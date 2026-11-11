"""TMB (Transports Metropolitans de Barcelona).

`Treball i pràctiques` (Liferay, en catalán) lista todas las ofertas laborales en un carrusel
(`li.carrusel-ofertas-laborals_new-li`, 65 el 2026-11-11, casi todas cerradas): título, enlace a la
ficha (`/ca/w/oferta-10242-…`) y «Termini: 07/11/2026 - 16/11/2026», sin hora. Cada tarjeta lleva a la
vez las etiquetas «En curs» y «Finalitzat» (la web enseña una con CSS): mandan las fechas.

Es oferta la tarjeta con el fin del plazo sin vencer. La ficha da plazas titulares, la descripción
(«per a la cobertura, amb caràcter indefinit, de 1 plaça…»), las bases en PDF y el formulario de
inscripción. Las prácticas van en otra página y no se leen.

Procesos sin hacer: «Estat dels processos de selecció» enlaza 74 páginas de seguimiento, una por
proceso; leerlas todas en cada pasada son demasiadas peticiones.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.tmb.cat"
PAGE = SITE + "/ca/treball-i-practiques"
COMPANY = "TMB"
PERIOD = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})")
REF = re.compile(r"/oferta-(\d+)-")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_page(html: str) -> list[dict]:
    cards = BeautifulSoup(html, "html.parser").select("li.carrusel-ofertas-laborals_new-li")
    if not cards:
        raise SourceLayoutError("TMB: no se encuentran las ofertas laborales")
    found, seen = [], set()
    for card in cards:
        link, title = card.find("a", href=True), card.select_one(".carrusel-ofertas-laborals__card-title")
        period = PERIOD.search(_clean(card.get_text(" ")))
        if link is None or title is None or period is None:
            raise SourceLayoutError("TMB: oferta sin enlace, título o plazo")
        url = urljoin(SITE, link["href"])
        if url in seen:
            continue
        seen.add(url)
        d1, m1, y1, d2, m2, y2 = period.groups()
        ref = REF.search(url)
        found.append({"title": _clean(title.get_text(" ")), "url": url, "ref": ref.group(1) if ref else url,
                      "opens_on": f"{y1}-{m1}-{d1}", "deadline": f"{y2}-{m2}-{d2}"})
    return found


def parse_detail(html: str) -> OfferDetail:
    """Descripción, bases, plazas titulares y contrato. El formulario de inscripción se enlaza desde la ficha."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".desc-text-oferta-reduida")
    if body is None:
        raise SourceLayoutError("TMB: ficha sin descripción")
    text = _clean(body.get_text(" "))
    sections = [{"title": "Descripció", "level": 2, "html": sanitize(body.decode_contents())}]
    bases = [a for a in soup.select("a[href]") if re.search(r"\.pdf(?:[/?]|$)", a["href"], re.I)]  # Liferay: «….pdf/<uuid>?t=…»
    if bases:
        link = bases[0]
        sections.append({"title": "Bases de la convocatòria", "level": 2,
                         "html": f'<p><a href="{escape(urljoin(SITE, link["href"]), quote=True)}">Bases de la convocatoria (PDF)</a></p>'})
    seats = soup.find(string=re.compile(r"Places titulars"))
    number = re.search(r"\d+", _clean(seats.find_parent("div").get_text(" "))) if seats else None
    kind = "indefinido" if re.search(r"car[àa]cter indefinit", text, re.I) else (
        "temporal" if re.search(r"car[àa]cter temporal", text, re.I) else None)
    return OfferDetail(sections=sections, location="Barcelona", positions=int(number.group(0)) if number else None,
                       kind=kind)


class TmbSource(Source):
    id = "tmb"
    name = "TMB (Transports Metropolitans de Barcelona)"
    homepage = PAGE
    scope = "Cataluña"
    text_lang = "ca"
    ref_code = re.compile(r"\d+")  # la «Referència» de la ficha

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                        kind=None, deadline=row["deadline"], opens_on=row["opens_on"])
            for row in parse_page(http.get(PAGE)) if not deadline_passed(row["deadline"], None, now)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return parse_detail(http.get(offer.url))
