"""Nombre con el que el agente saluda, sacado del nombre del perfil de WhatsApp.

El CRM guarda el nombre que cada persona se pone en WhatsApp, y ese nombre puede ser
cualquier cosa: un negocio («micro empresa de lavadora y agua señora luz»), un apodo, un
emoji, un usuario con números. El prompt de Roger dice «Claro, [Nombre], …» y el modelo
rellenaba el hueco con lo único que tenía: «Claro, Micro empresa de lavadora y agua señora
luz, es una decisión importante» (2026-10-30). Aquí se decide CON CÓDIGO si ese nombre suena
a una persona; si no, el modelo no recibe nombre y saluda sin él hasta que la persona diga
el suyo.
"""
from __future__ import annotations

import re
import unicodedata

# Palabras que delatan un negocio, un cargo o un parentesco, no un nombre de pila.
_NO_ES_PERSONA = {
    "empresa", "micro", "tienda", "negocio", "comercial", "comercializadora", "distribuidora",
    "restaurante", "cafeteria", "panaderia", "drogueria", "farmacia", "ferreteria", "papeleria",
    "lavadora", "lavanderia", "servicios", "servicio", "ventas", "oficina", "consultorio",
    "clinica", "hospital", "centro", "grupo", "fundacion", "corporacion", "sociedad", "compania",
    "agua", "pollo", "carniceria", "peluqueria", "salon", "taller", "almacen", "supermercado",
    "inversiones", "constructora", "ingenieria", "asesorias", "asesor", "soporte", "oficial",
    "official", "shop", "store", "ltda", "sas", "inc", "corp", "doctor", "dr", "dra", "doctora",
    "senor", "senora", "sra", "sr", "don", "dona", "mi", "mis", "tu", "tus", "el", "la", "los",
    "las", "un", "una", "y", "e", "de", "del", "en", "con", "para", "por", "sin",
    # Apelativos de cariño y parentescos: no son el nombre de la persona.
    "mama", "papa", "amor", "bebe", "jefe", "jefa", "hermano", "hermana", "tio", "tia",
}
# Un nombre largo de verdad son 2 o 3 palabras («Edwin Muñoz», «María José Pérez»).
_MAX_PALABRAS = 3
_MAX_LARGO = 40


def _sin_acentos(s: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", s) if unicodedata.category(c) != "Mn"
    ).lower()


def nombre_para_saludar(crudo: str | None) -> str | None:
    """El primer nombre si el del perfil suena a persona; None si no (se saluda sin nombre).

    Lo que no pasa: emojis y símbolos se descartan; con números, o con más de tres palabras, o
    con una palabra de negocio o de cargo (empresa, tienda, doctor, señora…), no es un nombre.
    «Edwin Muñoz» → «Edwin». El nombre de pila va con su acento y su mayúscula inicial.
    """
    if not crudo:
        return None
    # Solo letras, espacios, guion y apóstrofo: los emojis y símbolos no son parte del nombre,
    # y el punto y el guion bajo separan palabras («Kevin_Rivera», «D.V»).
    limpio = "".join(
        c if (c.isalpha() or c in " -'’") else (" " if (c.isspace() or c in "._") else "")
        for c in crudo
    )
    if any(c.isdigit() for c in crudo):
        return None
    palabras = limpio.split()
    if not palabras or len(palabras) > _MAX_PALABRAS or len(limpio) > _MAX_LARGO:
        return None
    if any(_sin_acentos(p.strip("-'’")) in _NO_ES_PERSONA for p in palabras):
        return None
    primero = palabras[0].strip("-'’")
    if len(primero) < 2 or not re.search(r"[aeiouáéíóúü]", primero.lower()):
        return None  # «Jr», «Ps», «Xx»: iniciales o apodos sin vocal
    # NOMBRE EN MAYÚSCULAS o en minúsculas → Capitalizado; «McDonald» se deja como viene.
    if primero.isupper() or primero.islower():
        primero = primero.capitalize()
    return primero
