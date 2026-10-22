"""Contactos sin teléfono (WhatsApp lo oculta si la persona usa nombre de usuario).

Caso real, Roger 2026-10-22: Elsa Mateo llegó como contacto `bsuid:` sin teléfono, Angie la
pasó al equipo sin saberlo y el aviso a n8n salió con el número vacío. Ahora el CRM manda
`contact.phone: null` en el contexto, Nea se lo dice al modelo (que pide el número una vez) y
lo reenvía en `Transmitir_aviso(telefono=...)`.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

import httpx

from app.profile import BusinessProfile
from app.prompt import build_system_prompt
from app.state import Conversation
from app.tools import ToolRuntime, tool_schemas
from tests.conftest import CRM_CONV_ID, CRM_URL, IDENTITY, make_ctx, make_settings

NOW = datetime(2026, 10, 22, 19, 0, tzinfo=timezone.utc)
FICHA = "Paciente: Elsa Mateo, 46 años, República Dominicana - Modalidad: Teleconsulta EXTERIOR\nPerfil: 80 kg | 1.5 m | Diabetes tipo 2"
MARCA = "TELÉFONO FALTANTE"


def _prompt(contact: dict | None) -> str:
    context = {"contact": contact} if contact is not None else None
    return build_system_prompt(
        profile=BusinessProfile(),
        context=context,
        conv=Conversation(id=1, wa_identity="bsuid:DO.123", greeted=True),
        now=NOW,
    )


def test_sin_telefono_en_el_crm_el_modelo_lo_sabe_y_debe_pedirlo():
    p = _prompt({"name": "maru", "channel": "whatsapp", "phone": None})
    assert MARCA in p
    assert "código de país" in p
    assert "telefono" in p


def test_con_telefono_no_se_pide_nada():
    assert MARCA not in _prompt({"name": "Ana", "channel": "whatsapp", "phone": "573165001020"})


def test_si_el_crm_no_manda_el_dato_no_se_asume_que_falta():
    assert MARCA not in _prompt({"name": "Gerardo"})  # CRM viejo: sin clave `phone`
    assert MARCA not in _prompt(None)  # contexto no disponible


def test_en_instagram_o_messenger_no_se_pide_un_whatsapp():
    for canal in ("instagram", "messenger"):
        assert MARCA not in _prompt({"name": "x", "channel": canal, "phone": None})


def test_el_esquema_ofrece_telefono_como_opcional():
    f = next(t["function"] for t in tool_schemas(transmitir_aviso=True) if t["function"]["name"] == "Transmitir_aviso")
    assert "telefono" in f["parameters"]["properties"]
    assert f["parameters"]["required"] == ["reclamo", "tipo"]


async def test_el_telefono_dado_por_el_paciente_viaja_al_crm(respx_mock):
    ctx = make_ctx(make_settings(transmitir_aviso_enabled=True))
    ruta = respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(return_value=httpx.Response(200, json={"ok": True, "notified": []}))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    res = await rt.execute("Transmitir_aviso", {"reclamo": FICHA, "tipo": "PRESENCIAL", "telefono": " +1 809 555 1234 "})
    assert res["ok"] is True
    assert json.loads(ruta.calls[0].request.content) == {
        "conversationId": CRM_CONV_ID,
        "summary": FICHA,
        "tipo": "PRESENCIAL",
        "telefono": "+1 809 555 1234",
    }
    await ctx.crm.aclose()


async def test_sin_telefono_la_llamada_queda_como_siempre(respx_mock):
    ctx = make_ctx(make_settings(transmitir_aviso_enabled=True))
    ruta = respx_mock.post(f"{CRM_URL}/api/bot/qualify").mock(return_value=httpx.Response(200, json={"ok": True, "notified": []}))
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID)
    await rt.execute("Transmitir_aviso", {"reclamo": FICHA, "tipo": "PRESENCIAL", "telefono": "  "})
    assert json.loads(ruta.calls[0].request.content) == {"conversationId": CRM_CONV_ID, "summary": FICHA, "tipo": "PRESENCIAL"}
    await ctx.crm.aclose()
