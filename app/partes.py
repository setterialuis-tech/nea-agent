"""Partir la respuesta en varios mensajes de WhatsApp.

Dos caminos, y el segundo es opcional:

1. `partir`: reglas de código, deterministas. Parte por párrafos y listas, nunca
   corta una frase, una pregunta ni una URL, y respeta el máximo de mensajes.
   Siempre corre.
2. `dar_forma_con_modelo`: un modelo propio (`FORMAT_MODEL`) reparte el texto
   con el prompt del CRM (el «GPT formateador» de n8n). Su salida se VALIDA contra el original
   (enlaces, preguntas, largo); si algo no cuadra, se usa el camino 1. Un
   formateador que falla jamás pierde ni cambia lo que Nea quiso decir.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.formato_prompt import PROMPT_FORMATO_FABRICA
from app.multimedia import leer_salida_formato

logger = logging.getLogger("nea.partes")

# Un texto corto no se parte: tres burbujas de seis palabras cansan.
MINIMO_PARA_PARTIR = 200
# El formateador con modelo limpia también lo que va en un solo mensaje (quita «¡» y asteriscos,
# pone emojis), como el de n8n; un texto más corto que esto no vale una llamada.
MINIMO_PARA_FORMATEAR = 120
# Una parte más corta que esto se pega a su vecina.
MINIMO_DE_PARTE = 60

_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_FIN_DE_FRASE = re.compile(r"(?<=[.!?…])\s+(?=[¿¡A-ZÁÉÍÓÚÑ0-9\U0001F300-\U0001FAFF*_(\-•✅📍👉📌])")
_VINETA = re.compile(r"^\s*(?:[-•]|\d+[.)])\s+", re.M)
_ITEM_DE_LISTA = re.compile(r"^\s*(?:[-•*✅📍👉📌✔️▪️]|\d+[.)])\s+")


def _bloques(texto: str) -> list[str]:
    """Párrafos separados por línea en blanco; una lista se queda con su intro."""
    crudos = [b.strip() for b in re.split(r"\n\s*\n", texto.strip()) if b.strip()]
    return crudos


def _frases(bloque: str) -> list[str]:
    """Frases de un bloque, sin partir las URL."""
    protegidas: list[str] = []

    def guardar(m: re.Match[str]) -> str:
        protegidas.append(m.group(0))
        return f"{len(protegidas) - 1}"

    sin_urls = _URL.sub(guardar, bloque)
    trozos = [t.strip() for t in _FIN_DE_FRASE.split(sin_urls) if t.strip()]
    return [
        re.sub("(\\d+)", lambda m: protegidas[int(m.group(1))], t) for t in trozos
    ]


def _fusionar(partes: list[str], maximo: int, separador: str) -> list[str]:
    """Pega las vecinas más cortas hasta quedar en `maximo` (y sin partes enanas)."""
    partes = list(partes)
    while len(partes) > 1 and (
        len(partes) > maximo or min(len(p) for p in partes) < MINIMO_DE_PARTE
    ):
        # La pareja de vecinas con menos texto junto.
        i = min(range(len(partes) - 1), key=lambda k: len(partes[k]) + len(partes[k + 1]))
        partes[i : i + 2] = [partes[i] + separador + partes[i + 1]]
    return partes


def partir(texto: str, maximo: int) -> list[str]:
    """El texto, repartido en hasta `maximo` mensajes (al menos uno)."""
    texto = (texto or "").strip()
    if not texto:
        return []
    if maximo <= 1 or len(texto) < MINIMO_PARA_PARTIR:
        return [texto]

    bloques = _bloques(texto)
    if len(bloques) == 1:
        # Sin párrafos: se parte por frases. Una lista sin intro no se rompe.
        lineas = [l for l in bloques[0].split("\n") if l.strip()]
        if len(lineas) > 1 and sum(1 for l in lineas if _ITEM_DE_LISTA.match(l)) >= 2:
            return [bloques[0]]
        frases = _frases(bloques[0])
        if len(frases) < 2:
            return [bloques[0]]
        return _fusionar(frases, maximo, " ")
    return _fusionar(bloques, maximo, "\n\n")


# ---------------------------------------------------------------------------
# Formateador con modelo (opcional)
# ---------------------------------------------------------------------------

# Partes máximas que admite el formato de n8n (part_1 … part_4).
MAX_PARTES_FORMATO = 4


def prompt_de_sistema(prompt: str, maximo: int) -> str:
    """El prompt del formateador + el máximo de partes de esta respuesta (Agente → Mensajes).

    Espejo de `promptDeSistema` en `src/lib/formatear.ts` del CRM.
    """
    n = max(1, min(MAX_PARTES_FORMATO, int(maximo) if maximo else MAX_PARTES_FORMATO))
    return (
        f"{prompt.strip()}\n\n# LÍMITE DE ESTA RESPUESTA\n"
        f"Usa como máximo {n} parte(s) (part_1 a part_{n}); deja vacías las demás "
        "y reparte TODO el contenido en las que uses."
    )


def _urls(texto: str) -> set[str]:
    return {u.rstrip(".,;:!?)»\"'*_") for u in _URL.findall(texto)}


def validar(original: str, partes: list[str], maximo: int) -> str | None:
    """Por qué las partes del modelo no sirven, o None si sirven."""
    if not partes or len(partes) > maximo:
        return "número de partes fuera de rango"
    if any(not isinstance(p, str) or not p.strip() for p in partes):
        return "hay partes vacías"
    unido = "\n".join(partes)
    faltan = [u for u in _urls(original) if u not in unido]
    if faltan:
        return "perdió un enlace"
    if unido.count("?") != original.count("?"):
        return "cambió el número de preguntas"
    if len(_VINETA.findall(unido)) < len(_VINETA.findall(original)):
        return "quitó viñetas"
    largo, base = len(unido), max(len(original), 1)
    if not 0.7 <= largo / base <= 1.4:
        return "cambió demasiado el largo"
    return None


async def dar_forma_con_modelo(
    llm: Any, texto: str, maximo: int, prompt: str | None = None
) -> list[str] | None:
    """Reparte el texto con el modelo formateador. None = usa `partir`.

    `prompt` es el que el dueño editó en el CRM (Ajustes → IA → Formatear la
    respuesta); sin él, el de fábrica (el «GPT formateador» de n8n). Solo recibe la
    respuesta del agente: ni el historial ni nada del paciente.
    """
    if len(texto) < MINIMO_PARA_FORMATEAR:
        return None
    maximo = max(1, min(maximo, MAX_PARTES_FORMATO))
    try:
        reply = await llm.complete(
            [
                {"role": "system", "content": prompt_de_sistema(prompt or PROMPT_FORMATO_FABRICA, maximo)},
                {"role": "user", "content": texto},
            ]
        )
    except Exception as exc:  # el formateador no puede tumbar el turno
        logger.warning("formateador: falló (%s) — reglas de código", exc)
        return None
    crudo = (reply.content or "").strip()
    crudo = re.sub(r"^```(?:json)?\s*|\s*```$", "", crudo)
    try:
        partes = leer_salida_formato(json.loads(crudo))
    except ValueError:
        logger.warning("formateador: respuesta que no es JSON — reglas de código")
        return None
    if not partes:
        logger.warning("formateador: sin partes que se puedan leer — reglas de código")
        return None
    motivo = validar(texto, partes, maximo)
    if motivo:
        logger.warning("formateador: %s — reglas de código", motivo)
        return None
    return partes
