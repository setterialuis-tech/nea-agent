"""Modo ahorro: a quien no tiene ventana gratis se le manda lo mínimo de mensajes, y el
formateador recibe el aviso. Apagado, nada cambia."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from app.llm import LlmReply
from app.partes import CONTEXTO_SIN_VENTANA, dar_forma_con_modelo, prompt_de_sistema
from app.profile import BusinessProfile, profile_from_payload
from app.turn import _maximo_de_mensajes, _tipo_de_lead
from tests.conftest import mock_crm_basics, wa_body

IMG = "https://i.postimg.cc/0yCfSz4Z/pacientes-extrajeros-Web.jpg"
PAGINA = "https://www.cirugiadiabetesobesidad.com/internacional/"
RESPUESTA = (
    "Gracias, Rodrigo. Con lo que me cuentas, el Dr. Roger puede revisar tu caso. Como vives en República "
    "Dominicana, el primer paso es una TELECONSULTA por videollamada: revisa tu historia y tus estudios. "
    "Después recibes por escrito una propuesta personalizada en USD. Mira cómo se arma 👇\n"
    f"📸 {IMG}\n"
    f"Aquí puedes ver el proceso completo: {PAGINA} ¿Te gustaría avanzar con tu teleconsulta?"
)
SOLO_TEXTO = (
    "Gracias, Rodrigo. Con lo que me cuentas, el Dr. Roger puede revisar tu caso. Como vives en República "
    "Dominicana, el primer paso es una TELECONSULTA por videollamada. Después recibes por escrito una "
    "propuesta personalizada en USD con lo que incluye tu paquete. ¿Te gustaría avanzar con tu teleconsulta?"
)


def _perfil(**kw):
    return BusinessProfile(**kw)


# --- ¿anuncio? ¿sin ventana gratis? ------------------------------------------------
def test_el_origen_del_crm_vale_en_todos_los_turnos():
    # Segundo turno de un lead de anuncio: ya no viene el referral, pero el CRM sabe su origen.
    de_anuncio, sin = _tipo_de_lead(_perfil(), {"origin": "anuncio", "freeWindow": True}, None)
    assert de_anuncio is True and sin is False


def test_un_crm_anterior_usa_el_referral_del_primer_mensaje():
    assert _tipo_de_lead(_perfil(), {}, "Cirugía") == (True, False)
    assert _tipo_de_lead(_perfil(), {}, None) == (False, False)


def test_sin_modo_ahorro_nadie_es_sin_ventana():
    assert _tipo_de_lead(_perfil(), {"origin": None, "freeWindow": False}, None) == (False, False)


def test_con_modo_ahorro_organico_y_anuncio_pasado_no_tienen_ventana_gratis():
    p = _perfil(saver_mode=True)
    assert _tipo_de_lead(p, {"origin": None, "freeWindow": False}, None) == (False, True)
    assert _tipo_de_lead(p, {"origin": "anuncio", "freeWindow": False}, None) == (True, True)
    assert _tipo_de_lead(p, {"origin": "anuncio", "freeWindow": True}, None) == (True, False)


# --- tope ---------------------------------------------------------------------------
def test_el_tope_sin_ventana_usa_el_del_modo_ahorro_y_por_defecto_1():
    ctx = SimpleNamespace(settings=SimpleNamespace(max_parts_ads=3, max_parts_organic=2))
    assert _maximo_de_mensajes(ctx, _perfil(saver_mode=True), False, True) == 1
    assert _maximo_de_mensajes(ctx, _perfil(saver_mode=True, saver_max_parts=2), False, True) == 2
    assert _maximo_de_mensajes(ctx, _perfil(), True, False) == 3
    assert _maximo_de_mensajes(ctx, _perfil(), False, False) == 2


def test_el_perfil_lee_el_modo_ahorro_del_crm():
    p = profile_from_payload({"profile": {}, "messaging": {"saverMode": True, "saverMaxParts": 2}}, "Nea")
    assert p.saver_mode is True and p.saver_max_parts == 2
    sin = profile_from_payload({"profile": {}}, "Nea")
    assert sin.saver_mode is None and sin.saver_max_parts is None


# --- el formateador recibe el aviso ---------------------------------------------------
class _LlmFalso:
    def __init__(self, contenido: str):
        self.contenido = contenido
        self.mensajes: list[dict] = []

    async def complete(self, mensajes):
        self.mensajes = mensajes
        return LlmReply(content=self.contenido)


def test_el_aviso_va_al_final_del_prompt_solo_cuando_hay_contexto():
    assert "CONTEXTO DE ESTA RESPUESTA" not in prompt_de_sistema("X", 1)
    p = prompt_de_sistema("X", 1, CONTEXTO_SIN_VENTANA)
    assert p.endswith("# CONTEXTO DE ESTA RESPUESTA\n" + CONTEXTO_SIN_VENTANA)
    assert "máximo 1 parte(s)" in p


async def test_dar_forma_pasa_el_contexto_al_modelo():
    llm = _LlmFalso(json.dumps({"response": {"part_1": SOLO_TEXTO}}))
    partes = await dar_forma_con_modelo(llm, SOLO_TEXTO, 1, None, CONTEXTO_SIN_VENTANA)
    assert partes == [SOLO_TEXTO]
    assert CONTEXTO_SIN_VENTANA in llm.mensajes[0]["content"]
    llm2 = _LlmFalso(json.dumps({"response": {"part_1": SOLO_TEXTO}}))
    await dar_forma_con_modelo(llm2, SOLO_TEXTO, 1)
    assert CONTEXTO_SIN_VENTANA not in llm2.mensajes[0]["content"]  # el prompt de fábrica solo EXPLICA el contexto


# --- de punta a punta -----------------------------------------------------------------
def _cuerpos(routes):
    return [json.loads(c.request.content) for c in routes["messages"].calls]


async def test_modo_ahorro_organico_solo_texto_un_mensaje(ctx, client, respx_mock, monkeypatch):
    ctx.settings.parts_delay_seconds = 0
    from app import profile as perfil_mod

    original = perfil_mod.resolve_profile

    async def con_ahorro(c):
        p = await original(c)
        return BusinessProfile(**{**p.__dict__, "saver_mode": True, "saver_max_parts": 1})

    monkeypatch.setattr("app.turn.resolve_profile", con_ahorro)
    routes = mock_crm_basics(respx_mock)
    ctx.llm.replies = [LlmReply(content=SOLO_TEXTO)]
    await client.post("/webhook", content=wa_body(text="quiero información"))
    await asyncio.sleep(0.4)
    cuerpos = _cuerpos(routes)
    assert len(cuerpos) == 1 and "text" in cuerpos[0]
    assert "¿Te gustaría avanzar con tu teleconsulta?" in cuerpos[0]["text"]


async def test_modo_ahorro_organico_con_imagen_dos_mensajes(ctx, client, respx_mock, monkeypatch):
    ctx.settings.parts_delay_seconds = 0
    from app import profile as perfil_mod

    original = perfil_mod.resolve_profile

    async def con_ahorro(c):
        p = await original(c)
        return BusinessProfile(**{**p.__dict__, "saver_mode": True, "saver_max_parts": 1})

    monkeypatch.setattr("app.turn.resolve_profile", con_ahorro)
    routes = mock_crm_basics(respx_mock)
    ctx.llm.replies = [LlmReply(content=RESPUESTA)]
    await client.post("/webhook", content=wa_body(text="quiero información"))
    await asyncio.sleep(0.4)
    cuerpos = _cuerpos(routes)
    assert [("media" if "media" in c else "text") for c in cuerpos] == ["text", "media"]
    assert PAGINA in cuerpos[1]["media"]["caption"]


async def test_apagado_el_modo_ahorro_un_organico_sigue_con_su_tope(ctx, client, respx_mock):
    ctx.settings.parts_delay_seconds = 0
    routes = mock_crm_basics(respx_mock)  # sin modo ahorro: organico = 2 en total
    ctx.llm.replies = [LlmReply(content=RESPUESTA)]
    await client.post("/webhook", content=wa_body(text="quiero información"))
    await asyncio.sleep(0.4)
    assert len(_cuerpos(routes)) == 2
