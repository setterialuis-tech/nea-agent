"""Partir la respuesta en varios mensajes de WhatsApp.

Dos caminos, y el segundo es opcional:

1. `partir`: reglas de código, deterministas. Parte por párrafos y listas, nunca
   corta una frase, una pregunta ni una URL, y respeta el máximo de mensajes.
   Siempre corre.
2. `dar_forma_con_modelo`: un modelo propio (`FORMAT_MODEL`) reparte el texto
   como lo hacía el formateador de n8n. Su salida se VALIDA contra el original
   (enlaces, preguntas, largo); si algo no cuadra, se usa el camino 1. Un
   formateador que falla jamás pierde ni cambia lo que Nea quiso decir.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

logger = logging.getLogger("nea.partes")

# Un texto corto no se parte: tres burbujas de seis palabras cansan.
MINIMO_PARA_PARTIR = 200
# Una parte más corta que esto se pega a su vecina.
MINIMO_DE_PARTE = 60

_URL = re.compile(r"(?:https?://|www\.)\S+", re.I)
_FIN_DE_FRASE = re.compile(r"(?<=[.!?…])\s+(?=[¿¡A-ZÁÉÍÓÚÑ0-9\U0001F300-\U0001FAFF*_(\-•✅📍👉📌])")
_ITEM_DE_LISTA = re.compile(r"^\s*(?:[-•*✅📍👉📌✔️▪️]|\d+[.)])\s+")


def _bloques(texto: str) -> list[str]:
    """Párrafos separados por línea en blanco; una lista se queda con su intro."""
    crudos = [b.strip() for b in re.split(r"\n\s*\n", texto.strip()) if b.strip()]
    return crudos


def _frases(bloque: str) -> list[str]:
    """Frases de un bloque, sin partir las URL."""
    protegidas: list[str] = []

    def guardar(m: re.Match[str]) -> str:
        protegidas.append(m.group(0))
        return f"{len(protegidas) - 1}"

    sin_urls = _URL.sub(guardar, bloque)
    trozos = [t.strip() for t in _FIN_DE_FRASE.split(sin_urls) if t.strip()]
    return [
        re.sub("(\\d+)", lambda m: protegidas[int(m.group(1))], t) for t in trozos
    ]


def _fusionar(partes: list[str], maximo: int, separador: str) -> list[str]:
    """Pega las vecinas más cortas hasta quedar en `maximo` (y sin partes enanas)."""
    partes = list(partes)
    while len(partes) > 1 and (
        len(partes) > maximo or min(len(p) for p in partes) < MINIMO_DE_PARTE
    ):
        # La pareja de vecinas con menos texto junto.
        i = min(range(len(partes) - 1), key=lambda k: len(partes[k]) + len(partes[k + 1]))
        partes[i : i + 2] = [partes[i] + separador + partes[i + 1]]
    return partes


def partir(texto: str, maximo: int) -> list[str]:
    """El texto, repartido en hasta `maximo` mensajes (al menos uno)."""
    texto = (texto or "").strip()
    if not texto:
        return []
    if maximo <= 1 or len(texto) < MINIMO_PARA_PARTIR:
        return [texto]

    bloques = _bloques(texto)
    if len(bloques) == 1:
        # Sin párrafos: se parte por frases. Una lista sin intro no se rompe.
        lineas = [l for l in bloques[0].split("\n") if l.strip()]
        if len(lineas) > 1 and sum(1 for l in lineas if _ITEM_DE_LISTA.match(l)) >= 2:
            return [bloques[0]]
        frases = _frases(bloques[0])
        if len(frases) < 2:
            return [bloques[0]]
        return _fusionar(frases, maximo, " ")
    return _fusionar(bloques, maximo, "\n\n")


# ---------------------------------------------------------------------------
# Formateador con modelo (opcional)
# ---------------------------------------------------------------------------

PROMPT_FORMATO = """Eres un formateador de mensajes de WhatsApp. Recibes el texto que un agente quiere enviar y lo repartes en hasta {maximo} mensajes cortos. NO reescribes, NO resumes, NO agregas información y NO quitas ninguna pregunta.

REGLAS
- Devuelves SOLO un JSON: {{"partes": ["...", "..."]}}. Sin texto fuera del JSON.
- Máximo {maximo} partes y máximo 3 frases por parte. El contenido total debe estar completo en la suma de las partes.
- Una pregunta es una unidad: nunca la partas entre dos mensajes. La pregunta de cierre va al final de la última parte.
- Las URL van COMPLETAS y tal cual, dentro de la parte que las introduce. Nunca las cortes ni las quites.
- Una lista: el texto introductorio en una parte y los ítems después, con \\n antes de cada ítem. No pongas más de 3 ítems en una misma parte.
- Quita los asteriscos decorativos (*) y el signo ¡ de apertura. Mantén un asterisco a cada lado SOLO en la pregunta de cierre (*¿Te gustaría agendar?*).
- Conserva los emojis que ya trae el texto. Si una parte tiene más de 150 caracteres y ningún emoji, agrega uno de este banco: 🩺 💊 🏥 ⚕️ 📋 📌 ✅. Máximo 2 emojis nuevos por parte.
- Si el texto ya cabe bien en un solo mensaje, devuelve una sola parte."""


def _urls(texto: str) -> set[str]:
    return {u.rstrip(".,;:!?)»\"'*_") for u in _URL.findall(texto)}


def validar(original: str, partes: list[str], maximo: int) -> str | None:
    """Por qué las partes del modelo no sirven, o None si sirven."""
    if not partes or len(partes) > maximo:
        return "número de partes fuera de rango"
    if any(not isinstance(p, str) or not p.strip() for p in partes):
        return "hay partes vacías"
    unido = "\n".join(partes)
    faltan = [u for u in _urls(original) if u not in unido]
    if faltan:
        return "perdió un enlace"
    if unido.count("?") != original.count("?"):
        return "cambió el número de preguntas"
    largo, base = len(unido), max(len(original), 1)
    if not 0.7 <= largo / base <= 1.4:
        return "cambió demasiado el largo"
    return None


async def dar_forma_con_modelo(llm: Any, texto: str, maximo: int) -> list[str] | None:
    """Reparte el texto con el modelo formateador. None = usa `partir`."""
    if maximo <= 1 or len(texto) < MINIMO_PARA_PARTIR:
        return None
    try:
        reply = await llm.complete(
            [
                {"role": "system", "content": PROMPT_FORMATO.format(maximo=maximo)},
                {"role": "user", "content": texto},
            ]
        )
    except Exception as exc:  # el formateador no puede tumbar el turno
        logger.warning("formateador: falló (%s) — reglas de código", exc)
        return None
    crudo = (reply.content or "").strip()
    crudo = re.sub(r"^```(?:json)?\s*|\s*```$", "", crudo)
    try:
        partes = json.loads(crudo).get("partes")
    except (ValueError, AttributeError):
        logger.warning("formateador: respuesta que no es JSON — reglas de código")
        return None
    if not isinstance(partes, list):
        return None
    partes = [p.strip() if isinstance(p, str) else "" for p in partes]
    motivo = validar(texto, partes, maximo)
    if motivo:
        logger.warning("formateador: %s — reglas de código", motivo)
        return None
    return partes
