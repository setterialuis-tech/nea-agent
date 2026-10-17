"""qualify_lead: Nea avisa al CRM que el lead quedó calificado (etapa + resumen + aviso al asesor)."""
from __future__ import annotations

import json

import httpx

from app.tools import ToolRuntime, tool_schemas
from tests.conftest import CRM_CONV_ID, CRM_URL, IDENTITY, make_ctx, make_settings

RESUMEN = "Ana Pérez · quiere vender depto en Miraflores · plazo 3 meses · llamada mañana 10:00"


def _nombres(schemas):
    return [t["function"]["name"] for t in schemas]


def test_la_herramienta_solo_se_ofrece_si_se_habilita():
    assert "qualify_lead" not in _nombres(tool_schemas())
    assert "qualify_lead" in _nombres(tool_schemas(qualify=True))


async def test_desactivada_no_llama_al_crm():
    ctx = make_ctx()  # qualify_enabled=False por defecto
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("qualify_lead", {"summary": RESUMEN})
    assert res["ok"] is False and res["error"] == "no_disponible"
    await ctx.crm.aclose()


async def test_exige_resumen():
    ctx = make_ctx(make_settings(qualify_enabled=True))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("qualify_lead", {"summary": "   "})
    assert res["ok"] is False and res["error"] == "argumentos_invalidos"
    await ctx.crm.aclose()


async def test_manda_el_resumen_y_cuenta_los_avisos_enviados(respx_mock):
    ctx = make_ctx(make_settings(qualify_enabled=True))
    ruta = respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "stageMoved": True,
                "notified": [
                    {"channel": "email", "target": "as***@casa.com", "status": "enviado"},
                    {"channel": "whatsapp", "target": "*******8777", "status": "fallido", "error": "plantilla"},
                ],
            },
        )
    )
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("qualify_lead", {"summary": RESUMEN})
    assert res["ok"] is True and res["avisos_enviados"] == 1
    cuerpo = json.loads(ruta.calls[0].request.content)
    assert cuerpo == {"conversationId": CRM_CONV_ID, "summary": RESUMEN}
    await ctx.crm.aclose()


async def test_con_los_avisos_apagados_en_el_crm_sigue_el_flujo(respx_mock):
    ctx = make_ctx(make_settings(qualify_enabled=True))
    respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(
        return_value=httpx.Response(200, json={"ok": True, "skipped": "disabled"})
    )
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("qualify_lead", {"summary": RESUMEN})
    assert res["ok"] is True and "desactivados" in res["nota"]
    await ctx.crm.aclose()


async def test_un_crm_sin_el_modulo_no_rompe_la_conversacion(respx_mock):
    ctx = make_ctx(make_settings(qualify_enabled=True))
    respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(return_value=httpx.Response(404))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("qualify_lead", {"summary": RESUMEN})
    assert res["ok"] is False and res["error"] == "crm_error"
    await ctx.crm.aclose()
