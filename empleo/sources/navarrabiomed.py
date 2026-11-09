"""Navarrabiomed (contrata la Fundación Miguel Servet).

Drupal. `/es/empleo` muestra una tarjeta por proceso con referencia, «Fecha de publicación» y
«Fecha de cierre» (sin hora), título y enlace a la ficha. La ficha tiene el texto (campo `body`),
las bases en PDF y el formulario de inscripción. La hora de cierre solo está en las bases («Fecha
de cierre: 20 de noviembre de 2026 a las 12.00h»; en una ampliación, «hasta el 13 de noviembre de
2026 a las 12.00h»): vale si las bases la dan para el día del listado. El contrato también está
solo en las bases y no se lee. No comparte referencias con IdiSNA.

Es oferta la tarjeta cuyo cierre no ha pasado (el último día cuenta entero). El 2026-11-08 solo
había tarjetas abiertas: no se sabe si las cerradas se retiran o se quedan.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import hour_on, numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..pdftext import read_pdf
from ..sanitize import sanitize
from .base import Source

SITE = "https://navarrabiomed.es"
PAGE = f"{SITE}/es/empleo"
DATE = re.compile(r"\d\d/\d\d/\d{4}")


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _date(card, css: str) -> str | None:
    node = card.select_one(css)
    found = DATE.search(_text(node)) if node else None
    return numeric_date(found.group(0)) if found else None


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    # La referencia y las fechas van en una columna y el título en otra: la tarjeta es el
    # primer contenedor que tiene las dos.
    cards = [next((p for p in node.parents if p.select_one("h3.title")), node) for node in soup.select("div.reference")]
    if not cards:
        raise SourceLayoutError("Navarrabiomed: no se encuentran las tarjetas de empleo")
    found = []
    for card in cards:
        ref, link = card.select_one("div.reference span"), card.select_one("h3.title a[href]")
        deadline = _date(card, "div.end-date")
        if not (ref and link and deadline):
            raise SourceLayoutError("Navarrabiomed: tarjeta sin referencia, enlace o fecha de cierre")
        found.append({
            "ref": _text(ref), "title": _text(link), "url": urljoin(SITE, link["href"]),
            "published_on": _date(card, "div.start-date"), "deadline": deadline,
        })
    return found


def bases_url(html: str) -> str | None:
    link = BeautifulSoup(html, "html.parser").select_one(".field--name-field-attach-empleo a[href]")
    return urljoin(SITE, link["href"]) if link else None


def parse_detail(html: str) -> OfferDetail:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".field--name-body")
    if body is None:
        raise SourceLayoutError("Navarrabiomed: ficha sin texto")
    sections = [{"title": "Convocatoria", "level": 2, "html": sanitize(body.decode_contents())}]
    bases = bases_url(html)
    if bases:
        url = escape(bases, quote=True)
        sections.append({"title": "Documentos de la convocatoria", "level": 2,
                         "html": sanitize(f'<ul><li><a href="{url}">Bases del proceso</a></li></ul>')})
    return OfferDetail(sections=sections, location="Pamplona (Navarra)")


class NavarrabiomedSource(Source):
    id = "navarrabiomed"
    name = "Navarrabiomed (Fundación Miguel Servet)"
    homepage = PAGE
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    title_code = re.compile(r"(?P<code>\d{2}-\d+)\s+(?P<title>.+)")  # «26-42 Personal administrativo»
    detail_version = 2  # la hora de cierre sale de las bases (#17)
    scope = "Comunidad Foral de Navarra"
    apply_label = "Ver la convocatoria e inscribirse"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(
                ref=e["ref"], title=e["title"], company="Fundación Miguel Servet", url=e["url"],
                apply_url=e["url"], kind=None, deadline=e["deadline"], published_on=e["published_on"],
            )
            for e in parse_listing(http.get(PAGE)) if not deadline_passed(e["deadline"], None, now)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        html = http.get(offer.url)
        detail, bases = parse_detail(html), bases_url(html)
        if bases and offer.deadline:
            try:
                text = read_pdf(http, bases, "Navarrabiomed")
            except SourceLayoutError:  # sin texto legible, el último día cuenta entero
                return detail
            detail.deadline_time = hour_on(text, date.fromisoformat(offer.deadline))
        return detail
