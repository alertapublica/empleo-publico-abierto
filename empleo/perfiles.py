"""Perfil de cada oferta de investigación: clasificación orientativa nuestra, solo para filtrar.

En los centros de investigación casi todo es «Investigación y laboratorio», así que el área no
distingue. El perfil dice quién busca el puesto: predoctoral, investigador/a, técnico/a de
laboratorio o apoyo, ensayos clínicos, datos y bioinformática, sanitario, gestión. Se deduce del
título con reglas deterministas (sin servicios externos): gana la primera regla de PERFILES que
case, así que el orden importa. Sin regla, la oferta queda sin perfil.
Los casos revisados están en perfiles_referencia.csv (fuente, título, perfil): los tests exigen que
sigan saliendo igual; añadir allí una oferta es darla por revisada.
"""
from __future__ import annotations

import csv
import re
import unicodedata
from pathlib import Path

PERFILES = (
    ("predoctoral", "Predoctoral y en formación", r"predoc|pre-doc|\br1\b|phd (call|student|position)|en practicas|en formacion|doctoral student"),
    ("investigador", "Investigador/a (postdoctoral y sénior)",
     r"postdoc|posdoc|\br[234]a?\b|investigador|researcher|research fellow|\bdoctor\b|doctoral degree"),
    ("ensayos", "Ensayos clínicos",
     r"ensayo|assaig|clinical trial|study (coordinator|nurse)|\bcra\b|\bcta\b|monitor|clinical research assistant"),
    ("sanitario", "Enfermería y sanitario",
     r"enfermer|infermer|nurse|auxiliar (clinic|sanitari)|farmaceutic|facultativ"),
    ("datos", "Datos y bioinformática",
     r"bioinformatic|bioestadist|biostatistic|data (manager|entry|scientist|analyst)|gestor(a)? de datos|software|platform engineer"),
    ("gestion", "Gestión y administración",
     r"gestion|gestor|manager|administrativ|administratiu|administrative|director|head of|recursos humanos|rrhh|financ|ethics|fundraising"
     r"|health and safety|tecnico de proyecto"),
    ("tecnico", "Técnico/a de laboratorio y apoyo",
     r"tecnic|technician|laborator|suport recerca|apoyo a la investigacion|research (assistant|support)|auxiliary|titulad[oa]"),
)
NAMES = {key: name for key, name, _ in PERFILES}
RULES = [(key, re.compile(rx)) for key, _, rx in PERFILES]
BY_NAME = sorted(NAMES.items(), key=lambda kv: kv[1])
NONE = "sin-perfil"
REFERENCE = Path(__file__).with_name("perfiles_referencia.csv")


GENDER = re.compile(r"(?<=\w)\s?/\s?(?:a|as|o|os|ora|ra|na)\b")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y sin «/a»; conserva las cifras (R1, R2A), que aquí son perfil."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return GENDER.sub("", text)


def classify(title: str) -> str:
    """Clave del perfil, o «» si el título no lo dice."""
    text = normalize(title)
    for key, rule in RULES:
        if rule.search(text):
            return key
    return ""


def reference(path: Path = REFERENCE) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))
