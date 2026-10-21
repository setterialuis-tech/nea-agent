"""Partir la respuesta, formateador con modelo validado, guarda contra basura y Vertex."""
from __future__ import annotations

import asyncio
import json

import pytest

from app.config import Settings
from app.llm import LlmReply
from app.partes import dar_forma_con_modelo, partir, validar
from app.turn import _respuesta_invalida

LARGO = (
    "Excelente, Vianis. Con tus datos confirmamos que eres candidata para el Programa Integral. "
    "La valoración médica formal cuesta 150 mil pesos y es descontable del procedimiento. "
    "Incluye revisión de historial, definición de técnica y presupuesto exacto.\n\n"
    "Modalidades en Cartagena:\n- Presencial: Clínica Higea.\n- Virtual: videollamada con el Dr. Roger.\n\n"
    "Más información en https://cirugiadiabetesobesidad.com/programa-bariatrico y en el Instagram.\n\n"
    "¿Te gustaría agendar tu valoración?"
)


def test_texto_corto_no_se_parte():
    assert partir("Hola, ¿cómo estás?", 3) == ["Hola, ¿cómo estás?"]


def test_maximo_uno_deja_todo_junto():
    assert partir(LARGO, 1) == [LARGO.strip()]


def test_respeta_el_maximo_y_no_pierde_texto():
    for maximo in (2, 3, 4):
        partes = partir(LARGO, maximo)
        assert 1 < len(partes) <= maximo
        assert "".join(p.replace("\n", "").replace(" ", "") for p in partes) == LARGO.replace(
            "\n", ""
        ).replace(" ", "")


def test_no_parte_una_url_ni_una_pregunta():
    partes = partir(LARGO, 4)
    assert any("https://cirugiadiabetesobesidad.com/programa-bariatrico" in p for p in partes)
    assert partes[-1].rstrip().endswith("¿Te gustaría agendar tu valoración?")


def test_la_lista_se_queda_con_su_intro():
    partes = partir(LARGO, 4)
    i = next(i for i, p in enumerate(partes) if "Modalidades" in p)
    assert "Presencial" in partes[i]


def test_parrafo_unico_se_parte_por_frases():
    texto = (
        "Gracias por escribirnos. Somos el equipo del Dr. Roger Méndez, especialista en cirugía bariátrica. "
        "Tenemos cupos disponibles para el programa integral esta semana. "
        "Para orientarte mejor necesito unos datos. ¿Cuál es tu nombre completo?"
    )
    partes = partir(texto, 2)
    assert len(partes) == 2
    assert partes[-1].endswith("¿Cuál es tu nombre completo?")


class _Fake:
    def __init__(self, contenido):
        self.contenido = contenido

    async def complete(self, messages, tools=None):
        return LlmReply(content=self.contenido)


def test_formateador_valido_se_usa():
    partes = ["Excelente, Vianis. Con tus datos confirmamos que eres candidata.", LARGO.split("\n\n", 1)[1]]
    original = partes[0] + "\n\n" + partes[1]
    out = asyncio.run(dar_forma_con_modelo(_Fake(json.dumps({"partes": partes})), original, 3))
    assert out == partes


def test_formateador_que_pierde_un_enlace_se_descarta():
    out = asyncio.run(
        dar_forma_con_modelo(
            _Fake(json.dumps({"partes": ["Hola.", "Más info, ¿te gustaría? Visita nuestro sitio."]})),
            "Hola. " * 30 + "Más info en https://ejemplo.com/x ¿te gustaría?",
            3,
        )
    )
    assert out is None


def test_formateador_con_basura_se_descarta():
    assert asyncio.run(dar_forma_con_modelo(_Fake("no es json"), LARGO, 3)) is None
    assert asyncio.run(dar_forma_con_modelo(_Fake(json.dumps({"partes": []})), LARGO, 3)) is None


def test_validar_cuenta_preguntas():
    assert validar("¿Uno? ¿Dos?", ["¿Uno?"], 2) == "cambió el número de preguntas"


def test_validar_no_deja_quitar_viñetas():
    original = "Incluye:\n• Revisión\n• Técnica\n• Presupuesto"
    assert validar(original, ["Incluye:", "Revisión\nTécnica\nPresupuesto"], 3) == "quitó viñetas"
    assert validar(original, ["Incluye:", "• Revisión\n• Técnica\n• Presupuesto"], 3) is None


