"""GESPLAN (Gestión y Planeamiento Territorial y Medioambiental, Canarias).

`/trabaja-en-gesplan/` tiene dos bloques, «Ofertas disponibles» y «Ofertas finalizadas», con
tarjetas iguales: título (con las siglas de las islas delante, «GC TF …»), «Publicada»,
«Plazo de inscripción» (último día), jornada, islas y enlace a la ficha. La ficha tiene apartados
con encabezado («Descripción:», «Requisitos:», «Tipo de contrato:»…) y repite las fechas.

Se leen las tarjetas de los dos bloques y se ofrecen las de plazo no vencido. El plazo no trae
hora: el último día cuenta entero.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from ..sanitize import sanitize
from .base import Source

PAGE = "https://www.gesplan.es/trabaja-en-gesplan/"
COMPANY = "GESPLAN"
DATE = re.compile(r"\d\d/\d\d/\d{4}")
EMPTY_TEXT = "No hay ofertas disponibles"
KIND = {"indefinido": "indefinido", "temporal": "temporal"}


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _date(card, css: str) -> str | None:
    node = card.select_one(css)
    found = DATE.search(_text(node)) if node else None
    return numeric_date(found.group(0)) if found else None


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    lists = soup.select(".ofertas-empleo-lista")
    if not lists and EMPTY_TEXT not in _text(soup):
        raise SourceLayoutError("GESPLAN: no se encuentran las ofertas")
    entries = []
    for card in soup.select(".ofertas-empleo-lista .oferta-empleo-item"):
        title, link = card.select_one(".oferta-empleo-item-titulo"), card.select_one("a.oferta-empleo-item-link[href]")
        deadline = _date(card, ".oferta-empleo-fecha-fin")
        if not (title and link and deadline):
            raise SourceLayoutError("GESPLAN: oferta sin título, enlace o plazo")
        place = card.select_one(".oferta-empleo-item-datos .fa-location-dot")
        entries.append({
            "ref": link["href"].rstrip("/").rsplit("/", 1)[-1],
            "title": _text(title),
            "url": link["href"],
            "published_on": _date(card, ".oferta-empleo-fecha-inicio"),
            "deadline": deadline,
            "place": _text(place.parent) if place else None,
        })
    if not entries and EMPTY_TEXT not in _text(soup):
        raise SourceLayoutError("GESPLAN: no se encuentran las ofertas")
    return entries


def parse_detail(html: str) -> OfferDetail | None:
    """Apartados de la ficha; «Tipo de contrato» también como texto literal."""
    soup = BeautifulSoup(html, "html.parser")
    sections, contract = [], None
    for heading in soup.select("article .vc_custom_heading_wrap h3"):
        block = heading.find_parent(class_="uncont")
        body = block.select_one(".uncode_text_column") if block else None
        if body is None:
            continue
        title = _text(heading).rstrip(":").strip()
        if title.lower() == "tipo de contrato":
            contract = _text(body).rstrip(".").strip() or None
        sections.append({"title": title, "level": 2, "html": sanitize(body.decode_contents())})
    if not sections:
        return None
    first = (contract or "").split()[0].lower() if contract else ""
    return OfferDetail(sections=sections, contract=contract, kind=KIND.get(first))


class GesplanSource(Source):
    id = "gesplan"
    name = COMPANY
    homepage = PAGE
    scope = "Canarias"

    def __init__(self) -> None:
        self._places: dict[str, str | None] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = today_madrid(datetime.now(timezone.utc))
        entries = [e for e in parse_page(http.get(PAGE)) if e["deadline"] >= today]
        self._places = {e["ref"]: e["place"] for e in entries}
        return [
            ListedOffer(
                ref=e["ref"], title=e["title"], company=COMPANY, url=e["url"], apply_url=e["url"],
                kind=None, deadline=e["deadline"], published_on=e["published_on"],
            )
            for e in entries
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        detail = parse_detail(http.get(offer.url))
        if detail is not None:
            detail.location = self._places.get(offer.ref)
        return detail
