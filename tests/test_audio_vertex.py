import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.llm import OpenAiLlm, _formato_de_audio, _formato_vertex


class _Token:
    async def get(self):  # pragma: no cover - no se usa: _credencial se anula abajo
        return "t"


def _llm(token_source):
    llm = OpenAiLlm(api_key="x", model="google/gemini-2.5-flash", transcribe_model="google/gemini-2.5-flash",
                    base_url="https://ejemplo.test/v1", token_source=token_source)
    llm._credencial = AsyncMock()
    resp = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="hola"))])
    llm._client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock(return_value=resp))))
    return llm


def _formato_enviado(llm):
    msgs = llm._client.chat.completions.create.call_args.kwargs["messages"]
    parte = next(p for p in msgs[0]["content"] if p["type"] == "input_audio")
    return parte["input_audio"]["format"]


def test_formatos_vertex_son_mime_completo():
    assert _formato_vertex("audio/ogg; codecs=opus") == "audio/ogg"
    assert _formato_vertex("audio/mpeg") == "audio/mpeg"
    assert _formato_vertex("audio/mp4") == "audio/mp4"
    assert _formato_vertex("algo/raro") == "audio/ogg"


def test_otros_proveedores_siguen_con_formato_corto():
    assert _formato_de_audio("audio/ogg; codecs=opus") == "ogg"


def test_vertex_manda_audio_ogg_y_otros_proveedores_ogg():
    vertex = _llm(token_source=_Token())
    assert asyncio.run(vertex.transcribe(b"x", "audio/ogg; codecs=opus")) == "hola"
    assert _formato_enviado(vertex) == "audio/ogg"

    otro = _llm(token_source=None)
    assert asyncio.run(otro.transcribe(b"x", "audio/ogg; codecs=opus")) == "hola"
    assert _formato_enviado(otro) == "ogg"
