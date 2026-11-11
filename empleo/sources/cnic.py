"""CNIC (Centro Nacional de Investigaciones Cardiovasculares Carlos III, F.S.P.).

`Ofertas de empleo` (Drupal 7, Views) es una tabla con una fila por convocatoria: puesto (enlace a la
ficha), referencia («TECPROYECTO-FSC-10.26»), fin de inscripción («26/11/2026», sin hora) y estado
literal («Presentación de solicitudes», «En estudio de elegibilidad», «En subsanación», «Evaluación»,
«Resolución», «Cerrada»). El atributo `content` de la fecha no coincide con el texto: manda el texto.
`robots.txt` pide `Crawl-delay: 10`.

Es oferta la fila en «Presentación de solicitudes» con el plazo sin vencer; la ficha da el texto de la
convocatoria (`field-name-field-description`) y los criterios. Las demás son procesos: su comunicado es
el estado literal de la fila, sin fecha (la web no la da), y cada cambio de estado es uno nuevo.
«Cerrada» da el proceso por terminado.
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

PAGE = "https://www.cnic.es/es/empleo/ofertas-empleo"
COMPANY = "CNIC"
OPEN = "presentación de solicitudes"
CLOSED = "cerrada"
DAY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_page(html: str) -> list[dict]:
    table = BeautifulSoup(html, "html.parser").select_one("table.views-table")
    if table is None:
        raise SourceLayoutError("CNIC: no se encuentra la tabla de ofertas")
    found = []
    for row in table.select("tbody tr"):
        link = row.select_one("td.views-field-title a[href]")
        ref = row.select_one("td.views-field-field-reference")
        day = DAY.fullmatch(_clean(row.select_one("td.views-field-field-fecha").get_text(" "))
                            if row.select_one("td.views-field-field-fecha") else "")
        state = row.select_one("td.views-field-field-estado-convocatoria")
        if link is None or ref is None or day is None or state is None:
            raise SourceLayoutError("CNIC: fila sin puesto, referencia, fecha o estado")
        found.append({
            "title": _clean(link.get_text(" ")), "url": urljoin(PAGE, link["href"]), "ref": _clean(ref.get_text(" ")),
            "deadline": date(int(day.group(3)), int(day.group(2)), int(day.group(1))).isoformat(),
            "state": _clean(state.get_text(" ")),
        })
    if not found:
        raise SourceLayoutError("CNIC: la tabla no tiene filas")
    return found


def parse_detail(html: str) -> OfferDetail:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".field-name-field-description")
    if body is None:
        raise SourceLayoutError("CNIC: ficha sin texto de la convocatoria")
    for image in body.find_all("img"):
        image.decompose()
    sections = [{"title": "La convocatoria", "level": 2, "html": sanitize(body.decode_contents())}]
    criteria = [_clean(c.get_text(" ")) for c in soup.select(".field-name-field-criterios .field-name-field-criterio")]
    if criteria:
        items = "".join(f"<li>{escape(c)}</li>" for c in criteria if c)
        sections.append({"title": "Criterios de valoración", "level": 2, "html": sanitize(f"<ul>{items}</ul>")})
    return OfferDetail(sections=sections, location="Madrid")


class CnicSource(Source):
    id = "cnic"
    name = "CNIC (Centro Nacional de Investigaciones Cardiovasculares)"
    homepage = PAGE
    delay = 10.0  # Crawl-delay del robots.txt
    ref_code = re.compile(r"\S+")  # la referencia es el código público de la convocatoria

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._rows: list[dict] | None = None

    def _read(self, http: Client) -> list[dict]:
        if self._rows is None:
            self._rows = parse_page(http.get(PAGE))
        return self._rows

    def _is_offer(self, row: dict) -> bool:
        return row["state"].lower() == OPEN and not deadline_passed(
            row["deadline"], None, self._now or datetime.now(timezone.utc))

    def list_offers(self, http: Client) -> list[ListedOffer]:
        return [
            ListedOffer(ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"],
                        apply_url=row["url"] + "#block-inscripcion", kind=None, deadline=row["deadline"])
            for row in self._read(http) if self._is_offer(row)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return parse_detail(http.get(offer.url))

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Las convocatorias que ya no admiten solicitudes: su estado literal, sin fecha."""
        return [
            Announcement(date="", process=f"{row['title']} ({row['ref']})", title=row["state"], url=row["url"],
                         state="finalizado" if row["state"].lower() == CLOSED else "curso", process_url=row["url"])
            for row in self._read(http) if not self._is_offer(row)
        ]
