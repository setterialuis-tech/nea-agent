"""Un modelo por función: quién conversa, quién oye, quién ve y quién da forma.

Cada función del agente se construye aquí con su propio proveedor y modelo, a
partir de la configuración (ver `Settings`). Por defecto todas comparten el
proveedor que conversa; cada una puede irse por otro lado con su `*_PROVIDER`.

Un cliente por función, no uno por llamada: el cliente de Vertex guarda el
token y lo renueva solo.
"""
from __future__ import annotations

import hashlib
import logging
import re
from urllib.parse import urlparse
from typing import Any

from app.config import Settings
from app.llm import DEFAULT_TIMEOUT, OpenAiLlm
from app import vertex

logger = logging.getLogger("nea.roles")

OPENROUTER_URL = "https://openrouter.ai/api/v1"
FUNCIONES = ("conversacion", "audio", "vision", "formato")

# Un token por proceso: lo comparten todas las funciones que usen Vertex.
_token: dict[str, Any] = {}


def _vertex_token_de(clave: str) -> vertex.VertexToken:
    if clave not in _token:
        _token[clave] = vertex.VertexToken(vertex.leer_credenciales(clave))
    return _token[clave]


def _vertex_token(settings: Settings) -> vertex.VertexToken:
    return _vertex_token_de(settings.llm_vertex_credentials)


def _vertex_url(settings: Settings, token: vertex.VertexToken) -> str:
    proyecto = settings.llm_vertex_project.strip() or token.project
    return vertex.base_url(proyecto, settings.llm_vertex_region)


def proveedor_de(settings: Settings, funcion: str) -> str:
    """Proveedor efectivo de una función ("" = OpenAI directo)."""
    base = settings.llm_provider.strip().lower()
    propio = {
        "conversacion": "",
        "audio": settings.audio_provider,
        "vision": settings.vision_provider,
        "formato": settings.format_provider,
    }[funcion].strip().lower()
    return propio or base


def modelo_de(settings: Settings, funcion: str) -> str:
    """Modelo de la función; vacío = esa función no tiene modelo propio."""
    if funcion == "conversacion":
        return settings.llm_model
    if funcion == "vision":
        return settings.vision_model.strip()
    if funcion == "formato":
        return settings.format_model.strip()
    # audio: con Vertex no hay whisper; el modelo que conversa (Gemini) también oye.
    modelo = settings.llm_transcribe_model.strip()
    if proveedor_de(settings, "audio") == "vertex" and modelo in ("", "whisper-1"):
        return settings.llm_model
    return modelo


def construir(settings: Settings, funcion: str) -> OpenAiLlm | None:
    """El cliente de la función, o None si esa función no tiene modelo."""
    modelo = modelo_de(settings, funcion)
    if funcion != "conversacion" and funcion != "audio" and not modelo:
        return None
    prov = proveedor_de(settings, funcion)
    propio = {
        "conversacion": ("", ""),
        "audio": (settings.audio_api_key, settings.audio_base_url),
        "vision": (settings.vision_api_key, settings.vision_base_url),
        "formato": (settings.format_api_key, settings.format_base_url),
    }[funcion]
    api_key = propio[0] or settings.llm_api_key
    base_url = propio[1] or settings.llm_base_url or None
    token = None
    reasoning = settings.llm_reasoning_effort
    sort = settings.llm_provider_sort

    if prov == "vertex":
        if not settings.llm_vertex_credentials.strip():
            raise vertex.VertexError("LLM_PROVIDER=vertex pide LLM_VERTEX_CREDENTIALS")
        token = _vertex_token(settings)
        base_url = _vertex_url(settings, token)
        api_key = "vertex"  # se cambia por el token antes de cada llamada
        sort = ""
    elif prov == "openrouter":
        base_url = propio[1] or OPENROUTER_URL
    elif prov == "openai":
        base_url = propio[1] or None
        sort = ""

    # El formateador no razona: es una tarea mecánica y cada segundo se ve.
    if funcion == "formato":
        reasoning = "minimal"

    return OpenAiLlm(
        api_key,
        modelo,
        transcribe_model=modelo if funcion == "audio" else settings.llm_transcribe_model,
        base_url=base_url,
        reasoning_effort=reasoning,
        provider_sort=sort,
        timeout=settings.llm_timeout_seconds or DEFAULT_TIMEOUT,
        token_source=token,
    )


