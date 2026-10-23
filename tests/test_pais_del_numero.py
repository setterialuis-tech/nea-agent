"""El agente sabe de qué país es el número de quien le escribe.

Caso real, Roger 2026-10-22: dos pacientes dominicanos (+1 809/829) fueron tratados como
colombianos porque el modelo no veía el número; uno dijo «La Vega» (ciudad dominicana) y
se le dio la valoración virtual para Colombia.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app.pais import pais_del_numero
from app.profile import BusinessProfile
from app.prompt import build_system_prompt
from app.state import Conversation

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
MARCA = "PAÍS DEL NÚMERO"


@pytest.mark.parametrize(
    "numero,pais",
    [
        ("573126893543", "Colombia"),
        ("+57 312 689 3543", "Colombia"),
        ("18095551234", "República Dominicana"),
        ("18295551234", "República Dominicana"),
        ("18495551234", "República Dominicana"),
        ("17875551234", "Puerto Rico"),
        ("14155552671", "Estados Unidos"),
        ("584121234567", "Venezuela"),
        ("34612345678", "España"),
        ("447911123456", "Reino Unido"),
    ],
)
def test_el_pais_sale_del_prefijo(numero, pais):
    assert pais_del_numero(numero) == pais


@pytest.mark.parametrize("numero", [None, "", "123", "bsuid:DO.123", "ig:178414", "no tengo", "9" * 16])
def test_sin_numero_utilizable_no_se_inventa_pais(numero):
    assert pais_del_numero(numero) is None


def _prompt(contact: dict | None, identidad: str = "18095551234") -> str:
    context = {"contact": contact} if contact is not None else None
    return build_system_prompt(
        profile=BusinessProfile(),
        context=context,
        conv=Conversation(id=1, wa_identity=identidad, greeted=True),
        now=NOW,
    )


def test_un_numero_dominicano_se_le_dice_al_modelo():
    p = _prompt({"name": "x", "channel": "whatsapp", "phone": "18095551234"})
    assert f"{MARCA}: su teléfono (+18095551234) es de República Dominicana" in p
    assert "pista" in p


def test_sin_contexto_del_crm_se_usa_la_identidad_de_la_conversacion():
    assert "es de Colombia" in _prompt(None, identidad="573126893543")


def test_contacto_sin_telefono_se_dice_desconocido_y_se_pide_preguntar():
    p = _prompt({"name": "maru", "channel": "whatsapp", "phone": None}, identidad="bsuid:DO.123")
    assert f"{MARCA}: desconocido" in p
    assert "pregúntaselo" in p


def test_crm_que_no_manda_el_dato_y_sin_numero_no_inventa_nada():
    assert MARCA not in _prompt({"name": "Gerardo"}, identidad="bsuid:DO.123")


def test_instagram_y_messenger_no_llevan_pais_de_numero():
    for canal in ("instagram", "messenger"):
        assert MARCA not in _prompt({"name": "x", "channel": canal, "phone": None}, identidad="ig:178414")
