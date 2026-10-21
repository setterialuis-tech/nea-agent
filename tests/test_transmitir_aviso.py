"""Transmitir_aviso: la herramienta con el nombre que ya usa el prompt del negocio.

Llama al mismo POST /api/bot/qualify, pero con `reclamo` y `tipo` (PRESENCIAL | RECLAMO | AVANZADO)
para que el CRM avise por su webhook a n8n.
"""
from __future__ import annotations

import json

import httpx
import pytest

from app.tools import TIPOS_AVISO, ToolRuntime, tool_schemas
from tests.conftest import CRM_CONV_ID, CRM_URL, IDENTITY, make_ctx, make_settings

FICHA = (
    "Paciente: Ana Pérez, 41 años, Bogotá - Modalidad: Virtual\n"
    "Perfil: 92 kg | 1.62 m | Sin antecedentes\n"
    "Régimen: Contributivo\n"
    "Nota: martes en la tarde"
)


def _nombres(schemas):
    return [t["function"]["name"] for t in schemas]


def _schema(schemas):
    return next(t["function"] for t in schemas if t["function"]["name"] == "Transmitir_aviso")


def test_solo_se_ofrece_si_se_habilita_y_sustituye_a_qualify_lead():
    assert "Transmitir_aviso" not in _nombres(tool_schemas())
    assert "Transmitir_aviso" not in _nombres(tool_schemas(qualify=True))
    con_las_dos = _nombres(tool_schemas(qualify=True, transmitir_aviso=True))
    assert "Transmitir_aviso" in con_las_dos
    assert "qualify_lead" not in con_las_dos  # nunca las dos: confundiría al modelo


def test_el_esquema_pide_reclamo_y_tipo_con_los_tres_valores():
    f = _schema(tool_schemas(transmitir_aviso=True))
    assert f["parameters"]["required"] == ["reclamo", "tipo"]
    assert f["parameters"]["properties"]["tipo"]["enum"] == ["PRESENCIAL", "RECLAMO", "AVANZADO"]
    assert tuple(f["parameters"]["properties"]["tipo"]["enum"]) == TIPOS_AVISO


async def test_desactivada_no_llama_al_crm():
    ctx = make_ctx()  # transmitir_aviso_enabled=False por defecto
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("Transmitir_aviso", {"reclamo": FICHA, "tipo": "PRESENCIAL"})
    assert res["ok"] is False and res["error"] == "no_disponible"
    await ctx.crm.aclose()


async def test_exige_reclamo():
    ctx = make_ctx(make_settings(transmitir_aviso_enabled=True))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("Transmitir_aviso", {"reclamo": "   ", "tipo": "RECLAMO"})
    assert res["ok"] is False and res["error"] == "argumentos_invalidos"
    await ctx.crm.aclose()


@pytest.mark.parametrize("tipo", ["", "urgente", "Presencial y virtual", None])
async def test_un_tipo_invalido_se_rechaza_para_que_el_modelo_reintente(tipo, respx_mock):
    ctx = make_ctx(make_settings(transmitir_aviso_enabled=True))
    ruta = respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(return_value=httpx.Response(200, json={"ok": True}))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("Transmitir_aviso", {"reclamo": FICHA, "tipo": tipo})
    assert res["ok"] is False and res["error"] == "argumentos_invalidos"
    assert "PRESENCIAL, RECLAMO o AVANZADO" in res["detalle"]
    assert ruta.call_count == 0  # jamás se avisa con un tipo inventado
    await ctx.crm.aclose()


@pytest.mark.parametrize(
    "entrada,esperado",
    [("PRESENCIAL", "PRESENCIAL"), ("RECLAMO", "RECLAMO"), ("AVANZADO", "AVANZADO"), (" reclamo ", "RECLAMO")],
)
async def test_manda_el_reclamo_y_el_tipo_al_crm(entrada, esperado, respx_mock):
    ctx = make_ctx(make_settings(transmitir_aviso_enabled=True))
    ruta = respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(
        return_value=httpx.Response(
            200,
            json={
                "ok": True,
                "stageMoved": False,
                "notified": [{"channel": "webhook", "target": "webhook", "status": "enviado"}],
                "webhook": {"status": "enviado"},
            },
        )
    )
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("Transmitir_aviso", {"reclamo": FICHA, "tipo": entrada})
    assert res["ok"] is True
    cuerpo = json.loads(ruta.calls[0].request.content)
    assert cuerpo == {"conversationId": CRM_CONV_ID, "summary": FICHA, "tipo": esperado}
    await ctx.crm.aclose()


async def test_qualify_lead_sigue_mandando_solo_el_resumen(respx_mock):
    """Compatibilidad: el flujo de siempre no manda `tipo`."""
    ctx = make_ctx(make_settings(qualify_enabled=True))
    ruta = respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(return_value=httpx.Response(200, json={"ok": True, "notified": []}))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    await rt.execute("qualify_lead", {"summary": FICHA})
    assert json.loads(ruta.calls[0].request.content) == {"conversationId": CRM_CONV_ID, "summary": FICHA}
    await ctx.crm.aclose()


async def test_un_fallo_del_crm_no_rompe_el_turno(respx_mock):
    ctx = make_ctx(make_settings(transmitir_aviso_enabled=True))
    respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(return_value=httpx.Response(500))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("Transmitir_aviso", {"reclamo": FICHA, "tipo": "AVANZADO"})
    assert res["ok"] is False and res["error"] == "crm_error"
    await ctx.crm.aclose()


async def test_avisos_apagados_en_el_crm_se_toma_como_ok(respx_mock):
    ctx = make_ctx(make_settings(transmitir_aviso_enabled=True))
    respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(return_value=httpx.Response(200, json={"ok": True, "skipped": "disabled"}))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("Transmitir_aviso", {"reclamo": FICHA, "tipo": "PRESENCIAL"})
    assert res["ok"] is True and "desactivados" in res["nota"]
    await ctx.crm.aclose()
