"""Google Vertex AI como proveedor del modelo.

Vertex habla el formato de OpenAI (`…/endpoints/openapi/chat/completions`), pero
NO acepta una API key: pide un token OAuth2 que se saca de la cuenta de
servicio (un JSON) y caduca a la hora. Aquí se guarda ese JSON, se cambia por
el token cuando hace falta y se entrega al cliente del SDK.

Mismo camino que el CRM (Ajustes → IA → Vertex): el dueño crea una cuenta de
servicio con el rol «Vertex AI User» y pega su JSON. En Nea va en la variable
`LLM_VERTEX_CREDENTIALS` (secreto: nunca en el chat ni en un commit).
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any

logger = logging.getLogger("nea.vertex")

SCOPE = "https://www.googleapis.com/auth/cloud-platform"
REGION_POR_DEFECTO = "us-central1"
# Se pide uno nuevo cuando faltan menos de estos segundos para que caduque.
MARGEN_SEGUNDOS = 300.0

_REGION = re.compile(r"^(?:global|[a-z]+-[a-z]+[0-9]+)$")
_PROYECTO = re.compile(r"^[a-z][a-z0-9-]{4,28}[a-z0-9]$")


class VertexError(Exception):
    """La cuenta de servicio no sirve o Google no dio token."""


def base_url(project: str, region: str) -> str:
    """Dirección OpenAI-compatible de Vertex para ese proyecto y región."""
    if not _PROYECTO.match(project or ""):
        raise VertexError("el id del proyecto de Vertex no es válido")
    region = (region or REGION_POR_DEFECTO).strip().lower()
    if not _REGION.match(region):
        raise VertexError("la región de Vertex no es válida")
    host = "aiplatform.googleapis.com" if region == "global" else f"{region}-aiplatform.googleapis.com"
    return f"https://{host}/v1/projects/{project}/locations/{region}/endpoints/openapi"


def leer_credenciales(crudo: str) -> dict[str, Any]:
    """El JSON de la cuenta de servicio, validado. Nunca se imprime."""
    try:
        info = json.loads(crudo)
    except (TypeError, ValueError) as exc:
        raise VertexError("LLM_VERTEX_CREDENTIALS no es un JSON válido") from exc
    if not isinstance(info, dict) or info.get("type") != "service_account":
        raise VertexError("LLM_VERTEX_CREDENTIALS no es una cuenta de servicio de Google")
    for campo in ("client_email", "private_key", "project_id"):
        if not info.get(campo):
            raise VertexError(f"a la cuenta de servicio le falta «{campo}»")
    return info


class VertexToken:
    """Token OAuth2 de la cuenta de servicio, renovado solo."""

    def __init__(self, credenciales: dict[str, Any]) -> None:
        # Se importa aquí: sin Vertex configurado, google-auth ni se carga.
        from google.oauth2 import service_account

        self._credenciales = service_account.Credentials.from_service_account_info(
            credenciales, scopes=[SCOPE]
        )
        self._lock = asyncio.Lock()
        self.project: str = str(credenciales["project_id"])

    def _vigente(self) -> bool:
        c = self._credenciales
        if not c.token or c.expiry is None:
            return False
        # `expiry` viene en UTC sin zona.
        import datetime as _dt

        restante = (c.expiry - _dt.datetime.now(_dt.UTC).replace(tzinfo=None)).total_seconds()
        return restante > MARGEN_SEGUNDOS

    def _renovar(self) -> None:
        from google.auth.transport.requests import Request

        self._credenciales.refresh(Request())

    async def token(self) -> str:
        if self._vigente():
            return str(self._credenciales.token)
        async with self._lock:
            if self._vigente():
                return str(self._credenciales.token)
            inicio = time.monotonic()
            try:
                # El refresh es síncrono (requests): fuera del loop.
                await asyncio.to_thread(self._renovar)
            except Exception as exc:
                # El mensaje de Google no lleva la llave, pero se corta igual.
                raise VertexError(f"Google no dio token: {str(exc)[:200]}") from exc
            logger.info("vertex: token renovado en %.1f s", time.monotonic() - inicio)
            return str(self._credenciales.token)
