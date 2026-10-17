"""send_media: imagen/video real de WhatsApp, una vez por conversación, tras el texto."""
from __future__ import annotations

import asyncio
import json

import httpx

from app.llm import LlmReply, ToolCall
from app.tools import ToolRuntime, tool_schemas
from tests.conftest import CRM_CONV_ID, CRM_URL, IDENTITY, make_ctx, make_settings, mock_crm_basics, wa_body

IMG = "https://i.postimg.cc/y8GgK6SL/dr.jpg"
VID = "https://files.catbox.moe/9hfwag.mp4"


def _llamada(url=IMG, tipo="image", caption="Dr. Roger Méndez\nCirugía bariátrica"):
    return LlmReply(
        content=None,
        tool_calls=[ToolCall(id="m1", name="send_media", arguments={"url": url, "type": tipo, "caption": caption})],
    )


def _cuerpos_de_mensajes(routes):
    return [json.loads(c.request.content) for c in routes["messages"].calls]


def test_la_herramienta_solo_se_ofrece_si_se_habilita():
    nombres = lambda s: [t["function"]["name"] for t in s]  # noqa: E731
    assert "send_media" not in nombres(tool_schemas())
    assert "send_media" in nombres(tool_schemas(media=True))


async def test_desactivada_no_envia_nada():
    ctx = make_ctx()  # send_media_enabled=False por defecto
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("send_media", {"url": IMG, "type": "image"})
    assert res["ok"] is False and res["error"] == "no_disponible"
    assert rt.media_queue == []
    await ctx.crm.aclose()


async def test_valida_argumentos_y_deduplica_en_el_turno():
    ctx = make_ctx(make_settings(send_media_enabled=True))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    assert (await rt.execute("send_media", {"url": "http://x/a.jpg", "type": "image"}))["error"] == "argumentos_invalidos"
    assert (await rt.execute("send_media", {"url": IMG, "type": "audio"}))["error"] == "argumentos_invalidos"
    assert (await rt.execute("send_media", {"url": IMG, "type": "image", "caption": "a" * 2000}))["ok"] is True
    assert len(rt.media_queue[0]["caption"]) == 1024
    assert (await rt.execute("send_media", {"url": IMG, "type": "image"}))["error"] == "ya_enviado"
    await ctx.crm.aclose()


async def test_ya_enviado_en_la_conversacion_se_rechaza():
    ctx = make_ctx(make_settings(send_media_enabled=True))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    await ctx.store.marcar_media_enviada(conv.id, IMG)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    assert (await rt.execute("send_media", {"url": IMG, "type": "image"}))["error"] == "ya_enviado"
    await ctx.crm.aclose()


async def test_el_archivo_sale_despues_del_texto_con_su_caption(ctx, client, respx_mock):
    ctx.settings.send_media_enabled = True
    routes = mock_crm_basics(respx_mock)
    ctx.llm.replies = [_llamada(), LlmReply(content="Te comparto una foto del Dr. Roger para que lo conozcas.")]
    await client.post("/webhook", content=wa_body(text="quiero conocer al doctor"))
    await asyncio.sleep(0.3)

    cuerpos = _cuerpos_de_mensajes(routes)
    assert len(cuerpos) == 2
    assert "text" in cuerpos[0] and "media" not in cuerpos[0]
    assert cuerpos[1]["media"] == {
        "url": IMG,
        "type": "image",
        "caption": "Dr. Roger Méndez\nCirugía bariátrica",
    }
    # Quedó registrado: pedirlo otra vez en la misma conversación se rechaza.
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    assert await ctx.store.media_ya_enviada(conv.id, IMG)


async def test_sin_texto_no_se_envia_el_archivo(ctx, client, respx_mock):
    ctx.settings.send_media_enabled = True
    routes = mock_crm_basics(respx_mock)
    ctx.llm.replies = [_llamada(), LlmReply(content="")]
    await client.post("/webhook", content=wa_body(text="hola"))
    await asyncio.sleep(0.3)
    assert all("media" not in b for b in _cuerpos_de_mensajes(routes))


async def test_si_el_crm_rechaza_el_medio_no_se_marca_como_enviado(ctx, client, respx_mock):
    ctx.settings.send_media_enabled = True
    routes = mock_crm_basics(respx_mock)

    def responder(request):
        return httpx.Response(422 if "media" in json.loads(request.content) else 200, json={"messageId": "m"})

    routes["messages"].mock(side_effect=responder)
    ctx.llm.replies = [_llamada(VID, "video"), LlmReply(content="Mira este video corto del procedimiento.")]
    await client.post("/webhook", content=wa_body(text="quiero ver un video"))
    await asyncio.sleep(0.3)
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    assert not await ctx.store.media_ya_enviada(conv.id, VID)


PDF = "https://files.catbox.moe/brochure-torre-norte.pdf"


async def test_un_brochure_pdf_se_encola_como_document():
    ctx = make_ctx(make_settings(send_media_enabled=True))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("send_media", {"url": PDF, "type": "document", "caption": "Brochure Torre Norte"})
    assert res["ok"] is True
    assert rt.media_queue == [{"url": PDF, "type": "document", "caption": "Brochure Torre Norte"}]
    # el mismo brochure no se manda dos veces en la conversación
    assert (await rt.execute("send_media", {"url": PDF, "type": "document"}))["error"] == "ya_enviado"
    await ctx.crm.aclose()


def test_la_herramienta_anuncia_document_en_su_esquema():
    esquema = next(t for t in tool_schemas(media=True) if t["function"]["name"] == "send_media")
    assert "document" in esquema["function"]["parameters"]["properties"]["type"]["enum"]