# ── Modelos que manda el CRM (Ajustes → IA, un modelo por función) ──────────
#
# El CRM puede dar, por función, proveedor + base + modelo + llave
# (`BusinessProfile.modelos`). Mandan sobre el entorno de Nea; lo que el CRM no
# mande se queda como estaba. Un cliente por configuración distinta: cambiar el
# modelo en el CRM crea uno nuevo en el turno siguiente (el perfil se relee cada
# pocos minutos) y el anterior se descarta con el siguiente cambio.

_desde_crm: dict[str, tuple[str, OpenAiLlm]] = {}


def _huella(cfg: dict[str, str]) -> str:
    """Identifica una configuración sin guardar la llave en claro como clave."""
    datos = "\x00".join(cfg.get(k, "") for k in ("provider", "baseUrl", "model", "apiKey"))
    return hashlib.sha256(datos.encode()).hexdigest()


def _raiz_openai(base_url: str) -> str:
    """La raíz de una API compatible con OpenAI (la misma regla que el CRM)."""
    sin_barra = base_url.strip().rstrip("/")
    host = (urlparse(sin_barra).hostname or "").lower()
    if host.endswith("googleapis.com") or re.search(r"/v1$", sin_barra, re.I):
        return sin_barra
    return f"{sin_barra}/v1"


def construir_desde_crm(settings: Settings, funcion: str, cfg: dict[str, str]) -> OpenAiLlm:
    """El cliente de una función según lo que mandó el CRM."""
    prov = cfg.get("provider", "").strip().lower()
    modelo = cfg["model"]
    token = None
    api_key = cfg["apiKey"]
    base_url = _raiz_openai(cfg["baseUrl"])
    sort = settings.llm_provider_sort if prov == "openrouter" else ""
    if prov == "vertex":
        token = _vertex_token_de(api_key)
        base_url = cfg["baseUrl"].strip().rstrip("/")
        api_key = "vertex"  # se cambia por el token antes de cada llamada
    reasoning = "minimal" if funcion == "formato" else settings.llm_reasoning_effort
    return OpenAiLlm(
        api_key,
        modelo,
        transcribe_model=modelo,
        base_url=base_url,
        reasoning_effort=reasoning,
        provider_sort=sort,
        timeout=settings.llm_timeout_seconds or DEFAULT_TIMEOUT,
        token_source=token,
    )


def llm_de_perfil(ctx: Any, profile: Any, funcion: str) -> Any | None:
    """El cliente de la función: el del CRM si lo mandó, si no el del entorno.

    Sin modelo propio devuelve lo de siempre: `ctx.llm` para conversar y oír,
    `ctx.vision_llm` / `ctx.format_llm` (que pueden ser None = esa función no
    tiene modelo y se resuelve como antes). Un modelo del CRM que no se pueda
    construir (JSON de Vertex roto…) se registra y se cae al entorno: un ajuste
    mal puesto no tumba el turno.
    """
    base = {
        "conversacion": ctx.llm,
        "audio": ctx.audio_llm or ctx.llm,
        "vision": ctx.vision_llm,
        "formato": ctx.format_llm,
    }[funcion]
    if getattr(ctx.settings, "multi_org", False):
        return base
    cfg = (getattr(profile, "modelos", None) or {}).get(funcion)
    if not cfg:
        return base
    huella = _huella(cfg)
    hecho = _desde_crm.get(funcion)
    if hecho and hecho[0] == huella:
        return hecho[1]
    try:
        cliente = construir_desde_crm(ctx.settings, funcion, cfg)
    except Exception as exc:  # llave o JSON inválidos: se sigue con el entorno
        logger.warning("modelo del CRM para «%s» no sirve (%s) — uso el del entorno", funcion, type(exc).__name__)
        return base
    _desde_crm[funcion] = (huella, cliente)
    logger.info("modelo de «%s» tomado del CRM: %s (%s)", funcion, cfg["model"], cfg.get("provider", ""))
    return cliente


async def llm_de(ctx: Any, funcion: str) -> Any | None:
    """Como `llm_de_perfil`, resolviendo el perfil vigente del contexto."""
    from app.profile import resolve_profile

    return llm_de_perfil(ctx, await resolve_profile(ctx), funcion)
