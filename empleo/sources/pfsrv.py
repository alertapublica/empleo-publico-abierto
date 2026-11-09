"""ENAIRE y Aena: el mismo SAP antiguo (`PFSrv`) con dos plantillas distintas.

El listado es HTML de servidor en Latin-1 y da título y fechas de inscripción, nada más. Una
convocatoria se considera abierta si hoy cae dentro de esas fechas: la web no indica el contrato,
las plazas (salvo en el título) ni la ubicación, que están en las bases. Se enlaza siempre al
listado oficial porque las páginas de avisos y de solicitud dependen de la sesión.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from ..text import humane_caps
from .base import Source

CODE = re.compile(r"codigo=(\d+)")
SEATS = re.compile(r"^(\d+)\s+PLAZAS?\b", re.I)
LEVELS = re.compile(r"\b(niveles?) ([a-z])(?: y ([a-z]))?\b")
ENAIRE_TERM = re.compile(
    r"Plazo de inscripción:\s*Desde el (\d\d/\d\d/\d{4})[\s\d:]*hasta el (\d\d/\d\d/\d{4})\s*(\d\d:\d\d)?")
ENAIRE_PUBLISHED = re.compile(r"Fecha Inicio de Publicación:\s*(\d\d/\d\d/\d{4})")
AENA_TERM = re.compile(
    r"Fecha inicio inscripción:\s*(\d\d/\d\d/\d{4})\s*Fecha fin inscripción:\s*(\d\d/\d\d/\d{4})")


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _title(raw: str) -> str:
    """Título sin mayúsculas sostenidas, conservando los niveles: «niveles A y B»."""
    return LEVELS.sub(lambda m: m.group(0)[:len(m.group(1))] + m.group(0)[len(m.group(1)):].upper().replace(" Y ", " y "),
                      humane_caps(raw))


def _code(node) -> str:
    link = node.find("a", href=CODE)
    if link is None:
        raise SourceLayoutError("PFSrv: convocatoria sin código")
    return CODE.search(link["href"]).group(1)


def parse_enaire(html: str) -> list[dict]:
    rows = BeautifulSoup(html, "html.parser").select("table.empleo__tabla-convocatorias tbody tr")
    if not rows:
        raise SourceLayoutError("ENAIRE: no se encuentra la tabla de convocatorias")
    found = []
    for row in rows:
        cell = row.find("td")
        text = _text(cell)
        term, published = ENAIRE_TERM.search(text), ENAIRE_PUBLISHED.search(text)
        if not (term and published):
            raise SourceLayoutError(f"ENAIRE: fila sin fechas: {text[:80]}")
        found.append({
            "code": _code(row), "title": next(cell.stripped_strings),
            "start": numeric_date(term.group(1)), "end": numeric_date(term.group(2)),
            "published": numeric_date(published.group(1)), "end_time": term.group(3),
        })
    return found


def parse_aena(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = [block for block in soup.select("div.th") if block.find("h3")]
    if not blocks:
        raise SourceLayoutError("Aena: no se encuentran las convocatorias")
    found = []
    for block in blocks:
        term = AENA_TERM.search(_text(block))
        if not term:
            raise SourceLayoutError(f"Aena: bloque sin fechas: {_text(block)[:80]}")
        found.append({
            "code": _code(block.find_next_sibling("div", class_="td3")),
            "title": _text(block.find("h3")),
            "start": numeric_date(term.group(1)), "end": numeric_date(term.group(2)),
            "published": None,
        })
    return found


class PfsrvSource(Source):
    apply_label = "Ir a las convocatorias oficiales"

    def __init__(self, id: str, name: str, host: str, parser) -> None:
        self.id = id
        self.name = name
        self.homepage = f"{host}/empleo/"
        self.page = f"{host}/empleo/PFSrv?accion=inicio&SEDE=0"
        self.parser = parser

    def offers_on(self, html: str, today: str) -> list[ListedOffer]:
        return [
            ListedOffer(
                ref=row["code"], title=_title(row["title"]), company=self.name,
                url=self.page, apply_url=self.page, opens_on=row["start"], deadline=row["end"],
                published_on=row["published"],
                deadline_time=row.get("end_time"),
                kind="bolsa" if "BOLSA" in row["title"].upper() else None,
                positions=int(seats.group(1)) if (seats := SEATS.match(row["title"])) else None,
            )
            for row in self.parser(html) if row["start"] <= today <= row["end"]
        ]

    def list_offers(self, http: Client) -> list[ListedOffer]:
        html = http.get_bytes(self.page).decode("latin-1")
        return self.offers_on(html, today_madrid(datetime.now(timezone.utc)))

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(sections=[{
            "title": "Bases e inscripción", "level": 2,
            "html": f"<p>Las bases, las plazas y las condiciones están en la web oficial de {self.name}, "
                    "junto a esta convocatoria en el listado.</p>",
        }])


ENAIRE = PfsrvSource("enaire", "ENAIRE", "https://empleo.enaire.es", parse_enaire)
AENA = PfsrvSource("aena", "Aena", "https://empleo.aena.es", parse_aena)
