"""Completar la memoria de Nea con lo que el CRM envió o recibió sin ella.

Nea guarda en `bot_message` lo que ELLA envía y lo que entra cuando ella está
al mando. Pero el CRM también habla (campañas, plantillas, seguimientos,
recordatorios, un humano en la bandeja) y también escucha con la IA apagada.
Sin esto, Nea contesta como si esas cosas no hubieran pasado: saluda de nuevo
a quien ya recibió la campaña, o ignora lo que el doctor acaba de prometer.

Es una LECTURA al CRM (`GET /api/bot/messages`) al empezar el turno, por
cursor — no un push: el CRM no necesita saber que Nea existe, si Nea está caída
nada se pierde (el cursor espera), y un reintento no duplica porque filas y
cursor se escriben juntos.

Nunca rompe un turno: si el CRM no ofrece el endpoint (versión vieja) o falla,
se sigue con la memoria que haya.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any, Iterable

from app.crm import CrmError
from app.state import AppContext, Conversation

logger = logging.getLogger("nea.sincronia")

PAGINA = 50
MAX_PAGINAS = 4
# Primera vez en una conversación sin memoria: cuánto hilo se trae.
INICIAL = 40

_ORIGEN_SALIENTE = {
    "template": ("crm_template", "[Plantilla enviada] "),
    "operator": ("crm_operator", "[Mensaje del equipo] "),
    "manual": ("crm_manual", "[Mensaje del equipo desde el teléfono] "),
}

_MARCADOR = {
    "image": "[imagen]",
    "video": "[video]",
    "audio": "[nota de voz]",
    "voice": "[nota de voz]",
    "document": "[documento]",
    "sticker": "[sticker]",
    "location": "[ubicación]",
    "contacts": "[contacto]",
}

# Lo que Nea pone para distinguir el origen en SU historial no debe volver a
# salir en los mensajes que ella escribe al lead.
_MARCA_INICIAL = re.compile(
    r"^\s*\[(?:Plantilla enviada|Mensaje del equipo(?: desde el teléfono)?)\]\s*"
)


def quitar_marcas(texto: str) -> str:
    return _MARCA_INICIAL.sub("", texto)


def a_memoria(m: dict[str, Any]) -> tuple[str, str, str, str] | None:
    """Un mensaje del CRM → (rol, contenido, clave, origen) o None si no cuenta.

    - Lo que salió con origen `ai` es de Nea (ella ya lo guardó): no se repite.
    - Lo que falló al enviar nunca llegó al paciente: no es parte de la charla.
    - El texto ya viene renderizado por el CRM (plantilla con el nombre
      sustituido, botón con su rótulo).
    """
    direction = m.get("direction")
    origin = m.get("origin")
    if direction == "out":
        if origin == "ai" or m.get("status") == "failed":
            return None
        fuente, prefijo = _ORIGEN_SALIENTE.get(origin, ("crm_operator", "[Mensaje del equipo] "))
        rol = "assistant"
    elif direction == "in":
        fuente, prefijo, rol = "crm_user", "", "user"
    else:
        return None
    texto = (m.get("text") or "").strip()
    marcador = _MARCADOR.get(m.get("type") or "")
    if marcador:
        texto = f"{marcador} {texto}".strip()
    if not texto:
        return None
    clave = m.get("waMessageId") or f"crm:{m.get('id')}"
    return rol, prefijo + texto, clave, fuente


# Holgura entre «nació la conversación en el CRM» y su primer mensaje: el CRM la crea unos
# segundos después de la hora que Meta le pone al mensaje.
_HOLGURA_INICIO = timedelta(minutes=15)


def desde_de(context: dict[str, Any] | None) -> datetime | None:
    """Desde cuándo cuenta la memoria de esta conversación: lo que el CRM tiene en la bandeja.

    Nea guarda por teléfono, y de la migración de n8n quedaron hasta 40 mensajes viejos de
    4.857 números: charlas de otras campañas, con otros precios y otros textos, que el
    modelo seguía como si fueran de hoy (cofinanciación del 45 %, «la sesión en vivo de
    hoy»). La conversación del CRM trae su fecha de inicio (`conversation.startedAt`); lo
    anterior no es de ella. Sin la fecha (CRM viejo) no se filtra nada.
    """
    raw = ((context or {}).get("conversation") or {}).get("startedAt")
    if not raw or not isinstance(raw, str):
        return None
    try:
        inicio = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if inicio.tzinfo is None:
        return None
    return inicio - _HOLGURA_INICIO


def _cursor_de(m: dict[str, Any]) -> str:
    return f"{m['createdAt']}|{m['id']}"


def _partir(cursor: str | None) -> tuple[str | None, str | None]:
    if not cursor or "|" not in cursor:
        return None, None
    after, after_id = cursor.split("|", 1)
    return after, after_id


async def sincronizar_historial(
    ctx: AppContext,
    conv: Conversation,
    crm_conv_id: str,
    excluir: Iterable[str] = (),
    desde: datetime | None = None,
) -> int:
    """Trae lo posterior al cursor y lo guarda. Devuelve cuántas filas entraron.

    `excluir`: wamids entrantes del turno en curso; el turno los guarda él
    mismo (con la multimedia ya descrita), así que aquí solo se saltan — el
    cursor sí los rebasa.
    """
    get_history = getattr(ctx.crm, "get_history", None)
    if not callable(get_history):
        return 0
    excluir = set(excluir)
    try:
        return await _sincronizar(ctx, conv, crm_conv_id, get_history, excluir, desde)
    except CrmError as exc:
        logger.warning("sincronía %s: el CRM no contestó (%s) — sigo sin ella", conv.wa_identity, exc)
    except Exception:  # la sincronía jamás tumba un turno
        logger.exception("sincronía %s: falló — sigo sin ella", conv.wa_identity)
    return 0


async def _sincronizar(
    ctx: AppContext,
    conv: Conversation,
    crm_conv_id: str,
    get_history: Any,
    excluir: set[str],
    desde: datetime | None = None,
) -> int:
    cursor = conv.crm_sync_cursor
    entradas: list[tuple[str, str, str, str]] = []
    ultimo: dict[str, Any] | None = None
    primera_vez = cursor is None

    # Sin cursor y con memoria local previa (instalación anterior a esta
    # función): lo anterior ya está, en su mayoría, guardado por Nea; traerlo
    # duplicaría al paciente. Solo se fija el cursor en lo último que hay.
    # La memoria vieja de otra época (n8n) no cuenta: sin nada de ESTA conversación, se trae.
    solo_fijar = primera_vez and bool(
        await ctx.store.recent_messages(conv.id, 1, desde=desde)
    )

    for _ in range(MAX_PAGINAS):
        after, after_id = _partir(cursor)
        data = await get_history(
            crm_conv_id,
            after=after,
            after_id=after_id,
            limit=INICIAL if primera_vez else PAGINA,
        )
        if data is None:  # CRM sin el endpoint o conversación desconocida
            return 0
        mensajes = data.get("messages") or []
        for m in mensajes:
            ultimo = m
            if solo_fijar or m.get("waMessageId") in excluir:
                continue
            e = a_memoria(m)
            if e:
                entradas.append(e)
        if not mensajes:
            break
        cursor = _cursor_de(mensajes[-1])
        if primera_vez or not data.get("hasMore"):
            break

    if ultimo is None:
        return 0
    nuevo = _cursor_de(ultimo)
    # Filas y cursor en una sola escritura: si se cae a medias, el reintento
    # no duplica ni se salta nada.
    await ctx.store.importar_historial_crm(conv.id, entradas, nuevo)
    conv.crm_sync_cursor = nuevo
    if entradas:
        logger.info(
            "sincronía %s: %d mensaje(s) del CRM incorporados a la memoria",
            conv.wa_identity,
            len(entradas),
        )
    return len(entradas)
