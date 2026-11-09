"""FGC (Ferrocarrils de la Generalitat de Catalunya), en SAP SuccessFactors.

A diferencia de Correos y Navantia, el listado (`/go/CONVOCATORIES/814602/`) usa tarjetas y no
una tabla. Cada tarjeta trae «Termini presentació» (último día, DD/MM/AAAA) y «Tipus de
Contracte», que es el mismo en todas («Durada determinada / Indefinit») y se guarda literal.

El plazo es el de la tarjeta, que coincide con el «Termini de presentació» de las bases. El
`validThrough` de la ficha no sirve: es cuándo se retira el anuncio y puede ser posterior (una
convocatoria con plazo hasta el 6 de noviembre seguía publicada con `validThrough` del día 10).
Algunas convocatorias son cursos de formación para acceder a puestos: se ofrecen tal cual.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from .base import Source
from .successfactors import parse_detail

HOST = "https://treballar.fgc.cat"
PAGE = f"{HOST}/go/CONVOCATORIES/814602/"
COMPANY = "Ferrocarrils de la Generalitat de Catalunya"
MAX_PAGES = 10
EMPTY_TEXT = "no hi ha posicions obertes"
SHOWING = re.compile(r"mostrant\s+(\d+)\s+a\s+(\d+)\s+de\s+(\d+)", re.I)
JOB_ID = re.compile(r"/(\d+)/?$")
DATE = re.compile(r"\d\d/\d\d/\d{4}")
DEADLINE_LABEL = "Termini presentació"
CONTRACT_LABEL = "Tipus de Contracte"


def _text(node) -> str:
    return re.sub(r"[\s\xa0]+", " ", node.get_text(" ")).strip()


def parse_tiles(html: str) -> tuple[list[dict], int]:
    """Tarjetas de una página y total declarado."""
    soup = BeautifulSoup(html, "html.parser")
    text = _text(soup)
    tiles = soup.select("li.job-tile")
    if not tiles:
        if EMPTY_TEXT in text.lower():
            return [], 0
        raise SourceLayoutError("FGC: no se encuentran las convocatorias")
    total = SHOWING.search(text)
    if not total:
        raise SourceLayoutError("FGC: no se encuentra el total de convocatorias")
    entries = []
    for tile in tiles:
        link = tile.select_one("a.jobTitle-link[href]")
        section = tile.select_one(".sub-section-desktop")
        job = JOB_ID.search(link["href"]) if link else None
        if not (job and section):
            raise SourceLayoutError("FGC: tarjeta sin enlace o sin datos")
        fields = {}
        for field in section.select(".section-field"):
            label, value = field.select_one(".section-label"), field.select_one("div[id$='-value']")
            if label and value:
                fields[_text(label)] = _text(value)
        deadline = fields.get(DEADLINE_LABEL, "")
        if not DATE.fullmatch(deadline):
            raise SourceLayoutError(f"FGC: la convocatoria {job.group(1)} no trae «{DEADLINE_LABEL}»")
        entries.append({
            "ref": job.group(1),
            "title": _text(link),
            "url": urljoin(HOST, link["href"]),
            "deadline": numeric_date(deadline),
            "contract": fields.get(CONTRACT_LABEL) or None,
        })
    return entries, int(total.group(3))


def parse_job(html: str) -> OfferDetail | None:
    """Texto de la convocatoria y lugar; el plazo es el del listado."""
    detail = parse_detail(html)
    if detail is None:
        return None
    place = BeautifulSoup(html, "html.parser").find(attrs={"itemprop": "streetAddress"})
    location = re.sub(r"\s*,\s*ES$", "", (place.get("content") or _text(place)).strip()) if place else None
    return OfferDetail(sections=detail.sections, location=location or None)


class FgcSource(Source):
    id = "fgc"
    name = "FGC"
    homepage = PAGE
    scope = "Cataluña"

    def list_offers(self, http: Client) -> list[ListedOffer]:
        found: dict[str, dict] = {}
        total = 0
        for _ in range(MAX_PAGES):
            entries, total = parse_tiles(http.get(PAGE if not found else f"{PAGE}{len(found)}/"))
            new = [entry for entry in entries if entry["ref"] not in found]
            found.update({entry["ref"]: entry for entry in new})
            if not new or len(found) >= total:
                break
        if len(found) < total:
            raise SourceLayoutError(f"FGC: se declaran {total} convocatorias y se leen {len(found)}")
        today = today_madrid(datetime.now(timezone.utc))
        return [
            ListedOffer(
                ref=entry["ref"], title=entry["title"], company=COMPANY, url=entry["url"],
                apply_url=f"{HOST}/talentcommunity/apply/{entry['ref']}/?locale=ca_ES",
                kind=None, deadline=entry["deadline"], contract=entry["contract"],
            )
            for entry in found.values() if entry["deadline"] >= today
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return parse_job(http.get(offer.url))
