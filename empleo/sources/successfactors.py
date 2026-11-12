"""Portales de empleo de SAP SuccessFactors (Career Site Builder): Correos, Navantia, BSM…

El listado de cada categoría (`/go/<nombre>/<id>/`) llega ya montado en el HTML, con título,
departamento, centro y fecha de publicación. La ficha (`/job/<texto>/<id>/`) añade, como
microdatos schema.org/JobPosting, la localidad, la fecha de cierre y el texto de la oferta.
La inscripción es siempre `/talentcommunity/apply/<id>/`, en la web oficial.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError
from ..sanitize import sanitize
from .base import Source

MONTHS = {"ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6, "jul": 7,
          "ago": 8, "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dic": 12,
          # en catalán (BSM): «11 de nov. 2026», «14 d’oct. 2026»
          "gen": 1, "febr": 2, "març": 3, "maig": 5, "juny": 6, "ag": 8, "set": 9, "des": 12}
MAX_PAGES = 40
RESULTS = re.compile(r"Result(?:ados|ats)\s+(\d+)\s*[–-]\s*(\d+)\s+de\s+(\d+)")
JOB_ID = re.compile(r"/job/[^?#]*?/(\d+)/?(?:[?#].*)?$")
UTC_DATE = re.compile(r"[A-Za-z]{3} ([A-Za-z]{3}) (\d{1,2}) (\d{2}):(\d{2}):(\d{2}) UTC (\d{4})")
ENGLISH_MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def _list_date(value: str) -> str | None:
    match = re.fullmatch(r"(\d{1,2})\s+(?:de\s+|d[’']\s*)?([a-záéíóúç]+)\.?\s+(\d{4})", _clean(value).lower())
    if not match or match.group(2) not in MONTHS:
        return None
    return f"{match.group(3)}-{MONTHS[match.group(2)]:02d}-{int(match.group(1)):02d}"


def _closing_date(value: str) -> str | None:
    """`validThrough` llega en UTC a la medianoche local del día siguiente al último día."""
    match = UTC_DATE.fullmatch(value.strip())
    if not match or match.group(1) not in ENGLISH_MONTHS:
        return None
    month, day, hour, minute, second, year = match.groups()
    moment = datetime(int(year), ENGLISH_MONTHS.index(month) + 1, int(day), int(hour),
                      int(minute), int(second), tzinfo=timezone.utc).astimezone(MADRID)
    if (moment.hour, moment.minute) == (0, 0):
        moment -= timedelta(days=1)
    return moment.date().isoformat()


def parse_listing(html: str, base: str) -> tuple[list[dict], int]:
    """Filas de una página de categoría y total declarado de resultados."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table#searchresults")
    if table is None:
        # Aviso «sin resultados» de la plataforma, igual en castellano y en catalán (BSM): «A continuación,
        # figuran las 0 últimas ofertas…», «A continuació s'enumeren els 0 llocs…». Sin ese «0», no vale.
        message = soup.select_one("div#noresults #noresults-message")
        if message is not None and re.search(r"\b0\b", message.get_text(" ")):
            return [], 0
        raise SourceLayoutError("SuccessFactors: no se encuentra la tabla de resultados")
    rows = []
    for tr in table.select("tr.data-row"):
        link = tr.select_one("a.jobTitle-link")
        match = JOB_ID.search(link["href"]) if link and link.get("href") else None
        if not match:
            raise SourceLayoutError("SuccessFactors: fila sin enlace a la oferta")

        def cell(name: str) -> str:
            node = tr.select_one(f"td.{name}")
            return _clean(node.get_text(" ")) if node else ""

        rows.append({
            "ref": match.group(1),
            "title": _clean(link.get_text(" ")),
            "url": urljoin(base, link["href"]),
            "department": cell("colDepartment") or None,
            "facility": cell("colFacility") or None,
            "published_on": _list_date(cell("colDate")),
        })
    label = RESULTS.search(_clean(soup.get_text(" ")))
    if rows and not label:
        raise SourceLayoutError("SuccessFactors: no se encuentra el total de resultados")
    return rows, int(label.group(3)) if label else 0


def parse_detail(html: str) -> OfferDetail | None:
    soup = BeautifulSoup(html, "html.parser")
    posting = soup.select_one('[itemtype*="JobPosting"]')
    if posting is None:
        return None

    def meta(name: str) -> str | None:
        node = posting.find(attrs={"itemprop": name})
        if node is None:
            return None
        return _clean(node.get("content") or node.get_text(" ")) or None

    description = posting.find(attrs={"itemprop": "description"})
    sections = []
    if description is not None:
        body = sanitize(description.decode_contents())
        if BeautifulSoup(body, "html.parser").get_text(strip=True):
            sections.append({"title": "Descripción de la oferta", "level": 2, "html": body})
    return OfferDetail(
        sections=sections,
        location=meta("addressLocality"),
        deadline=_closing_date(meta("validThrough") or ""),
    )


class SuccessFactorsSource(Source):
    """`categories` son pares (tipo de contrato o None, ruta `/go/...`)."""

    def __init__(self, id: str, name: str, host: str, company: str,
                 categories: list[tuple[str | None, str]], location: str | None = None) -> None:
        self.id, self.name, self.company = id, name, company
        self.location = location  # si el microdato de la ficha no da la localidad (BSM pone «Selecció»)
        self.host = host.rstrip("/")
        self.homepage = f"{self.host}/"
        self.categories = categories
        self._rows: dict[str, dict] = {}

    def _category(self, http: Client, path: str) -> list[dict]:
        base = f"{self.host}{path}"
        found: dict[str, dict] = {}
        total = 0
        for _ in range(MAX_PAGES):
            url = base if not found else f"{base}{len(found)}/"
            rows, total = parse_listing(http.get(url), self.host)
            new = [row for row in rows if row["ref"] not in found]
            if not new:
                break
            found.update({row["ref"]: row for row in new})
            if len(found) >= total:
                break
        if len(found) < total:
            raise SourceLayoutError(
                f"{self.id}: la categoría declara {total} resultados y se leen {len(found)}"
            )
        return list(found.values())

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._rows = {}
        for kind, path in self.categories:
            for row in self._category(http, path):
                if row["ref"] not in self._rows:
                    self._rows[row["ref"]] = {**row, "kind": kind}
        return [
            ListedOffer(
                ref=ref, title=row["title"], company=self.company, url=row["url"],
                apply_url=f"{self.host}/talentcommunity/apply/{ref}/?locale=es_ES",
                kind=row["kind"],
            )
            for ref, row in self._rows.items()
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        detail = parse_detail(http.get(offer.url))
        if detail is not None and self.location:
            detail.location = self.location
        return detail

    def enrich(self, http: Client) -> dict[str, dict]:
        # Todo viene ya en el listado: no hace falta otra petición.
        return {
            ref: {
                "published_on": row["published_on"],
                "department": " · ".join(x for x in (row["department"], row["facility"]) if x) or None,
            }
            for ref, row in self._rows.items()
        }
