"""Agente → Herramientas de Nea (CRM): recortar el chasis de lo que el negocio apagó.

Si el chasis siguiera nombrando una herramienta apagada, el modelo intentaría
usarla (o prometería lo que hace) aunque ya no exista. Sin nada apagado, el
texto sale idéntico: los CRM que no mandan la lista se comportan como siempre.
Solo se cambian frases exactas del chasis y del contexto; las instrucciones del
negocio no se tocan.
"""
from __future__ import annotations

import re

_HOSTILIDAD_SIN_HANDOFF = (
    "Hostilidad: una grosería suelta no te inmuta — aguantas vara con dignidad, sin engancharte ni "
    "sermonear. Al TERCER mensaje hostil seguido se acabó el guion: escribe una única línea digna de "
    "cierre (sin invitación, sin pitch, sin pregunta).\n"
)
_NUNCA_HOSTIL_SIN_HANDOFF = (
    "- Sigas vendiendo a quien te insulta. Al TERCER mensaje hostil seguido: una línea digna de "
    "cierre sin pitch NI pregunta.\n"
)


def recortar_herramientas(texto: str, off: frozenset[str]) -> str:
    """El system prompt sin las partes del chasis que hablan de herramientas apagadas."""
    if not off:
        return texto
    cambios: list[tuple[str, str]] = []
    if "update_ficha" in off:
        cambios.append(
            (" Guarda cada dato nuevo del lead con la herramienta update_ficha en cuanto lo sepas.", "")
        )
        texto = re.sub(r"^- update_ficha: .*\n", "", texto, flags=re.M)
    if "propose_slots" in off:
        texto = re.sub(r"AGENDAR:\n.*?\n\n(?=SI NO CALIFICA)", "", texto, count=1, flags=re.S)
        cambios += [
            (
                "y AGENDAR una cita con el equipo cuando corresponda",
                "y llevarla al siguiente paso que indiquen las instrucciones del negocio",
            ),
            (
                "si llega listo, califica ligero y ve directo a agendar",
                "si llega listo, califica ligero y avanza según las instrucciones del negocio",
            ),
        ]
    for nombre in ("propose_slots", "book_session", "reschedule_session"):
        if nombre in off:
            texto = re.sub(rf"^- {nombre}: .*\n", "", texto, flags=re.M)
    if "route_out" in off:
        texto = re.sub(
            r"SI NO CALIFICA \(según los criterios del negocio\):\n.*?\n\n", "", texto, count=1, flags=re.S
        )
        texto = re.sub(r"^- route_out: .*\n", "", texto, flags=re.M)
        cambios.append(("(compártelos al despedirlos con route_out)", "(compártelos al despedirlos)"))
    if "handoff" in off:
        texto = re.sub(r"^HANDOFF \(llama la herramienta handoff\).*\n", "", texto, flags=re.M)
        texto = re.sub(r"^Hostilidad: .*\n", _HOSTILIDAD_SIN_HANDOFF, texto, flags=re.M)
        texto = re.sub(r"^- Sigas vendiendo a quien te insulta\..*\n", _NUNCA_HOSTIL_SIN_HANDOFF, texto, flags=re.M)
        texto = re.sub(r"^- handoff: .*\n", "", texto, flags=re.M)
        cambios += [
            (' Si insisten una segunda vez, handoff con razón "modelo".', ""),
            ("dilo con honestidad o haz handoff.", "dilo con honestidad."),
            (" y ofrécele lo que sí (o handoff).", " y ofrécele lo que sí."),
            ("dilo con honestidad o haz handoff)", "dilo con honestidad)"),
            (
                "→ Si quiere CANCELAR: handoff — esa la decide el equipo.",
                "→ Si quiere CANCELAR: dile que lo gestiona el equipo y sigue las instrucciones del negocio.",
            ),
            (" Eso no es handoff.", ""),
            (
                "haz handoff para que lo coordine una persona.",
                "sigue las instrucciones del negocio para pasarlo con el equipo.",
            ),
            (
                "(aviso, transferencia o handoff por haber aceptado avanzar)",
                "(aviso o transferencia por haber aceptado avanzar)",
            ),
            (" (eso NO es handoff)", ""),
        ]
    for viejo, nuevo in cambios:
        texto = texto.replace(viejo, nuevo)
    return texto
