"""Seguimiento: UN empujón y solo uno, marcado ANTES de enviar."""
from __future__ import annotations

import asyncio
from datetime import timedelta

import httpx

from app.followup import FollowupWorker
from app.llm import LlmReply
from app.state import utcnow
from app.turn import conversation_lock
from tests.conftest import (
    CRM_CONV_ID,
    CRM_URL,
    IDENTITY,
    crm_context,
    make_ctx,
)


async def preparar_conversacion(ctx, hace_horas: float = 5.0):
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    await ctx.store.add_message(conv.id, "user", "me interesa, luego te digo")
    await ctx.store.add_message(conv.id, "assistant", "va, ¿mañana o pasado?")
    await ctx.store.update_conversation(
        conv.id,
        crm_conversation_id=CRM_CONV_ID,
        greeted=True,
        followup_due_at=utcnow() - timedelta(hours=hace_horas - 4),
    )
    return conv


async def test_followup_un_solo_empujon(respx_mock):
    ctx = make_ctx()
    ctx.llm.replies = [LlmReply(content="¿Seguimos donde nos quedamos? 😊")]
    conv = await preparar_conversacion(ctx)
    respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context())
    )
    messages = respx_mock.post(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(200, json={"messageId": "m1"})
    )
    worker = FollowupWorker(ctx)

    await worker.tick()
    assert messages.call_count == 1
    assert ctx.store.conversations[conv.id].followup_sent is True

    # segundo barrido, y hasta un due_at fantasma: jamás un segundo empujón
    await ctx.store.update_conversation(
        conv.id, followup_due_at=utcnow() - timedelta(minutes=1)
    )
    await worker.tick()
    await worker.tick()
    assert messages.call_count == 1
    await ctx.crm.aclose()


async def test_followup_ventana_cerrada_se_omite_y_consume(respx_mock):
    ctx = make_ctx()
    conv = await preparar_conversacion(ctx)
    respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context(window_open=False))
    )
    messages = respx_mock.post(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(200, json={"messageId": "m1"})
    )
    worker = FollowupWorker(ctx)
    await worker.tick()
    assert messages.call_count == 0  # omitido con log
    # el claim ocurrió ANTES del envío: aunque "crashee" después, a lo sumo uno
    assert ctx.store.conversations[conv.id].followup_sent is True
    await worker.tick()
    assert messages.call_count == 0
    await ctx.crm.aclose()


async def test_followup_no_aplica_a_conversacion_cerrada(respx_mock):
    ctx = make_ctx()
    conv = await preparar_conversacion(ctx)
    await ctx.store.update_conversation(conv.id, phase="cerrada")
    context_route = respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context())
    )
    worker = FollowupWorker(ctx)
    await worker.tick()
    assert context_route.call_count == 0  # ni siquiera se consideró
    assert ctx.store.conversations[conv.id].followup_sent is False
    await ctx.crm.aclose()


async def test_followup_llm_caido_se_omite_sin_reintento_futuro(respx_mock):
    from app.llm import LlmExhausted

    ctx = make_ctx()
    ctx.llm.raise_exc = LlmExhausted("apagado")
    conv = await preparar_conversacion(ctx)
    respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context())
    )
    messages = respx_mock.post(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(200, json={"messageId": "m1"})
    )
    worker = FollowupWorker(ctx)
    await worker.tick()
    assert messages.call_count == 0
    assert ctx.store.conversations[conv.id].followup_sent is True  # consumido
    await ctx.crm.aclose()


async def test_followup_espera_el_turno_vivo_y_se_calla_si_el_lead_escribio(respx_mock):
    """El empujón se reclama antes de enviarlo. Si mientras espera su turno el
    lead escribe, el "¿seguimos?" queda fuera de lugar — y encimado con la
    respuesta del turno vivo."""
    ctx = make_ctx()
    ctx.llm.replies = [LlmReply(content="¿Seguimos donde nos quedamos? 😊")]
    conv = await preparar_conversacion(ctx)
    respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context())
    )
    messages = respx_mock.post(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(200, json={"messageId": "m1"})
    )

    # Un turno del lead ya está en vuelo: tiene el candado tomado.
    async with conversation_lock(ctx, IDENTITY):
        tarea = asyncio.create_task(FollowupWorker(ctx).tick())
        await asyncio.sleep(0.05)
        assert messages.call_count == 0, "el empujón no esperó al turno vivo"
        # Ese turno registra el mensaje del lead y luego suelta el candado.
        await ctx.store.update_conversation(conv.id, last_inbound_at=utcnow())
    await tarea

    assert messages.call_count == 0  # ya hubo conversación: sin empujón
    await ctx.crm.aclose()


