"""IMDEA Energía: portal de empleo propio (`jobs.energy.imdea.org`).

Fundación de la Comunidad de Madrid. La portada en castellano (`/es`) lista en tarjetas
(`div.offer`) las vacantes abiertas y las que están en evaluación (17 el 2026-11-12, 2 abiertas):
título, referencia («26.77 AT7 TEC»), categoría (en inglés), resumen y «Fecha de publicación» y
«Fecha de fin» con el mes abreviado en inglés («17 Nov 2026», sin hora). Mandan las fechas: el botón
«Inscribirse» solo aparece en las abiertas, pero no se usa.

La ficha (`/es/offer/N`) tiene bloques con título fijo (Descripción, Requisitos, Criterios de
selección, Condiciones, Lugar de trabajo) y la lista de documentos que hay que adjuntar; el tipo de
contrato va en «Condiciones» («Tipo de contrato: Contrato según legislación vigente»). La inscripción
es un formulario propio (`/es/offer/N/apply`). Sondeo del 2026-11-12, a partir del informe de Codex
(encargo 8).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://jobs.energy.imdea.org"
PAGE = SITE + "/es"
DETAIL = re.compile(r"^/es/offer/(\d+)$")
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
DAY = re.compile(r"(\d{1,2}) (" + "|".join(MONTHS) + r") (\d{4})")
BLOCKS = ("Descripción", "Requisitos", "Criterios de selección", "Condiciones", "Lugar de trabajo")
CONTRACT = re.compile(r"^Tipo de contrato:\s*(.+)$")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").replace("​", "").split())


def _day(text: str, what: str) -> str:
    found = DAY.fullmatch(_clean(text))
    if found is None:
        raise SourceLayoutError(f"IMDEA Energía: {what} ilegible: {text!r}")
    return date(int(found.group(3)), MONTHS.index(found.group(2)) + 1, int(found.group(1))).isoformat()


def parse_list(html: str) -> list[dict]:
    cards = BeautifulSoup(html, "html.parser").select("div.offer")
    if not cards:
        raise SourceLayoutError("IMDEA Energía: no se encuentran las vacantes")
    found = []
    for card in cards:
        title, link = card.select_one(".offer-title"), card.find("a", href=DETAIL)
        dates = {_clean(label.get_text(" ")): label.find_next_sibling("div")
                 for label in card.select(".bg-grey div > div:first-child")}
        if title is None or link is None or not all(dates.get(k) for k in ("Fecha de publicación", "Fecha de fin")):
            raise SourceLayoutError("IMDEA Energía: vacante sin título, enlace o fechas")
        code = card.select_one("span.mr-2")
        found.append({
            "ref": DETAIL.match(link["href"]).group(1), "url": urljoin(SITE, link["href"]),
            "title": _clean(title.get_text(" ")), "code": (_clean(code.get_text(" ")) or None) if code else None,
            "published_on": _day(dates["Fecha de publicación"].get_text(" "), "fecha de publicación"),
            "deadline": _day(dates["Fecha de fin"].get_text(" "), "fecha de fin"),
        })
    return found


def parse_detail(html: str) -> OfferDetail:
    soup = BeautifulSoup(html, "html.parser")
    sections, contract = [], None
    for heading in soup.select("div.offer-title-front"):
        name = _clean(heading.get_text(" "))
        if name in BLOCKS:
            body = heading.find_next_sibling()
            if body is None or body.name != "span":
                raise SourceLayoutError(f"IMDEA Energía: «{name}» sin su texto detrás")
            if _clean(body.get_text(" ")):
                sections.append({"title": name, "level": 2, "html": sanitize(body.decode_contents())})
            for item in body.find_all("li") if body and name == "Condiciones" else []:
                found = CONTRACT.match(_clean(item.get_text(" ")))
                contract = found.group(1) if found else contract
        elif name == "Documentos":
            items = [_clean(li.get_text(" ")) for li in heading.find_next_sibling("ul").find_all("li")] \
                if heading.find_next_sibling("ul") else []
            if any(items):
                html = "".join(f"<li>{escape(item)}</li>" for item in items if item)
                sections.append({"title": "Documentos que hay que adjuntar", "level": 2, "html": sanitize(f"<ul>{html}</ul>")})
    titles = [section["title"] for section in sections]
    if titles[:2] != ["Descripción", "Requisitos"]:
        raise SourceLayoutError(f"IMDEA Energía: ficha sin «Descripción» y «Requisitos» ({titles})")
    return OfferDetail(sections=sections, contract=contract, location="Móstoles")


class ImdeaEnergiaSource(Source):
    id = "imdea-energia"
    name = "IMDEA Energía"
    homepage = PAGE
    scope = "Comunidad de Madrid"
    apply_label = "Ver la vacante y el formulario de inscripción"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(ref=row["ref"], title=row["title"], company=self.name, url=row["url"], apply_url=row["url"],
                        kind=None, code=row["code"], published_on=row["published_on"], deadline=row["deadline"])
            for row in parse_list(http.get(PAGE)) if not deadline_passed(row["deadline"], None, now)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return parse_detail(http.get(offer.url))
