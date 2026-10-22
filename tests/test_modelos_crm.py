"""Un modelo por función, mandado por el CRM (Ajustes → IA).

El CRM puede dar proveedor + base + modelo + llave para conversar, dar forma,
oír y ver. Manda sobre el entorno de Nea; lo que no mande se queda como estaba,
y un ajuste mal puesto jamás tumba un turno.
"""
from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from app import roles
from app.llm import LlmReply
from app.profile import BusinessProfile, profile_from_payload
from tests.conftest import FakeLLM, make_ctx, make_settings

OPENROUTER = {
    "provider": "openrouter",
    "baseUrl": "https://openrouter.ai/api/v1",
    "model": "openai/gpt-4.1-mini",
    "apiKey": "sk-or-secreta-1234",
}


@pytest.fixture(autouse=True)
def _sin_cache():
    roles._desde_crm.clear()
    yield
    roles._desde_crm.clear()


def _perfil(**modelos: dict[str, str]) -> BusinessProfile:
    return BusinessProfile(modelos=dict(modelos))


# ── El perfil lee los modelos ───────────────────────────────────────────────


def test_el_perfil_lee_los_modelos_completos_y_conocidos():
    p = profile_from_payload(
        {
            "profile": {},
            "models": {
                "conversacion": OPENROUTER,
                "formato": {**OPENROUTER, "model": ""},  # sin modelo: no sirve
                "audio": {**OPENROUTER, "apiKey": ""},  # sin llave: no sirve
                "vision": {**OPENROUTER, "baseUrl": ""},  # sin base: no sirve
                "juzgar": OPENROUTER,  # función que no existe
            },
        },
        "Nea",
    )
    assert list(p.modelos) == ["conversacion"]
    assert p.modelos["conversacion"]["model"] == "openai/gpt-4.1-mini"


@pytest.mark.parametrize("crudo", [None, [], "x", {"conversacion": "no soy un dict"}])
def test_modelos_mal_formados_se_ignoran(crudo: Any):
    assert profile_from_payload({"profile": {}, "models": crudo}, "Nea").modelos == {}


def test_la_llave_no_sale_en_el_repr_del_perfil():
    p = profile_from_payload({"profile": {}, "models": {"conversacion": OPENROUTER}}, "Nea")
    assert "sk-or-secreta-1234" not in repr(p)


# ── Qué cliente se usa ──────────────────────────────────────────────────────


def test_sin_modelos_del_crm_se_usa_lo_del_entorno():
    ctx = make_ctx()
    ctx.format_llm = FakeLLM()
    assert roles.llm_de_perfil(ctx, BusinessProfile(), "conversacion") is ctx.llm
    assert roles.llm_de_perfil(ctx, BusinessProfile(), "formato") is ctx.format_llm
    # oír sin modelo propio lo hace el que conversa; ver sin modelo propio es None
    assert roles.llm_de_perfil(ctx, BusinessProfile(), "audio") is ctx.llm
    assert roles.llm_de_perfil(ctx, BusinessProfile(), "vision") is None


def test_el_modelo_del_crm_manda_sobre_el_entorno():
    ctx = make_ctx()
    llm = roles.llm_de_perfil(ctx, _perfil(conversacion=OPENROUTER), "conversacion")
    assert llm is not ctx.llm
    assert llm._model == "openai/gpt-4.1-mini"
    assert llm._transcribe_model == "openai/gpt-4.1-mini"


def test_cada_funcion_toma_el_suyo_y_las_demas_se_quedan_como_estaban():
    ctx = make_ctx()
    ctx.format_llm = FakeLLM()
    perfil = _perfil(vision={**OPENROUTER, "model": "google/gemini-2.5-flash"})
    assert roles.llm_de_perfil(ctx, perfil, "vision")._model == "google/gemini-2.5-flash"
    assert roles.llm_de_perfil(ctx, perfil, "conversacion") is ctx.llm
    assert roles.llm_de_perfil(ctx, perfil, "formato") is ctx.format_llm


def test_la_misma_configuracion_reusa_el_cliente_y_un_cambio_lo_renueva():
    ctx = make_ctx()
    a = roles.llm_de_perfil(ctx, _perfil(conversacion=OPENROUTER), "conversacion")
    b = roles.llm_de_perfil(ctx, _perfil(conversacion=dict(OPENROUTER)), "conversacion")
    assert a is b
    c = roles.llm_de_perfil(
        ctx, _perfil(conversacion={**OPENROUTER, "model": "openai/gpt-4.1"}), "conversacion"
    )
    assert c is not a
    assert c._model == "openai/gpt-4.1"
    # cambiar solo la llave también renueva el cliente
    d = roles.llm_de_perfil(
        ctx,
        _perfil(conversacion={**OPENROUTER, "model": "openai/gpt-4.1", "apiKey": "sk-or-otra-5678"}),
        "conversacion",
    )
    assert d is not c


def test_una_llave_de_vertex_rota_no_tumba_el_turno(caplog: pytest.LogCaptureFixture):
    ctx = make_ctx()
    perfil = _perfil(
        conversacion={
            "provider": "vertex",
            "baseUrl": "https://aiplatform.googleapis.com/v1/projects/mi-proyecto-123/locations/global/endpoints/openapi",
            "model": "google/gemini-2.5-flash",
            "apiKey": "esto no es un json",
        }
    )
    with caplog.at_level(logging.WARNING, logger="nea.roles"):
        assert roles.llm_de_perfil(ctx, perfil, "conversacion") is ctx.llm
    assert any("no sirve" in r.message for r in caplog.records)
    assert "esto no es un json" not in caplog.text


