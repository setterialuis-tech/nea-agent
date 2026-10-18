"""Un modelo por función: quién conversa, quién oye, quién ve y quién da forma.

Cada función del agente se construye aquí con su propio proveedor y modelo, a
partir de la configuración (ver `Settings`). Por defecto todas comparten el
proveedor que conversa; cada una puede irse por otro lado con su `*_PROVIDER`.

Un cliente por función, no uno por llamada: el cliente de Vertex guarda el
token y lo renueva solo.
"""
from __future__ import annotations

import logging
from typing import Any

from app.config import Settings
from app.llm import DEFAULT_TIMEOUT, OpenAiLlm
from app import vertex

logger = logging.getLogger("nea.roles")

OPENROUTER_URL = "https://openrouter.ai/api/v1"
FUNCIONES = ("conversacion", "audio", "vision", "formato")

# Un token por proceso: lo comparten todas las funciones que usen Vertex.
_token: dict[str, Any] = {}


def _vertex_token(settings: Settings) -> vertex.VertexToken:
    clave = settings.llm_vertex_credentials
    if clave not in _token:
        _token[clave] = vertex.VertexToken(vertex.leer_credenciales(clave))
    return _token[clave]


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
