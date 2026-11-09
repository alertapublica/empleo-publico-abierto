"""Modelo común a todas las fuentes. Nada aquí sabe de Tragsa.

Cada fuente traduce su portal a dos cosas, según cómo publica el propio portal:

- `ListedOffer`: algo a lo que una persona de fuera puede presentarse ahora, con ficha y plazo
  (un puesto, una bolsa, unas prácticas, una beca). Va a la portada, «Ofertas».
- `Announcement`: un comunicado de un proceso que se publica por fases (bases, admitidos,
  exámenes, resoluciones). Va a «Procesos selectivos». Solo título, fecha y enlace.

Lo demás no se lee: ayudas a proyectos, resoluciones con nombres, exámenes, listas de personas
y plazas de promoción interna como oferta.

Se transforma lo mínimo. El contrato se guarda con el texto de la fuente (`contract`) y `kind`
solo se rellena si la fuente lo dice sin ambigüedad. Nada se deduce del título. Una oferta está
abierta según sus fechas, no según la etiqueta de la web, que a menudo está desfasada.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime
from zoneinfo import ZoneInfo

MADRID = ZoneInfo("Europe/Madrid")

# Catálogo de organismos: cada fuente pertenece a un grupo (lo asigna `sources/__init__.py`)
# y declara su ámbito: «Estatal» o su comunidad autónoma. El orden es el de la web.
GROUPS = {
    "sepi": "Grupo SEPI",
    "estatal": "Otras empresas del Estado",
    "autonomica": "Empresas públicas autonómicas",
    "investigacion": "Fundaciones y centros de investigación",
}
STATE_SCOPE = "Estatal"

KINDS = {
    "temporal": "Temporal",
    "indefinido": "Indefinido",
    "practicas": "Prácticas",
    "beca": "Beca",
    "bolsa": "Bolsa de empleo",
}


# Un proceso se describe con varios datos independientes: una tasa de reposición es además, por
# ejemplo, un concurso-oposición de acceso libre. Cada fuente los lee de lo que publica su empresa.
PROCESS_TYPES = {
    "tasa": "Tasa de reposición",
    "oep": "Oferta de empleo público",
    "bolsa": "Bolsa de empleo",
    "otro": "Proceso selectivo",
}
ACCESS = {"libre": "Acceso libre", "interna": "Promoción interna"}
SYSTEMS = {
    "concurso-oposicion": "Concurso-oposición",
    "oposicion": "Oposición",
    "concurso": "Concurso de méritos",
}
STATES = {
    "abierto": "Inscripción abierta",
    "curso": "En curso",
    "finalizado": "Finalizado",
    "retirado": "Sin novedades en la web oficial",
}
LIVE_STATES = ("abierto", "curso")


def process_type(name: str) -> str:
    """Tipo de proceso para los registros que aún no traen el dato de su fuente."""
    lowered = name.lower()
    if "tasa de reposici" in lowered:
        return "tasa"
    if "oferta de empleo p" in lowered:
        return "oep"
    if "bolsa" in lowered or "banco de datos" in lowered:
        return "bolsa"
    return "otro"


def selection_system(text: str) -> str | None:
    """Sistema de selección según el texto oficial; None si el texto no lo dice."""
    lowered = text.lower()
    if re.search(r"concurso[\s–-]*(?:y[\s–-]*)?oposici", lowered):
        return "concurso-oposicion"
    opposition = "oposici" in lowered
    merits = bool(re.search(r"\bconcurso\b|\bm[ée]ritos\b|\bvaloraciones\b", lowered))
    if opposition and merits:
        return "concurso-oposicion"
    if opposition:
        return "oposicion"
    return "concurso" if merits else None


class SourceLayoutError(RuntimeError):
    """La página oficial ya no tiene la forma esperada: no hay que tocar los datos."""


@dataclass
class ListedOffer:
    """Lo que trae el listado de una fuente."""

    ref: str  # identificador dentro de la fuente
    title: str
    company: str
    url: str  # ficha oficial
    apply_url: str  # inscripción oficial
    kind: str | None = "temporal"  # clave de KINDS; None si la fuente no lo dice claro
    positions: int | None = None
    category: str | None = None
    deadline: str | None = None  # AAAA-MM-DD, último día del plazo
    published_on: str | None = None  # AAAA-MM-DD, si el listado ya la trae
    contract: str | None = None  # texto literal del contrato en la fuente
    opens_on: str | None = None  # AAAA-MM-DD, primer día del plazo, si la fuente lo da
    deadline_time: str | None = None  # HH:MM, si el plazo acaba a una hora concreta
    code: str | None = None  # código que el portal publica con la oferta (Source.labels)
    source_title: str | None = None  # título literal, si se le ha quitado el código


@dataclass
class OfferDetail:
    """Lo que trae la ficha de una oferta. Lo que es None no sustituye lo del listado."""

    sections: list[dict] = field(default_factory=list)  # {title, level, html}
    location: str | None = None
    parent_ref: str | None = None  # oferta anterior, si es una republicación
    deadline: str | None = None  # AAAA-MM-DD, si el listado no la trae
    kind: str | None = None  # clave de KINDS, si solo la ficha lo dice
    contract: str | None = None
    opens_on: str | None = None
    deadline_time: str | None = None
    positions: int | None = None


# Datos de la oferta que pueden venir del listado o de la ficha.
LISTING_OR_DETAIL = ("kind", "contract", "opens_on", "deadline_time", "positions")


@dataclass
class Announcement:
    """Comunicado de un proceso. Solo título, fecha y enlace, nunca listas de personas."""

    date: str  # AAAA-MM-DD, o vacía si la fuente no publica ninguna
    process: str
    title: str
    url: str
    # Datos del proceso, no del comunicado: se actualizan en cada lectura.
    via: str = "otro"  # clave de PROCESS_TYPES
    access: str | None = None  # clave de ACCESS, si la fuente lo indica
    contract: str | None = None  # clave de KINDS, si la fuente lo indica
    system: str | None = None  # clave de SYSTEMS, si la fuente lo indica
    state: str = "curso"  # clave de STATES
    process_url: str | None = None  # página oficial del proceso
    deadline: str | None = None  # fin de la inscripción, si está abierta
    apply_url: str | None = None  # dónde inscribirse, si está abierta
    deadline_time: str | None = None  # HH:MM, si la inscripción acaba a una hora concreta

    @property
    def key(self) -> str:
        digest = hashlib.sha1(f"{self.process}|{self.date}|{self.title}".encode())
        return digest.hexdigest()[:12]


PROCESS_FIELDS = ("via", "access", "contract", "system", "state", "process_url", "deadline", "apply_url",
                  "deadline_time")


def today_madrid(now: datetime) -> str:
    return now.astimezone(MADRID).date().isoformat()


def deadline_passed(deadline: str | None, deadline_time: str | None, now: datetime) -> bool:
    """Si el plazo ya ha acabado en Madrid. Sin hora, el último día cuenta entero."""
    if not deadline:
        return False
    local = now.astimezone(MADRID)
    today = local.date().isoformat()
    if deadline != today:
        return deadline < today
    return bool(deadline_time) and local.strftime("%H:%M") >= deadline_time
