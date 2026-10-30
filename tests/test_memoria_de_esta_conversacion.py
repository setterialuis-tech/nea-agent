"""La IA solo recuerda lo de ESTA conversación del CRM.

Nea guarda por teléfono, y de la migración de n8n quedaron mensajes viejos de otras
campañas (cofinanciación del 45 %, «la sesión en vivo de hoy») que el modelo seguía como
si fueran de hoy; además la marca `greeted` de esas filas hacía que el primer mensaje de
hoy saliera sin saludo ni petición de datos.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from app.llm import LlmReply
from app.main import create_app
from app.profile import BusinessProfile
from app.prompt import build_system_prompt
from app.sincronia import desde_de, sincronizar_historial
from app.state import BotMessage, Conversation, utcnow
from tests.conftest import (
    CRM_CONV_ID,
    CRM_URL,
    IDENTITY,
    crm_context,
    make_ctx,
    mock_crm_basics,
    wa_body,
)

VIEJO = "Hay cofinanciación del 45% en la sesión en vivo de hoy"


def _contexto(started_at: str | None) -> dict:
    ctx = crm_context()
    if started_at:
        ctx["conversation"]["startedAt"] = started_at
    return ctx


async def _sembrar_memoria_vieja(ctx) -> None:
    """Una conversación de n8n: marcada como saludada, con mensajes de hace semanas."""
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    await ctx.store.update_conversation(conv.id, greeted=True)
    hace_semanas = utcnow() - timedelta(days=20)
    for i, (rol, texto) in enumerate((("user", "¿hay descuento?"), ("assistant", VIEJO))):
        ctx.store.messages.append(
            BotMessage(
                id=900 + i,
                conversation_id=conv.id,
                role=rol,
                content=texto,
                created_at=hace_semanas,
            )
        )


async def _turno(respx_mock, ctx, contexto: dict, texto: str = "¡Hola! Quiero más información."):
    routes = mock_crm_basics(respx_mock)
    routes["context"].mock(return_value=httpx.Response(200, json=contexto))
    app = create_app(ctx=ctx)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://bot.test"
    ) as client:
        await client.post("/webhook", content=wa_body(text=texto))
        await asyncio.sleep(0.35)
    await ctx.crm.aclose()
    return ctx.llm.calls[0]["messages"]


def _todo(messages) -> str:
    return "\n".join(str(m["content"]) for m in messages)


async def test_la_memoria_de_otra_epoca_no_llega_al_modelo_y_saluda_como_primer_contacto(respx_mock):
    ctx = make_ctx()
    ctx.llm.replies = [LlmReply(content="¡Hola! Soy Angie.")]
    await _sembrar_memoria_vieja(ctx)
    inicio = (utcnow() - timedelta(seconds=30)).isoformat()
    messages = await _turno(respx_mock, ctx, _contexto(inicio))
    texto = _todo(messages)
    assert "cofinanciación" not in texto and "sesión en vivo" not in texto
    assert "Es el PRIMER contacto" in texto
    assert any(m["role"] == "user" and "Quiero más información" in m["content"] for m in messages)


async def test_sin_la_fecha_de_inicio_se_conserva_la_memoria(respx_mock):
    """Un CRM viejo no manda `startedAt`: no se filtra nada, como siempre."""
    ctx = make_ctx()
    ctx.llm.replies = [LlmReply(content="Hola de nuevo")]
    await _sembrar_memoria_vieja(ctx)
    messages = await _turno(respx_mock, ctx, _contexto(None))
    assert "cofinanciación" in _todo(messages)
    assert "Es el PRIMER contacto" not in _todo(messages)


async def test_una_conversacion_con_su_propio_hilo_conserva_su_memoria(respx_mock):
    """Lo posterior al inicio de la conversación del CRM sí cuenta."""
    ctx = make_ctx()
    ctx.llm.replies = [LlmReply(content="Claro")]
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    await ctx.store.update_conversation(conv.id, greeted=True)
    await ctx.store.add_message(conv.id, "assistant", "Soy Angie, ¿tu nombre y ciudad?")
    inicio = (utcnow() - timedelta(hours=2)).isoformat()
    messages = await _turno(respx_mock, ctx, _contexto(inicio), texto="Marco, Bogotá")
    assert "Soy Angie, ¿tu nombre y ciudad?" in _todo(messages)
    assert "Es el PRIMER contacto" not in _todo(messages)


def test_desde_de_lee_la_fecha_con_holgura_y_tolera_lo_raro():
    d = desde_de({"conversation": {"startedAt": "2026-10-29T21:20:13.218Z"}})
    assert d == datetime(2026, 10, 29, 21, 5, 13, 218000, tzinfo=timezone.utc)
    assert desde_de(None) is None
    assert desde_de({"conversation": {}}) is None
    assert desde_de({"conversation": {"startedAt": "ayer"}}) is None
    assert desde_de({"conversation": {"startedAt": "2026-10-29T21:20:13"}}) is None  # sin zona


async def test_la_sincronia_trae_el_hilo_del_crm_aunque_haya_memoria_vieja(respx_mock):
    """Antes, con memoria previa solo se fijaba el cursor y el hilo de hoy no entraba."""
    ctx = make_ctx()
    await _sembrar_memoria_vieja(ctx)
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    respx_mock.get(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "messages": [
                    {
                        "id": "m1",
                        "waMessageId": "wamid.hoy",
                        "direction": "out",
                        "origin": "template",
                        "type": "text",
                        "text": "Hola, te escribimos de la clínica",
                        "status": "delivered",
                        "createdAt": "2026-10-30T10:00:00.000Z",
                    }
                ],
                "hasMore": False,
            },
        )
    )
    desde = datetime(2026, 10, 30, 9, 45, tzinfo=timezone.utc)
    n = await sincronizar_historial(ctx, conv, CRM_CONV_ID, desde=desde)
    assert n == 1
    assert any("te escribimos de la clínica" in m.content for m in ctx.store.messages)
    await ctx.crm.aclose()


def test_el_anuncio_solo_se_menciona_si_el_negocio_no_lo_prohibe():
    perfil = BusinessProfile(agent_name="Angie", instructions="Nunca menciones el anuncio.")
    system = build_system_prompt(
        profile=perfil,
        context=crm_context(ad_headline="Chatea con nosotros"),
        conv=Conversation(id=1, wa_identity=IDENTITY),
        referral_headline="Chatea con nosotros",
    )
    assert "mencionando el anuncio" not in system
    assert "menciónalo" not in system
    assert "las instrucciones del negocio lo prohíban" in system
    assert "SOLO si las instrucciones del negocio no lo prohíben" in system