@pytest.mark.parametrize(
    "texto,motivo",
    [
        ("Non杉 узору就会出现问题了", "otro idioma"),
        ("Gracias.<｜tool▁sep｜>update_ficha", "marcas internas"),
        ("Listo.\n```json\n{\"function\": \"handoff\"}\n```", "herramienta"),
        ("(Accionando ahora la herramienta para notificar al equipo)", None),
        ("Ejecutaré en silencio la herramienta para que te contacten", "herramienta"),
    ],
)
def test_respuestas_basura_no_salen(texto, motivo):
    r = _respuesta_invalida(texto, [])
    assert r is not None
    if motivo:
        assert motivo in r


def test_respuesta_normal_pasa():
    assert _respuesta_invalida("¡Hola, José! 🩺 ¿Desde qué ciudad nos escribes?", []) is None


def test_settings_vertex_por_defecto():
    s = Settings(llm_provider="vertex", llm_model="google/gemini-2.5-flash")
    from app import roles

    assert roles.proveedor_de(s, "conversacion") == "vertex"
    assert roles.proveedor_de(s, "audio") == "vertex"
    # Con Vertex no hay whisper: el que conversa también oye.
    assert roles.modelo_de(s, "audio") == "google/gemini-2.5-flash"
    assert roles.modelo_de(s, "vision") == ""
    assert roles.construir(s, "vision") is None


def test_vertex_url():
    from app import vertex

    assert vertex.base_url("project-7b67dc57-9c8d", "us-central1") == (
        "https://us-central1-aiplatform.googleapis.com/v1/projects/project-7b67dc57-9c8d"
        "/locations/us-central1/endpoints/openapi"
    )
    assert vertex.base_url("project-7b67dc57-9c8d", "global").startswith(
        "https://aiplatform.googleapis.com/v1/projects/"
    )
    with pytest.raises(vertex.VertexError):
        vertex.base_url("x", "us-central1")
    with pytest.raises(vertex.VertexError):
        vertex.base_url("project-7b67dc57-9c8d", "../evil")
    with pytest.raises(vertex.VertexError):
        vertex.leer_credenciales("{}")


def test_enviar_partes_en_orden_y_se_detiene_si_el_crm_bloquea():
    from app.crm import CrmConflict
    from app.turn import _enviar_partes

    class Crm:
        def __init__(self, falla_en=None):
            self.enviados, self.falla_en = [], falla_en

        async def send_message(self, conv, texto):
            if self.falla_en == len(self.enviados):
                raise CrmConflict("ai_paused")
            self.enviados.append(texto)

    class Ctx:
        def __init__(self, crm):
            self.crm = crm

    crm = Crm()
    assert asyncio.run(_enviar_partes(Ctx(crm), 1, "c1", ["a", "b", "c"], 0)) is True
    assert crm.enviados == ["a", "b", "c"]
    crm = Crm(falla_en=1)
    assert asyncio.run(_enviar_partes(Ctx(crm), 1, "c1", ["a", "b", "c"], 0)) is True
    assert crm.enviados == ["a"]
    crm = Crm(falla_en=0)
    assert asyncio.run(_enviar_partes(Ctx(crm), 1, "c1", ["a", "b"], 0)) is False


def test_perfil_lee_messaging_del_crm():
    from app.profile import profile_from_payload

    p = profile_from_payload(
        {
            "profile": {"name": "Angie"},
            "messaging": {
                "coalesceSeconds": 7,
                "maxPartsAds": 4,
                "maxPartsOrganic": 1,
                "partsDelaySeconds": 0.8,
                "formatWithModel": False,
            },
        },
        "Nea",
    )
    assert (p.coalesce_seconds, p.max_parts_ads, p.max_parts_organic) == (7.0, 4, 1)
    assert p.parts_delay_seconds == 0.8 and p.format_with_model is False
    # Sin messaging (o con valores absurdos) manda el entorno: todo None.
    vacio = profile_from_payload({"profile": {}, "messaging": {"maxPartsAds": 99, "coalesceSeconds": -1}}, "Nea")
    assert vacio.max_parts_ads is None and vacio.coalesce_seconds is None
    assert profile_from_payload({"profile": {}}, "Nea").format_with_model is None


def test_coalescedor_usa_los_segundos_del_crm():
    from app.coalesce import Coalescer

    async def correr():
        salidas: list[list] = []

        async def volcar(identidad, items):
            salidas.append(items)

        c = Coalescer(5.0, volcar)  # el entorno dice 5 s; el CRM manda 0.05
        c.add("x", "uno", 0.05)
        c.add("x", "dos", 0.05)
        await asyncio.sleep(0.3)
        await c.aclose()
        return salidas

    assert asyncio.run(correr()) == [["uno", "dos"]]
