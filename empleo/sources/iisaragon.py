"""Fundación IIS Aragón (Instituto de Investigación Sanitaria Aragón).

`Empleo` (WordPress) lista diez entradas por página, de la más reciente a la más antigua, con título
(«Director/a Ejecutivo/a [Ref. RRHH-26/049]»), enlace y fecha de publicación («22-10-2026»). También
entran avisos generales sin referencia («Modificación de la composición de las comisiones…»): no son
ofertas y no se leen.

El plazo solo está en la entrada: «Plazo de Inicio: Jueves, 22 de octubre de 2026» y «Plazo de Fin:
23:59 horas del viernes, 13 de noviembre de 2026». Se leen las entradas con referencia publicadas en
los últimos RECENT_DAYS días de la primera página (hoy, siete). Es oferta la que tiene el fin sin
vencer. La entrada lleva un formulario de candidatura (Contact Form 7) que no se copia.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup

from ..dates import MONTHS, spanish_date
from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

PAGE = "https://www.iisaragon.es/empleo/"
COMPANY = "IIS Aragón"
RECENT_DAYS = 40
REF = re.compile(r"\[Ref\.\s*(RRHH-\d+/\d+)\]")
MONTH = "(" + "|".join(MONTHS) + ")"
END = re.compile(r"Plazo de Fin:\s*(?:(\d{1,2}[:.]\d{2})\s*horas?\s+del?\s+)?(?:[a-záéíóú]+,?\s+)?(\d{1,2}) de "
                 + MONTH + r" de (\d{4})", re.I)
START = re.compile(r"Plazo de Inicio:\s*(?:[a-záéíóú]+,?\s+)?(\d{1,2}) de " + MONTH + r" de (\d{4})", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_page(html: str) -> list[dict]:
    found = []
    for item in BeautifulSoup(html, "html.parser").select(".layer-content"):
        link, day = item.select_one(".title_link a[href]"), item.select_one(".post_date")
        if link is None or day is None:
            continue
        published = re.fullmatch(r"(\d{2})-(\d{2})-(\d{4})", _clean(day.get_text()))
        if published is None:
            raise SourceLayoutError(f"IIS Aragón: fecha de publicación ilegible: «{_clean(day.get_text())}»")
        title = _clean(link.get_text(" "))
        ref = REF.search(title)
        found.append({"title": title, "url": link["href"], "ref": ref.group(1) if ref else None,
                      "published": date(int(published.group(3)), int(published.group(2)), int(published.group(1)))})
    if not found:
        raise SourceLayoutError("IIS Aragón: el listado no tiene entradas")
    return found


def parse_detail(html: str) -> dict:
    content = BeautifulSoup(html, "html.parser").select_one(".the_content_wrapper")
    if content is None:
        raise SourceLayoutError("IIS Aragón: entrada sin contenido")
    for unwanted in content.select("script, style, div.wpcf7, form"):
        unwanted.decompose()
    text = _clean(content.get_text(" "))
    end, start = END.search(text), START.search(text)
    if end is None:
        raise SourceLayoutError("IIS Aragón: entrada sin «Plazo de Fin»")
    hour, day, month, year = end.groups()
    deadline = spanish_date(day, month, year)
    opens = spanish_date(*start.groups()) if start else None
    return {
        "deadline": deadline.isoformat() if deadline else None, "deadline_time": hour.replace(".", ":") if hour else None,
        "opens_on": opens.isoformat() if opens else None,
        "sections": [{"title": "La convocatoria", "level": 2, "html": sanitize(content.decode_contents())}],
    }


class IisAragonSource(Source):
    id = "iisaragon"
    name = "IIS Aragón"
    homepage = PAGE
    scope = "Aragón"
    title_code = re.compile(r"(?P<title>.+?)\s*\[Ref\.\s*(?P<code>RRHH-\d+/\d+)\]")
    ref_code = re.compile(r"RRHH-\d+/\d+")

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._details: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        since = now.astimezone(MADRID).date() - timedelta(days=RECENT_DAYS)
        offers = []
        for entry in parse_page(http.get(PAGE)):
            if entry["ref"] is None or entry["published"] < since:
                continue
            detail = parse_detail(http.get(entry["url"]))
            if detail["deadline"] is None or deadline_passed(detail["deadline"], detail["deadline_time"], now):
                continue
            self._details[entry["ref"]] = detail
            offers.append(ListedOffer(
                ref=entry["ref"], title=entry["title"], company=COMPANY, url=entry["url"], apply_url=entry["url"],
                kind=None, deadline=detail["deadline"], deadline_time=detail["deadline_time"],
                opens_on=detail["opens_on"], published_on=entry["published"].isoformat(),
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        detail = self._details.get(offer.ref) or parse_detail(http.get(offer.url))
        return OfferDetail(sections=detail["sections"])  # sin ubicación: hay grupos fuera de Zaragoza
