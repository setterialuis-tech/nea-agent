"""Nombre con el que saluda el agente (app/nombre.py): solo si el del perfil suena a persona."""
from __future__ import annotations

import pytest

from app.nombre import nombre_para_saludar
from app.profile import BusinessProfile
from app.prompt import build_system_prompt
from app.state import Conversation
from tests.conftest import IDENTITY, crm_context


@pytest.mark.parametrize(
    "crudo,esperado",
    [
        ("Edwin Muñoz", "Edwin"),
        ("Francy Mesa", "Francy"),
        ("Magdalena Lopez", "Magdalena"),
        ("Marco", "Marco"),
        ("JUAN CARLOS", "Juan"),
        ("ana", "Ana"),
        ("Luis ✨", "Luis"),
        ("Marlene 💙", "Marlene"),
        ("Nata🥰🤩🫶🏻", "Nata"),
        ("María José Pérez", "María"),
        ("Kevin_Rivera", "Kevin"),
        ("Luz Marina", "Luz"),
    ],
)
def test_un_nombre_de_persona_pasa_con_solo_el_primer_nombre(crudo, esperado):
    assert nombre_para_saludar(crudo) == esperado


@pytest.mark.parametrize(
    "crudo",
    [
        "micro empresa de lavadora y agua señora luz",  # el caso de Roger del 30-oct
        "Señora Luz",
        "Lavadora Luz",
        "Clínica Corpas",
        "Dr. Roger",
        "edwinmp142",  # con números
        "😎",  # solo emojis
        "Mési Bondye Pou Gras Ou F",  # demasiadas palabras
        "José Luis de la Cruz",
        "D.V",  # iniciales
        "Ps",
        "Mamá",
        "",
        "   ",
        None,
    ],
)
def test_lo_que_no_suena_a_persona_no_se_da_como_nombre(crudo):
    assert nombre_para_saludar(crudo) is None


def _system(nombre: str | None) -> str:
    ctx = crm_context()
    ctx["contact"]["name"] = nombre
    return build_system_prompt(
        profile=BusinessProfile(agent_name="Angie", instructions="Saluda con [Nombre]."),
        context=ctx,
        conv=Conversation(id=1, wa_identity=IDENTITY),
    )


def test_el_modelo_recibe_solo_el_primer_nombre_y_se_le_avisa_que_puede_no_ser_real():
    s = _system("Edwin Muñoz")
    assert "Edwin" in s and "Muñoz" not in s
    assert "puede no ser el real" in s


def test_un_negocio_no_llega_al_modelo_y_se_le_dice_que_no_use_ese_nombre():
    s = _system("micro empresa de lavadora y agua señora luz")
    assert "micro empresa" not in s.lower() and "lavadora" not in s.lower()
    assert "NOMBRE DEL LEAD: no se sabe" in s
    assert "NO lo llames por ese nombre" in s


def test_sin_nombre_en_el_crm_no_se_dice_nada_del_nombre():
    s = _system(None)
    assert "NOMBRE DEL LEAD" not in s
    assert "Nombre del lead" not in s
