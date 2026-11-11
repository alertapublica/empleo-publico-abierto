"""EMT Madrid (Empresa Municipal de Transportes de Madrid).

`Empleo` (ASP.NET, Kentico) lista «Procesos de selección activos» (17 el 2026-11-11, desde 2022): un
enlace por convocatoria con la fecha al final del título («Convocatoria 2 plazas Titulado/a Superior
Dirección de Servicios de Transporte 23-10-2026»).

La ficha (`.tab-pane.active`) da «Periodo de inscripción: 24/10/2026 - 31/12/2026», una frase y los
documentos numerados con su fecha («1. Bases convocatoria 23-10-2026»). La inscripción es un
formulario de suscripción en la misma ficha (no se copia).

Se leen todas las fichas de la lista (hoy, 17): si se filtrara por antigüedad, el motor daría por
retirados procesos que la web sigue mostrando. Es oferta la que tiene el periodo de inscripción sin
vencer; las demás son procesos, cuyos comunicados son sus documentos, con la fecha que trae su nombre.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.emtmadrid.es"
PAGE = SITE + "/Empresa/Empleo"
COMPANY = "EMT Madrid"
TRAILING_DAY = re.compile(r"\s*(\d{2})-(\d{2})-(\d{4})\s*$")
PERIOD = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})")
POSITIONS = re.compile(r"^Convocatoria (\d+) plazas?\b", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _iso(day: str, month: str, year: str) -> str:
    return date(int(year), int(month), int(day)).isoformat()


def parse_page(html: str) -> list[dict]:
    heading = BeautifulSoup(html, "html.parser").find(string=re.compile(r"Procesos de selecci[óo]n activos"))
    listing = heading.find_next("ul") if heading else None
    if listing is None:
        raise SourceLayoutError("EMT: no se encuentra la lista de procesos activos")
    found = []
    for link in listing.select("li a[href]"):
        title = _clean(link.get_text(" "))
        day = TRAILING_DAY.search(title)
        if day is None:
            raise SourceLayoutError(f"EMT: convocatoria sin fecha en el título: «{title}»")
        url = urljoin(SITE, link["href"])
        found.append({"title": title[:day.start()].strip(), "url": url, "published": _iso(*day.groups()),
                      "ref": url.rstrip("/").rsplit("/", 1)[-1].removesuffix(".aspx")})
    if not found:
        raise SourceLayoutError("EMT: la lista de procesos activos está vacía")
    return found


def parse_detail(html: str) -> dict:
    pane = BeautifulSoup(html, "html.parser").select_one(".tab-pane.active")
    period = PERIOD.search(_clean(pane.get_text(" "))) if pane else None
    if pane is None or period is None:
        raise SourceLayoutError("EMT: ficha sin periodo de inscripción")
    for unwanted in pane.select(".appointment-form, script, style"):
        unwanted.decompose()
    documents = []
    for link in pane.select("ul li a[href]"):
        label = _clean(link.get_text(" "))
        day = TRAILING_DAY.search(label)
        documents.append({"label": label, "url": urljoin(SITE, link["href"]), "date": _iso(*day.groups()) if day else ""})
    texts = [p for p in pane.find_all("p") if not PERIOD.search(p.get_text(" "))]
    d1, m1, y1, d2, m2, y2 = period.groups()
    return {"opens_on": _iso(d1, m1, y1), "deadline": _iso(d2, m2, y2), "period": _clean(period.group(0)),
            "summary": sanitize("".join(str(p) for p in texts)), "documents": documents}


class EmtSource(Source):
    id = "emt"
    name = "EMT Madrid"
    homepage = PAGE
    scope = "Comunidad de Madrid"
    apply_label = "Ver la convocatoria y suscribirse en la web oficial"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._rows: list[tuple[dict, dict]] | None = None

    def _read(self, http: Client) -> list[tuple[dict, dict]]:
        if self._rows is None:
            self._rows = [(row, parse_detail(http.get(row["url"]))) for row in parse_page(http.get(PAGE))]
        return self._rows

    def _is_offer(self, detail: dict) -> bool:
        return not deadline_passed(detail["deadline"], None, self._now or datetime.now(timezone.utc))

    def list_offers(self, http: Client) -> list[ListedOffer]:
        offers = []
        for row, detail in self._read(http):
            if not self._is_offer(detail):
                continue
            seats = POSITIONS.match(row["title"])
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"], kind=None,
                positions=int(seats.group(1)) if seats else None, deadline=detail["deadline"],
                opens_on=detail["opens_on"], published_on=row["published"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        detail = next((d for r, d in self._read(http) if r["ref"] == offer.ref), None)
        if detail is None:
            return OfferDetail(location="Madrid")
        sections = [{"title": "Periodo de inscripción", "level": 2, "html": sanitize(f"<p>{escape(detail['period'])}</p>")}]
        if detail["summary"]:
            sections.append({"title": "La convocatoria", "level": 2, "html": detail["summary"]})
        if detail["documents"]:
            items = "".join(f'<li><a href="{escape(d["url"], quote=True)}">{escape(d["label"])}</a></li>'
                            for d in detail["documents"])
            sections.append({"title": "Documentos", "level": 2, "html": sanitize(f"<ul>{items}</ul>")})
        return OfferDetail(location="Madrid", sections=sections)

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Los documentos de las convocatorias con la inscripción cerrada, con la fecha de su nombre."""
        return [
            Announcement(date=d["date"], process=row["title"], title=d["label"], url=d["url"], process_url=row["url"])
            for row, detail in self._read(http) if not self._is_offer(detail)
            for d in detail["documents"]
        ]
