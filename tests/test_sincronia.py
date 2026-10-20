"""Sincronía de la memoria con el CRM: campañas, plantillas, chat humano y
entrantes con la IA apagada llegan al historial de Nea — sin duplicar."""
from __future__ import annotations

import asyncio

import httpx

from app.sincronia import a_memoria, quitar_marcas, sincronizar_historial
from tests.conftest import CRM_CONV_ID, CRM_URL, IDENTITY, mock_crm_basics, wa_body


def msg(i, direction="out", origin="template", text="hola", type_="text", ts=None, wamid="", status="delivered"):
    return {
        "id": f"m{i}",
        "waMessageId": wamid or f"wamid.crm{i}",
        "direction": direction,
        "origin": origin,
        "type": type_,
        "text": text,
        "status": status,
        "createdAt": ts or f"2026-10-01T15:00:0{i}.000Z",
    }


def historial(respx_mock, paginas):
    """Responde cada GET con la siguiente página; guarda los params."""
    llamadas = []
    cola = list(paginas)

    def responder(request):
        llamadas.append(dict(request.url.params))
        return httpx.Response(200, json=cola.pop(0) if cola else {"messages": [], "hasMore": False})

    respx_mock.get(f"{CRM_URL}/api/bot/messages").mock(side_effect=responder)
    return llamadas


async def conversacion(ctx):
    return await ctx.store.get_or_create_conversation(IDENTITY)


def textos(ctx, conv):
    return [(m.role, m.content) for m in ctx.store.messages if m.conversation_id == conv.id]


# ------------------------------------------------------------ traducción ---


def test_plantilla_ya_renderizada_va_como_assistant_con_su_origen():
    r = a_memoria(msg(1, text="Hola María, te esperamos el lunes"))
    assert r == ("assistant", "[Plantilla enviada] Hola María, te esperamos el lunes", "wamid.crm1", "crm_template")


def test_humano_desde_la_bandeja_y_desde_el_telefono():
    assert a_memoria(msg(1, origin="operator", text="Ya le mando el cuadro"))[3] == "crm_operator"
    r = a_memoria(msg(2, origin="manual", text="Le llamo mañana"))
    assert r[1].startswith("[Mensaje del equipo desde el teléfono] ") and r[3] == "crm_manual"


def test_el_paciente_entra_como_user_sin_marca_y_un_boton_ya_es_texto():
    assert a_memoria(msg(1, direction="in", origin="operator", text="Sí, quiero info")) == (
        "user", "Sí, quiero info", "wamid.crm1", "crm_user"
    )


def test_lo_de_nea_y_lo_fallido_no_entran():
    assert a_memoria(msg(1, origin="ai")) is None
    assert a_memoria(msg(2, origin="operator", status="failed")) is None


def test_adjunto_sin_texto_deja_marcador_y_el_vacio_se_descarta():
    assert a_memoria(msg(1, direction="in", type_="image", text=None))[1] == "[imagen]"
    assert a_memoria(msg(2, direction="in", type_="image", text="mi estudio"))[1] == "[imagen] mi estudio"
    assert a_memoria(msg(3, direction="in", text=None)) is None


def test_sin_wamid_la_clave_es_el_id_del_crm():
    m = msg(1)
    m["waMessageId"] = None
    assert a_memoria(m)[2] == "crm:m1"


def test_las_marcas_no_se_le_escapan_al_lead():
    assert quitar_marcas("[Plantilla enviada] Hola") == "Hola"
    assert quitar_marcas("[Mensaje del equipo desde el teléfono] Hola") == "Hola"
    assert quitar_marcas("Hola [Plantilla enviada]") == "Hola [Plantilla enviada]"


# -------------------------------------------------------- sincronización ---


async def test_primera_vez_sin_memoria_trae_el_hilo_y_fija_el_cursor(ctx, respx_mock):
    conv = await conversacion(ctx)
    llamadas = historial(respx_mock, [{"messages": [
        msg(1, text="Hola María, campaña de octubre"),
        msg(2, direction="in", text="Me interesa"),
        msg(3, origin="ai", text="respuesta de Nea"),
    ], "hasMore": False}])
    n = await sincronizar_historial(ctx, conv, CRM_CONV_ID)
    assert n == 2
    assert textos(ctx, conv) == [
        ("assistant", "[Plantilla enviada] Hola María, campaña de octubre"),
        ("user", "Me interesa"),
    ]
    assert conv.crm_sync_cursor == "2026-10-01T15:00:03.000Z|m3"
    assert "after" not in llamadas[0]


async def test_segunda_vez_pide_desde_el_cursor_y_no_duplica(ctx, respx_mock):
    conv = await conversacion(ctx)
    llamadas = historial(respx_mock, [
        {"messages": [msg(1)], "hasMore": False},
        {"messages": [], "hasMore": False},
        {"messages": [msg(1)], "hasMore": False},  # el CRM repite (borde de ms)
    ])
    await sincronizar_historial(ctx, conv, CRM_CONV_ID)
    await sincronizar_historial(ctx, conv, CRM_CONV_ID)
    assert llamadas[1]["after"] == "2026-10-01T15:00:01.000Z" and llamadas[1]["afterId"] == "m1"
    await sincronizar_historial(ctx, conv, CRM_CONV_ID)  # repetido: por wamid no entra
    assert len(textos(ctx, conv)) == 1