# --- Mensajes sin letras reales (21-oct: salió un «.» y un emoji suelto) ------

import pytest

from app.formato import cuenta_letras
from app.profile import BusinessProfile, profile_from_payload
from app.turn import _respuesta_invalida


@pytest.mark.parametrize("texto", [".", "👍", "", "   ", "¿?", "…", "12 😊"])
async def test_followup_descarta_mensaje_sin_letras(respx_mock, caplog, texto):
    ctx = make_ctx()
    ctx.llm.replies = [LlmReply(content=texto)]
    conv = await preparar_conversacion(ctx)
    respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context())
    )
    messages = respx_mock.post(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(200, json={"messageId": "m1"})
    )
    with caplog.at_level("WARNING", logger="nea.followup"):
        await FollowupWorker(ctx).tick()
    assert messages.call_count == 0
    assert "no escribió un mensaje" in caplog.text
    assert ctx.store.conversations[conv.id].followup_sent is True
    await ctx.crm.aclose()


async def test_followup_texto_normal_se_envia(respx_mock):
    ctx = make_ctx()
    ctx.llm.replies = [LlmReply(content="Hola, ¿seguimos? 😊")]
    await preparar_conversacion(ctx)
    respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context())
    )
    messages = respx_mock.post(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(200, json={"messageId": "m1"})
    )
    await FollowupWorker(ctx).tick()
    assert messages.call_count == 1
    await ctx.crm.aclose()


def test_cuenta_letras():
    assert cuenta_letras("Sí") == 2
    assert cuenta_letras("👍 .") == 0
    assert cuenta_letras(None) == 0


def test_turno_descarta_respuesta_sin_palabras():
    for basura in (".", "👍", "…"):
        assert _respuesta_invalida(basura, []) is not None
    assert _respuesta_invalida("Sí 👍", []) is None
    assert _respuesta_invalida("", []) is None


# --- Seguimiento rápido configurado desde el CRM ------------------------------

def test_perfil_lee_followup_del_crm():
    p = profile_from_payload(
        {"followup": {"enabled": True, "hours": 6, "prompt": "  Sé breve.  "}}, "Nea"
    )
    assert (p.followup_enabled, p.followup_hours, p.followup_prompt) == (True, 6.0, "Sé breve.")


def test_perfil_sin_followup_es_como_antes():
    p = profile_from_payload({}, "Nea")
    assert (p.followup_enabled, p.followup_hours, p.followup_prompt) == (None, None, None)
    p = profile_from_payload({"followup": {"enabled": "si", "hours": 999, "prompt": 5}}, "Nea")
    assert (p.followup_enabled, p.followup_hours, p.followup_prompt) == (None, None, None)


class _Perfil:
    def __init__(self, perfil):
        self._p = perfil

    async def get(self):
        return self._p


async def test_followup_apagado_en_el_crm_no_envia(respx_mock):
    ctx = make_ctx()
    ctx.profile = _Perfil(BusinessProfile(followup_enabled=False))
    conv = await preparar_conversacion(ctx)
    respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context())
    )
    messages = respx_mock.post(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(200, json={"messageId": "m1"})
    )
    await FollowupWorker(ctx).tick()
    assert messages.call_count == 0
    assert ctx.store.conversations[conv.id].followup_sent is True
    await ctx.crm.aclose()


async def test_followup_usa_el_prompt_del_crm(respx_mock):
    ctx = make_ctx()
    ctx.profile = _Perfil(BusinessProfile(followup_enabled=True, followup_prompt="CRITERIO-DEL-DUENO"))
    ctx.llm.replies = [LlmReply(content="Hola, ¿seguimos?")]
    await preparar_conversacion(ctx)
    respx_mock.get(f"{CRM_URL}/api/bot/context").mock(
        return_value=httpx.Response(200, json=crm_context())
    )
    respx_mock.post(f"{CRM_URL}/api/bot/messages").mock(
        return_value=httpx.Response(200, json={"messageId": "m1"})
    )
    await FollowupWorker(ctx).tick()
    vistos = " ".join(str(m["content"]) for m in ctx.llm.calls[-1]["messages"])
    assert "CRITERIO-DEL-DUENO" in vistos
    await ctx.crm.aclose()
