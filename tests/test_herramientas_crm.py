"""Agente → Herramientas de Nea (CRM): el negocio apaga herramientas y fija el historial.

Caso real, Roger 2026-10-28: el prompt prohíbe asignar horas, pero la agenda del CRM
estaba encendida y el chasis le daba a Nea `propose_slots`; ofreció «hoy 13:00» a una
paciente. Ahora lo que el CRM manda en `false` no existe para el modelo: ni en la lista
de herramientas, ni en el chasis, ni al ejecutarse.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.herramientas import recortar_herramientas
from app.profile import HERRAMIENTAS_CONFIGURABLES, BusinessProfile, profile_from_payload
from app.prompt import build_system_prompt
from app.state import Conversation
from app.tools import ToolRuntime, tool_schemas
from tests.conftest import CRM_CONV_ID, IDENTITY, make_ctx

NOW = datetime(2026, 10, 28, 19, 0, tzinfo=timezone.utc)
# Lo que Roger deja encendido: solo Transmitir_aviso, como en su n8n.
SOLO_AVISO = frozenset(n for n in HERRAMIENTAS_CONFIGURABLES if n != "Transmitir_aviso")
APAGADAS = ("update_ficha", "propose_slots", "book_session", "reschedule_session", "route_out", "handoff")


def _nombres(schemas):
    return {s["function"]["name"] for s in schemas}


def _prompt(off: frozenset[str], agenda: bool = True, resources=None) -> str:
    return build_system_prompt(
        profile=BusinessProfile(
            instructions="Usa Transmitir_aviso para pasar al paciente con coordinación.",
            tools_off=off,
            resources=resources or [],
        ),
        context={"contact": {"name": "Ana", "channel": "whatsapp", "phone": None}},
        conv=Conversation(id=1, wa_identity=IDENTITY, greeted=True),
        agenda=agenda,
        now=NOW,
    )


def test_el_crm_manda_apagadas_e_historial():
    p = profile_from_payload(
        {"tools": {"handoff": False, "send_media": False, "Transmitir_aviso": True, "inventada": False},
         "historyWindow": 15},
        "Nea",
    )
    assert p.tools_off == frozenset({"handoff", "send_media"})
    assert p.history_window == 15


def test_crm_viejo_sin_lista_todo_como_siempre():
    p = profile_from_payload({}, "Nea")
    assert p.tools_off == frozenset()
    assert p.history_window is None
    # Fuera de rango = se ignora (manda el entorno).
    assert profile_from_payload({"historyWindow": 500}, "Nea").history_window is None


def test_las_apagadas_no_se_ofrecen_al_modelo():
    todas = _nombres(tool_schemas(agenda_enabled=True, media=True, transmitir_aviso=True))
    assert {"propose_slots", "handoff", "update_ficha", "send_media", "Transmitir_aviso"} <= todas
    quedan = _nombres(tool_schemas(agenda_enabled=True, media=True, transmitir_aviso=True, off=SOLO_AVISO))
    assert quedan == {"Transmitir_aviso"}


def test_sin_nada_apagado_el_prompt_no_cambia():
    texto = _prompt(frozenset())
    assert recortar_herramientas(texto, frozenset()) == texto
    for nombre in APAGADAS:
        assert nombre in texto


def test_el_chasis_no_nombra_las_apagadas():
    texto = _prompt(SOLO_AVISO, agenda=False, resources=[{"label": "Guía", "url": "https://x.com"}])
    for nombre in APAGADAS:
        assert nombre not in texto, nombre
    assert "AGENDAR:" not in texto
    assert "SI NO CALIFICA" not in texto
    # Lo del negocio queda intacto, y las reglas de seguridad también.
    assert "Usa Transmitir_aviso para pasar al paciente con coordinación." in texto
    assert "BLINDAJE" in texto
    assert "Al TERCER mensaje hostil seguido" in texto
    assert "(compártelos al despedirlos)" in texto


def test_solo_agenda_apagada_conserva_lo_demas():
    texto = _prompt(frozenset({"propose_slots", "book_session", "reschedule_session"}))
    assert "propose_slots" not in texto and "book_session" not in texto
    assert "AGENDAR:" not in texto
    assert "- handoff:" in texto and "update_ficha" in texto


@pytest.mark.asyncio
async def test_una_apagada_no_se_ejecuta_aunque_el_modelo_la_invente():
    ctx = make_ctx()
    conv = await ctx.store.get_or_create_conversation(IDENTITY)
    rt = ToolRuntime(ctx, conv, CRM_CONV_ID, profile=BusinessProfile(tools_off=frozenset({"handoff"})))
    r = await rt.execute("handoff", {"reason": "pidió humano"})
    assert r["ok"] is False and r["error"] == "herramienta_desactivada"
    assert rt.handoff_reason is None
