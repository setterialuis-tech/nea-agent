"""create_quote: Nea pide al CRM una cotización en PDF; el precio sale SOLO de la tabla del CRM."""
from __future__ import annotations

import json

import httpx

from app.tools import ToolRuntime, tool_schemas
from tests.conftest import CRM_CONV_ID, CRM_URL, IDENTITY, make_ctx, make_settings

ITEMS = [{"partida": "Drywall: tabique simple", "cantidad": 50}]


def _nombres(schemas):
    return [t["function"]["name"] for t in schemas]


async def _runtime(**settings):
    ctx = make_ctx(make_settings(**settings)) if settings else make_ctx()
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    return ctx, ToolRuntime(ctx, conv, CRM_CONV_ID)


def test_la_herramienta_solo_se_ofrece_si_se_habilita():
    assert "create_quote" not in _nombres(tool_schemas())
    assert "create_quote" in _nombres(tool_schemas(quotes=True))


async def test_desactivada_no_llama_al_crm():
    ctx, rt = await _runtime()
    res = await rt.execute("create_quote", {"items": ITEMS})
    assert res["ok"] is False and res["error"] == "no_disponible"
    await ctx.crm.aclose()


async def test_exige_partidas_con_cantidad_positiva():
    ctx, rt = await _runtime(quotes_enabled=True)
    for args in ({}, {"items": []}, {"items": [{"partida": "x", "cantidad": 0}]}, {"items": [{"partida": "", "cantidad": 2}]}):
        res = await rt.execute("create_quote", args)
        assert res["ok"] is False and res["error"] == "argumentos_invalidos"
    await ctx.crm.aclose()


async def test_manda_partidas_y_datos_y_devuelve_codigo_y_rango(respx_mock):
    ctx, rt = await _runtime(quotes_enabled=True)
    ruta = respx_mock.post(f"{CRM_URL}/api/bot/quotes").mock(
        return_value=httpx.Response(
            200,
            json={"ok": True, "code": "COT-2026-0001", "sent": True, "range": "USD 900.00 – USD 1,300.00"},
        )
    )
    res = await rt.execute(
        "create_quote",
        {"items": [{"partida": "Drywall: tabique simple", "cantidad": "50"}], "customer_name": "Carlos", "reference": "Oficina en Miraflores"},
    )
    assert res["ok"] is True and res["codigo"] == "COT-2026-0001" and "1,300" in res["rango"]
    cuerpo = json.loads(ruta.calls[0].request.content)
    assert cuerpo == {
        "conversationId": CRM_CONV_ID,
        "items": [{"partida": "Drywall: tabique simple", "cantidad": 50.0}],
        "customerName": "Carlos",
        "reference": "Oficina en Miraflores",
    }
    await ctx.crm.aclose()


async def test_partida_fuera_de_la_tabla_vuelve_con_la_lista_valida(respx_mock):
    ctx, rt = await _runtime(quotes_enabled=True)
    respx_mock.post(f"{CRM_URL}/api/bot/quotes").mock(
        return_value=httpx.Response(
            422,
            json={"error": {"code": "partida_desconocida", "message": "No están en la tabla: Piscina."}, "validas": ["Drywall: tabique simple"]},
        )
    )
    res = await rt.execute("create_quote", {"items": [{"partida": "Piscina", "cantidad": 1}]})
    assert res["ok"] is False and res["error"] == "partida_desconocida"
    assert res["validas"] == ["Drywall: tabique simple"]
    await ctx.crm.aclose()


async def test_guardada_pero_no_enviada_pide_handoff(respx_mock):
    ctx, rt = await _runtime(quotes_enabled=True)
    respx_mock.post(f"{CRM_URL}/api/bot/quotes").mock(
        return_value=httpx.Response(200, json={"ok": True, "code": "COT-2026-0002", "sent": False, "sendError": "ventana cerrada"})
    )
    res = await rt.execute("create_quote", {"items": ITEMS})
    assert res["ok"] is False and res["error"] == "no_enviada" and "handoff" in res["detalle"]
    await ctx.crm.aclose()


async def test_limite_diario_no_rompe_la_conversacion(respx_mock):
    ctx, rt = await _runtime(quotes_enabled=True)
    respx_mock.post(f"{CRM_URL}/api/bot/quotes").mock(
        return_value=httpx.Response(429, json={"error": {"code": "limite_diario", "message": "pasa al asesor"}})
    )
    res = await rt.execute("create_quote", {"items": ITEMS})
    assert res["ok"] is False and res["error"] == "limite_diario"
    await ctx.crm.aclose()


async def test_un_crm_sin_el_modulo_no_rompe_la_conversacion(respx_mock):
    ctx, rt = await _runtime(quotes_enabled=True)
    respx_mock.post(f"{CRM_URL}/api/bot/quotes").mock(return_value=httpx.Response(404))
    res = await rt.execute("create_quote", {"items": ITEMS})
    assert res["ok"] is False and res["error"] == "crm_error"
    await ctx.crm.aclose()