async def test_con_memoria_previa_solo_fija_el_cursor_sin_duplicar_lo_que_ya_tiene(ctx, respx_mock):
    conv = await conversacion(ctx)
    await ctx.store.add_message(conv.id, "user", "ya lo tenía")
    historial(respx_mock, [{"messages": [msg(1, direction="in", text="ya lo tenía")], "hasMore": False}])
    assert await sincronizar_historial(ctx, conv, CRM_CONV_ID) == 0
    assert len(textos(ctx, conv)) == 1
    assert conv.crm_sync_cursor == "2026-10-01T15:00:01.000Z|m1"


async def test_pagina_hasta_agotar(ctx, respx_mock):
    conv = await conversacion(ctx)
    conv.crm_sync_cursor = "2026-10-01T14:00:00.000Z|m0"
    llamadas = historial(respx_mock, [
        {"messages": [msg(1), msg(2, origin="operator", text="b")], "hasMore": True},
        {"messages": [msg(3, origin="operator", text="c")], "hasMore": False},
    ])
    assert await sincronizar_historial(ctx, conv, CRM_CONV_ID) == 3
    assert len(llamadas) == 2 and llamadas[1]["afterId"] == "m2"
    assert [r for r, _ in textos(ctx, conv)] == ["assistant"] * 3


async def test_excluir_salta_los_entrantes_del_turno_pero_el_cursor_los_rebasa(ctx, respx_mock):
    conv = await conversacion(ctx)
    conv.crm_sync_cursor = "2026-10-01T14:00:00.000Z|m0"
    historial(respx_mock, [{"messages": [
        msg(1, origin="operator", text="el doctor escribió"),
        msg(2, direction="in", text="mi pregunta", wamid="wamid.turno"),
    ], "hasMore": False}])
    await sincronizar_historial(ctx, conv, CRM_CONV_ID, excluir=["wamid.turno"])
    assert [t for _, t in textos(ctx, conv)] == ["[Mensaje del equipo] el doctor escribió"]
    assert conv.crm_sync_cursor.endswith("|m2")


async def test_crm_sin_endpoint_o_caido_no_rompe(ctx, respx_mock):
    conv = await conversacion(ctx)
    ruta = respx_mock.get(f"{CRM_URL}/api/bot/messages").mock(return_value=httpx.Response(404))
    assert await sincronizar_historial(ctx, conv, CRM_CONV_ID) == 0
    ruta.mock(return_value=httpx.Response(503))
    assert await sincronizar_historial(ctx, conv, CRM_CONV_ID) == 0
    assert conv.crm_sync_cursor is None and not ctx.store.messages


# ------------------------------------------------------ de punta a punta ---


async def test_turno_ve_la_campana_y_lo_que_dijo_el_humano(ctx, client, respx_mock):
    routes = mock_crm_basics(respx_mock)
    historial(respx_mock, [{"messages": [
        msg(1, text="Hola María, esta es la promo de octubre"),
        msg(2, origin="operator", text="Roger: te mando el cuadro de precios"),
        msg(3, direction="in", text="gracias, ¿cuánto cuesta?", wamid="wamid.001"),
    ], "hasMore": False}])
    await client.post("/webhook", content=wa_body(text="gracias, ¿cuánto cuesta?", wamid="wamid.001"))
    await asyncio.sleep(0.3)

    visto = [m["content"] for m in ctx.llm.calls[0]["messages"] if m["role"] != "system"]
    assert visto[0] == "[Plantilla enviada] Hola María, esta es la promo de octubre"
    assert visto[1] == "[Mensaje del equipo] Roger: te mando el cuadro de precios"
    # el entrante del turno entra UNA vez (lo guarda el turno, no la sincronía)
    assert visto.count("gracias, ¿cuánto cuesta?") == 1
    assert routes["messages"].call_count >= 1


async def test_con_la_ia_apagada_el_entrante_tambien_se_guarda(ctx, client, respx_mock):
    mock_crm_basics(respx_mock, ai_enabled=False)
    historial(respx_mock, [{"messages": [
        msg(1, origin="operator", text="Lo atiendo yo"),
        msg(2, direction="in", text="¿a qué hora abren?", wamid="wamid.009"),
    ], "hasMore": False}])
    await client.post("/webhook", content=wa_body(text="¿a qué hora abren?", wamid="wamid.009"))
    await asyncio.sleep(0.3)
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    assert [t for _, t in textos(ctx, conv)] == ["[Mensaje del equipo] Lo atiendo yo", "¿a qué hora abren?"]
    assert not ctx.llm.calls


async def test_el_tope_history_window_sigue_mandando(ctx, client, respx_mock):
    mock_crm_basics(respx_mock)
    historial(respx_mock, [{"messages": [
        msg(i % 10, text=f"campaña {i}", wamid=f"w{i}", ts=f"2026-10-01T15:{i:02d}:00.000Z")
        for i in range(1, 31)
    ], "hasMore": False}])
    await client.post("/webhook", content=wa_body(text="hola", wamid="wamid.777"))
    await asyncio.sleep(0.3)
    enviados = [m for m in ctx.llm.calls[0]["messages"] if m["role"] != "system"]
    assert len(enviados) <= ctx.settings.history_window
    assert enviados[-1]["content"] == "hola"
