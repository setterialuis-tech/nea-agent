"""El agente escribe UNA respuesta con las URL de sus archivos; Nea los saca con código,
reparte el texto y lo envía todo en el orden en que el agente lo escribió (como n8n)."""
from __future__ import annotations

import asyncio
import json

import httpx

from app.llm import LlmReply
from app.partes import dar_forma_con_modelo, prompt_de_sistema
from tests.conftest import mock_crm_basics, wa_body

IMG = "https://i.postimg.cc/0yCfSz4Z/pacientes-extrajeros-Web.jpg"
PAGINA = "https://www.cirugiadiabetesobesidad.com/internacional/"
RESPUESTA = (
    "Gracias, Rodrigo. Con lo que me cuentas, el Dr. Roger puede revisar tu caso. Como vives en República "
    "Dominicana, el primer paso es una TELECONSULTA por videollamada: revisa tu historia y tus estudios y te "
    "explica qué opciones podrían ser adecuadas para ti. Después recibes por escrito una propuesta "
    "personalizada en USD. Mira cómo se arma 👇\n"
    f"📸 {IMG}\n"
    f"Aquí puedes ver el proceso completo: {PAGINA} ¿Te gustaría avanzar con tu teleconsulta?"
)


def _cuerpos(routes):
    return [json.loads(c.request.content) for c in routes["messages"].calls]


async def test_la_imagen_sale_en_su_lugar_con_su_pie_y_el_enlace_queda_en_el_texto(ctx, client, respx_mock):
    ctx.settings.parts_delay_seconds = 0
    routes = mock_crm_basics(respx_mock)
    ctx.llm.replies = [LlmReply(content=RESPUESTA)]
    await client.post("/webhook", content=wa_body(text="quiero información"))
    await asyncio.sleep(0.4)

    cuerpos = _cuerpos(routes)
    tipos = ["media" if "media" in c else "text" for c in cuerpos]
    assert tipos.count("media") == 1
    i = tipos.index("media")
    assert i > 0 and i < len(cuerpos) - 1  # texto antes y texto después
    assert cuerpos[i]["media"] == {"url": IMG, "type": "image", "caption": "Mira cómo se arma 👇"}
    # La URL del archivo no se quedó en ningún texto; el enlace de la página sí.
    textos = [c["text"] for c in cuerpos if "text" in c]
    assert not any(IMG in t for t in textos)
    assert PAGINA in cuerpos[-1]["text"] and "¿Te gustaría avanzar con tu teleconsulta?" in cuerpos[-1]["text"]
    assert not any("Mira cómo se arma" in t for t in textos)


async def test_el_mismo_archivo_no_se_repite_en_la_conversacion(ctx, client, respx_mock):
    ctx.settings.parts_delay_seconds = 0
    routes = mock_crm_basics(respx_mock)
    ctx.llm.replies = [LlmReply(content=RESPUESTA), LlmReply(content=RESPUESTA)]
    await client.post("/webhook", content=wa_body(text="quiero información", wamid="wamid.001"))
    await asyncio.sleep(0.4)
    await client.post("/webhook", content=wa_body(text="¿y qué sigue?", wamid="wamid.002"))
    await asyncio.sleep(0.4)
    medias = [c for c in _cuerpos(routes) if "media" in c]
    assert len(medias) == 1
    conv = await ctx.store.get_or_create_conversation("573001112233")
    assert conv is not None


async def test_si_el_crm_rechaza_el_archivo_el_paciente_lo_recibe_como_enlace(ctx, client, respx_mock):
    ctx.settings.parts_delay_seconds = 0
    routes = mock_crm_basics(respx_mock)

    def responder(request):
        return httpx.Response(422 if "media" in json.loads(request.content) else 200, json={"messageId": "m"})

    routes["messages"].mock(side_effect=responder)
    ctx.llm.replies = [LlmReply(content=RESPUESTA)]
    await client.post("/webhook", content=wa_body(text="quiero información"))
    await asyncio.sleep(0.4)
    textos = [json.loads(c.request.content).get("text", "") for c in routes["messages"].calls]
    assert any(IMG in t for t in textos)  # nunca se pierde la URL


class _LlmFalso:
    def __init__(self, contenido: str):
        self.contenido = contenido
        self.mensajes: list[dict] = []

    async def complete(self, mensajes):
        self.mensajes = mensajes
        return LlmReply(content=self.contenido)


TEXTO_LARGO = (
    "Gracias, Rodrigo. Con lo que me cuentas, el Dr. Roger puede revisar tu caso. Como vives en República "
    "Dominicana, el primer paso es una TELECONSULTA por videollamada con él. Después recibes por escrito una "
    "propuesta personalizada en USD con lo que incluye tu paquete. ¿Te gustaría avanzar con tu teleconsulta?"
)


async def test_el_formateador_entiende_el_formato_de_n8n_y_usa_el_prompt_del_crm():
    n8n = {
        "response": {
            "part_1": "Gracias, Rodrigo. Con lo que me cuentas, el Dr. Roger puede revisar tu caso.",
            "part_2": "Como vives en República Dominicana, el primer paso es una TELECONSULTA por videollamada con él.",
            "part_3": "Después recibes por escrito una propuesta personalizada en USD con lo que incluye tu paquete.",
            "part_4": "¿Te gustaría avanzar con tu teleconsulta?",
            "image_urls": [],
            "video_url": "",
            "caption": "",
        }
    }
    llm = _LlmFalso(json.dumps(n8n))
    partes = await dar_forma_con_modelo(llm, TEXTO_LARGO, 3, "MI PROMPT DEL CRM")
    assert partes is None  # 4 partes > máximo 3 → se usan las reglas de código
    sistema = llm.mensajes[0]["content"]
    assert sistema.startswith("MI PROMPT DEL CRM")
    assert "máximo 3 parte(s) (part_1 a part_3)" in sistema
    # Al formateador solo le llega la respuesta del agente.
    assert [m["role"] for m in llm.mensajes] == ["system", "user"]
    assert llm.mensajes[1]["content"] == TEXTO_LARGO


async def test_el_formateador_acepta_cuatro_partes_si_el_maximo_lo_permite():
    n8n = {"response": {"part_1": "Gracias, Rodrigo. Con lo que me cuentas, el Dr. Roger puede revisar tu caso.",
                        "part_2": "Como vives en República Dominicana, el primer paso es una TELECONSULTA por videollamada con él.",
                        "part_3": "Después recibes por escrito una propuesta personalizada en USD con lo que incluye tu paquete.",
                        "part_4": "¿Te gustaría avanzar con tu teleconsulta?"}}
    llm = _LlmFalso(json.dumps(n8n))
    partes = await dar_forma_con_modelo(llm, TEXTO_LARGO, 6)
    assert partes is not None and len(partes) == 4
    # Sin prompt del CRM usa el de fábrica y topa a 4 partes.
    assert "máximo 4 parte(s)" in llm.mensajes[0]["content"]


def test_prompt_de_sistema_acota_el_maximo():
    assert "part_1 a part_2" in prompt_de_sistema("X", 2)
    assert "part_1 a part_4" in prompt_de_sistema("X", 9)
