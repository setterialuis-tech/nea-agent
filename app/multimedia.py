"""Imágenes, videos y PDF dentro de la respuesta del agente.

El agente conversacional escribe UNA respuesta completa, con la URL de cada
archivo en su texto (📸 imagen / 🎥 video), como en n8n. Aquí, con código (no
con el modelo), la respuesta se parte en el orden en que le llega al paciente:
bloques de texto y archivos.

- Una URL de imagen/video/PDF sale del texto (con su 📸/🎥 delante).
- «Caption: …» en la línea siguiente es su pie de foto.
- Sin «Caption:», la frase que lo presenta (termina en «:» o «👇») pasa a ser su
  pie: así no queda un «Mira cómo se arma 👇» suelto.
- Páginas web, formularios, mapas y WhatsApp NO se tocan.

Espejo de `src/lib/formatear.ts` del CRM (la pantalla «Probar» usa esa versión):
los dos lados comparten los casos de prueba. Si cambias una regla, cámbiala allá.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Literal

TipoArchivo = Literal["image", "video", "document"]

_EXT_IMAGEN = {"jpg", "jpeg", "png", "webp"}
_EXT_VIDEO = {"mp4", "mov", "3gp"}
_EXT_DOC = {"pdf"}
_URL = re.compile(r"https?://[^\s<>\"]+", re.I)
_COLA_URL = re.compile(r"[.,;:!?)»\"'*_]+$")
_MARCA_ANTES = re.compile("(?:📸|🎥|🖼️?|📹|📎|📄)\\s*$")
_CAPTION_LINEA = re.compile(r"^\s*Caption:\s*(.+?)\s*$", re.I)
_PRESENTA = re.compile(r"(:|👇\S*)$")
_FIN_FRASE = re.compile(r"(?<=[.!?…])\s+")
CAPTION_MAX = 1024
_INTRO_MAX = 200


@dataclass(frozen=True)
class Texto:
    texto: str


@dataclass(frozen=True)
class Archivo:
    url: str
    tipo: TipoArchivo
    caption: str | None = None


Item = Texto | Archivo


def tipo_de_archivo(url: str) -> TipoArchivo | None:
    """Tipo de archivo de una URL por su extensión, o None si es una página (se queda como texto)."""
    ruta = re.split(r"[?#]", re.sub(r"^https?://[^/]*", "", url, flags=re.I), maxsplit=1)[0]
    m = re.search(r"\.([A-Za-z0-9]{2,4})$", ruta)
    if not m:
        return None
    ext = m.group(1).lower()
    if ext in _EXT_IMAGEN:
        return "image"
    if ext in _EXT_VIDEO:
        return "video"
    if ext in _EXT_DOC:
        return "document"
    return None


def _limpiar(t: str) -> str:
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def _ultima_frase(texto: str) -> tuple[str, str]:
    """(lo que queda, la última frase) de un texto."""
    lineas = texto.rstrip().split("\n")
    ultima = lineas[-1]
    frases = _FIN_FRASE.split(ultima)
    cruda = frases[-1]
    antes_en_linea = ultima[: len(ultima) - len(cruda)]
    resto = "\n".join([*lineas[:-1], antes_en_linea]).rstrip()
    return resto, cruda.strip()


def extraer_secuencia(texto: str) -> list[Item]:
    """La respuesta del agente en orden: bloques de texto y archivos."""
    items: list[Item] = []
    cursor = 0
    pendiente = ""

    def volcar() -> None:
        nonlocal pendiente
        limpio = _limpiar(pendiente)
        if limpio:
            items.append(Texto(limpio))
        pendiente = ""

    for m in _URL.finditer(texto):
        url = _COLA_URL.sub("", m.group(0))
        tipo = tipo_de_archivo(url)
        if tipo is None:
            continue
        inicio = m.start()
        antes = _MARCA_ANTES.sub("", texto[cursor:inicio])
        fin = inicio + len(url)
        caption: str | None = None
        linea = re.match(r"^[ \t]*\r?\n([^\n]*)", texto[fin:])
        if linea:
            c = _CAPTION_LINEA.match(linea.group(1))
            if c:
                caption = c.group(1)
                fin += len(linea.group(0))
        pendiente += antes
        if caption is None:
            sin_frase, frase = _ultima_frase(_limpiar(pendiente))
            if frase and len(frase) <= _INTRO_MAX and _PRESENTA.search(frase):
                caption = frase
                pendiente = sin_frase
        volcar()
        items.append(Archivo(url, tipo, caption[:CAPTION_MAX] if caption else None))
        cursor = fin
    pendiente += texto[cursor:]
    volcar()
    return items


# ---------------------------------------------------------------------------
# Salida del modelo formateador
# ---------------------------------------------------------------------------

def _txt(v: Any) -> str:
    return v.strip() if isinstance(v, str) else ""


def leer_salida_formato(data: Any) -> list[str] | None:
    """Las partes que devolvió el modelo, o None si no se entiende.

    Acepta el formato de n8n ({"response": {"part_1"…}}) y el simple
    ({"partes": [...]}). Los archivos que el modelo diga haber sacado se ignoran:
    los archivos los saca `extraer_secuencia`, y una URL de archivo que el modelo
    se llevó del texto la detecta el validador como enlace perdido.
    """
    if not isinstance(data, dict):
        return None
    if isinstance(data.get("partes"), list):
        partes = [p for p in (_txt(x) for x in data["partes"]) if p]
        return partes or None
    r = data.get("response") if isinstance(data.get("response"), dict) else data
    partes = [p for p in (_txt(r.get(f"part_{i}")) for i in range(1, 7)) if p]
    return partes or None


# ---------------------------------------------------------------------------
# Tope de mensajes por respuesta
# ---------------------------------------------------------------------------

def ajustar_a_tope(items: list[Item], maximo: int) -> tuple[list[Item], list[int]]:
    """Que la respuesta COMPLETA no pase de `maximo` mensajes, contando cada archivo como uno.

    Devuelve los items (a veces con texto plegado al pie de un archivo) y, por cada
    item, cuántas partes puede ocupar: 0 para un archivo, 1 o más para un bloque de texto.

    1. Si no alcanza para un mensaje por bloque de texto, el texto que sigue a un
       archivo pasa a su pie de foto (los enlaces funcionan igual en un pie), del último
       al primero, mientras el pie quepa en 1024 caracteres.
    2. Lo que sobra del presupuesto se reparte entre los bloques, más a los más largos.
    3. Si aun así no cabe (más archivos que el tope), cada bloque conserva un mensaje.

    Espejo de `ajustarATope` en `src/lib/formatear.ts` del CRM.
    """
    items = list(items)
    maximo = max(1, int(maximo))
    archivos = sum(1 for i in items if isinstance(i, Archivo))

    def bloques() -> list[int]:
        return [k for k, i in enumerate(items) if isinstance(i, Texto)]

    while maximo - archivos < len(bloques()):
        plegado = False
        for k in reversed(bloques()):
            previo = items[k - 1] if k > 0 else None
            if not isinstance(previo, Archivo):
                continue
            pie = (previo.caption + "\n\n" if previo.caption else "") + items[k].texto  # type: ignore[union-attr]
            if len(pie) > CAPTION_MAX:
                continue
            items[k - 1] = Archivo(previo.url, previo.tipo, pie)
            del items[k]
            plegado = True
            break
        if not plegado:
            break

    idx = bloques()
    presupuesto = max(len(idx), maximo - archivos)
    cuotas = {k: 1 for k in idx}
    for _ in range(presupuesto - len(idx)):
        # El siguiente mensaje va al bloque que quedaría con partes más largas.
        k = max(idx, key=lambda j: len(items[j].texto) / cuotas[j])  # type: ignore[union-attr]
        cuotas[k] += 1
    return items, [cuotas.get(k, 0) for k in range(len(items))]
