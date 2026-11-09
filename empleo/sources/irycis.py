"""IRYCIS (Instituto Ramón y Cajal de Investigación Sanitaria), Madrid.

Contrata la Fundación para la Investigación Biomédica del Hospital Universitario Ramón y Cajal.
`/es/irycis/fundacion/empleo/` es una tabla por año: la del año en curso bajo un `h2` («2026») y
las anteriores en un acordeón (`li.accordion-navigation`, año en `a.title`). Cada fila: referencia
(`C75/26`), «Fecha conv.» y «Fecha cierre» sin año («04/11», «16/11»), título (enlace a la
convocatoria en PDF, escaneado y sin texto), perfil y acta (listas de personas: no se enlaza).

El año es el de la tabla y tiene que coincidir con el sufijo de la referencia; si no, la fila no se
usa. Si el cierre cae antes que la convocatoria, es del año siguiente (C81/25: 29/12 → 22/01), y
un plazo de más de 60 días se descarta. Sin hora de cierre. Solo se leen las tablas de los dos
últimos años; las filas sin referencia `Cnn/aa` (expresiones de interés para estancias) no se
ofrecen. El título es el literal de la web (a menudo la titulación pedida). Contrato sin indicar.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from .base import Source

SITE = "https://www.irycis.org"
PAGE = f"{SITE}/es/irycis/fundacion/empleo/"
COMPANY = "Fundación para la Investigación Biomédica del Hospital Universitario Ramón y Cajal"
REF = re.compile(r"C\d+/(\d{2})")
DM = re.compile(r"(\d{2})/(\d{2})")
MAX_PLAZO = 60


def _tables(soup: BeautifulSoup) -> list[tuple[int, object]]:
    """(año, tabla) del año en curso y del anterior."""
    found = []
    current = soup.select_one("main section.section--text h2")
    table = current.find_next_sibling("table") if current else None
    if table is not None and current.get_text(strip=True).isdigit():
        found.append((int(current.get_text(strip=True)), table))
    item = soup.select_one("main li.accordion-navigation")
    if item is not None:
        year, table = item.select_one("a.title"), item.select_one("table")
        if year is not None and table is not None and year.get_text(strip=True).isdigit():
            found.append((int(year.get_text(strip=True)), table))
    if len(found) != 2 or found[0][0] != found[1][0] + 1:
        raise SourceLayoutError("IRYCIS: no se encuentran las tablas del año en curso y del anterior")
    return found


def parse_page(html: str) -> list[dict]:
    found = []
    for year, table in _tables(BeautifulSoup(html, "html.parser")):
        for row in table.select("tr"):
            cells = row.select("td")
            if not cells:
                continue  # cabecera
            if len(cells) < 4:
                raise SourceLayoutError("IRYCIS: fila con menos columnas")
            ref, conv, close = (" ".join(c.get_text().split()) for c in cells[:3])
            suffix = REF.fullmatch(ref)
            if suffix is None or int(suffix.group(1)) != year % 100:
                continue
            link = cells[3].select_one("a[href]")
            starts, ends = DM.fullmatch(conv), DM.fullmatch(close)
            if link is None or starts is None or ends is None:
                raise SourceLayoutError(f"IRYCIS: fila {ref} sin enlace o fechas")
            opens_on = date(year, int(starts.group(2)), int(starts.group(1)))
            deadline = date(year, int(ends.group(2)), int(ends.group(1)))
            if deadline < opens_on:
                deadline = date(year + 1, deadline.month, deadline.day)
            if deadline - opens_on > timedelta(days=MAX_PLAZO):
                continue
            found.append({
                "ref": ref, "title": " ".join(link.get_text().split()), "url": urljoin(SITE, link["href"]),
                "opens_on": opens_on.isoformat(), "deadline": deadline.isoformat(),
            })
    if not found:
        raise SourceLayoutError("IRYCIS: ninguna fila con referencia Cnn/aa")
    return found


class IrycisSource(Source):
    id = "irycis"
    name = "IRYCIS"
    homepage = PAGE
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    scope = "Comunidad de Madrid"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(
                ref=e["ref"], title=e["title"], company=COMPANY, url=e["url"], apply_url=e["url"],
                kind=None, opens_on=e["opens_on"], deadline=e["deadline"],
            )
            for e in parse_page(http.get(PAGE)) if not deadline_passed(e["deadline"], None, now)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(location="Madrid")