def test_multi_organizacion_no_usa_modelos_del_crm():
    settings = make_settings(vocero_mode="cloud", crm_organization="")
    assert settings.multi_org
    ctx = make_ctx(settings)
    assert roles.llm_de_perfil(ctx, _perfil(conversacion=OPENROUTER), "conversacion") is ctx.llm


@pytest.mark.parametrize(
    "base, esperada",
    [
        ("https://openrouter.ai/api", "https://openrouter.ai/api/v1"),
        ("https://openrouter.ai/api/v1/", "https://openrouter.ai/api/v1"),
        ("https://api.openai.com", "https://api.openai.com/v1"),
        ("https://api.groq.com/openai/v1", "https://api.groq.com/openai/v1"),
        (
            "https://generativelanguage.googleapis.com/v1beta/openai",
            "https://generativelanguage.googleapis.com/v1beta/openai",
        ),
    ],
)
def test_la_raiz_de_la_api_se_normaliza_como_en_el_crm(base: str, esperada: str):
    assert roles._raiz_openai(base) == esperada


def test_los_logs_no_llevan_la_llave(caplog: pytest.LogCaptureFixture):
    ctx = make_ctx()
    with caplog.at_level(logging.DEBUG, logger="nea.roles"):
        roles.llm_de_perfil(ctx, _perfil(conversacion=OPENROUTER), "conversacion")
    assert "tomado del CRM" in caplog.text
    assert "sk-or-secreta-1234" not in caplog.text


# ── El turno usa el modelo del CRM ──────────────────────────────────────────


class _Perfiles:
    """`ctx.profile` de mentira: sirve un perfil fijo."""

    def __init__(self, perfil: BusinessProfile) -> None:
        self._perfil = perfil

    async def get(self) -> BusinessProfile:
        return self._perfil


async def test_la_conversacion_usa_el_modelo_del_crm(monkeypatch: pytest.MonkeyPatch):
    from app import turn

    del_crm = FakeLLM([LlmReply(content="respondo con el modelo del CRM")])
    llamadas: list[tuple[str, str]] = []

    def construir(settings: Any, funcion: str, cfg: dict[str, str]) -> FakeLLM:
        llamadas.append((funcion, cfg["model"]))
        return del_crm

    monkeypatch.setattr(roles, "construir_desde_crm", construir)

    env = FakeLLM([LlmReply(content="respondo con el del entorno")])
    ctx = make_ctx(llm=env)
    ctx.profile = _Perfiles(_perfil(conversacion=OPENROUTER))

    texto = await turn._tool_loop(
        ctx, [{"role": "user", "content": "hola"}], SimpleNamespace()
    )

    assert texto == "respondo con el modelo del CRM"
    assert llamadas == [("conversacion", "openai/gpt-4.1-mini")]
    assert len(del_crm.calls) == 1
    assert env.calls == []


async def test_sin_modelo_del_crm_la_conversacion_sigue_con_el_entorno():
    from app import turn

    env = FakeLLM([LlmReply(content="entorno")])
    ctx = make_ctx(llm=env)
    ctx.profile = _Perfiles(BusinessProfile())
    assert await turn._tool_loop(ctx, [{"role": "user", "content": "hola"}], SimpleNamespace()) == "entorno"
    assert len(env.calls) == 1


async def test_el_formateador_usa_el_modelo_del_crm(monkeypatch: pytest.MonkeyPatch):
    from app import turn

    recibido: list[Any] = []
    prompts: list[str | None] = []

    async def dar_forma(llm: Any, texto: str, maximo: int, prompt: str | None = None) -> list[str]:
        recibido.append(llm)
        prompts.append(prompt)
        return ["uno", "dos"]

    del_crm = FakeLLM()
    monkeypatch.setattr(roles, "construir_desde_crm", lambda *a, **k: del_crm)
    monkeypatch.setattr(turn, "dar_forma_con_modelo", dar_forma)

    ctx = make_ctx()  # sin FORMAT_MODEL en el entorno
    perfil = BusinessProfile(modelos={"formato": OPENROUTER}, format_prompt="PROMPT DEL CRM")
    assert await turn._repartir(ctx, perfil, "texto largo " * 30, de_anuncio=True) == ["uno", "dos"]
    assert recibido == [del_crm]
    assert prompts == ["PROMPT DEL CRM"]  # el prompt que el dueño editó en el CRM llega al formateador


async def test_el_formateador_respeta_el_interruptor_del_crm(monkeypatch: pytest.MonkeyPatch):
    from app import turn

    async def dar_forma(*a: Any, **k: Any) -> list[str]:  # no debe llamarse
        raise AssertionError("el formateador está apagado en Agente → Mensajes")

    monkeypatch.setattr(roles, "construir_desde_crm", lambda *a, **k: FakeLLM())
    monkeypatch.setattr(turn, "dar_forma_con_modelo", dar_forma)

    ctx = make_ctx()
    perfil = BusinessProfile(modelos={"formato": OPENROUTER}, format_with_model=False)
    partes = await turn._repartir(ctx, perfil, "corto", de_anuncio=False)
    assert partes == ["corto"]
