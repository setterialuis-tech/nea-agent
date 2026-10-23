"""País de un teléfono de WhatsApp, por su prefijo.

El agente no veía el número de quien le escribe: en Roger (2026-10-22) dos pacientes de
República Dominicana (+1 809/829/849) fueron tratados como colombianos porque nada en el
contexto del modelo decía de dónde era el número. Aquí se calcula CON CÓDIGO (el modelo no
sabe de memoria que 829 es dominicano) y se le da como pista, no como dato seguro: la
persona puede vivir en otro país.
"""
from __future__ import annotations

import re

import phonenumbers
from phonenumbers import NumberParseException, geocoder

# libphonenumber reparte los móviles de +44 entre varias regiones (7911 sale como Guernsey).
_COMO_REINO_UNIDO = {"GG", "JE", "IM"}


def pais_del_numero(telefono: str | None) -> str | None:
    """Nombre en español del país del número («República Dominicana») o None si no se sabe.

    Acepta con o sin «+» y con separadores. Un número que no se puede ubicar (corto, sin
    prefijo conocido, identidad `bsuid:`/`ig:`) devuelve None: nunca se inventa un país.
    """
    digitos = re.sub(r"\D", "", telefono or "")
    if not 7 <= len(digitos) <= 15:
        return None
    try:
        numero = phonenumbers.parse("+" + digitos)
    except NumberParseException:
        return None
    region = phonenumbers.region_code_for_number(numero)
    if not region or region == "ZZ":
        return None
    if region in _COMO_REINO_UNIDO and digitos.startswith("44"):
        return "Reino Unido"
    return geocoder.country_name_for_number(numero, "es") or None
