"""IdiSNA (Instituto de Investigación Sanitaria de Navarra).

El RSS de empleo (`/rss.aspx?S=39`) trae las 15 últimas convocatorias, abiertas y cerradas, con
el texto completo de cada una. El texto tiene siempre los mismos rótulos: «Modalidad de contrato:
…», «Fecha de publicación: 23 de octubre de 2026» y «Fecha de cierre: 6 de noviembre de 2026 a
las 12:00h». El listado web dice «Vigente» con el plazo vencido: no se usa.

Es oferta la convocatoria cuyo cierre, con su hora, no ha pasado. Una sin fecha de cierre detiene
la fuente: no se ofrece sin plazo. El título es el del RSS, literal (alguno acaba en «- Copia»).
Navarrabiomed publica aparte, con otras referencias.
"""
from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..dates import clock, spanish_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

FEED = "https://www.idisna.es/rss.aspx?S=39"
HOMEPAGE = "https://www.idisna.es/rrhh/empleo"
COMPANY = "IdiSNA"
DATE = r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})"
CLOSING = re.compile(r"Fecha de cierre:\s*" + DATE + r"(?:\s+a\s+las\s+(\d{1,2}[:.]\d{2}))?", re.I)
PUBLISHED = re.compile(r"Fecha de publicación:\s*" + DATE, re.I)
# El rótulo siguiente empieza en mayúscula; «Contrato de duración determinada» no corta.
CONTRACT = re.compile(r"Modalidad de contrato\s*:\s*(.+?)(?:\.\s|\s+(?-i:Salario|Duración|Fecha de|Jornada)|$)", re.I)
REF = re.compile(r"[?&]N=(\d+)")


def _text(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html, "html.parser").get_text(" ")).strip()


def parse_feed(xml: str) -> list[dict]:
    try:
        root = ET.fromstring(xml)
    except ET.ParseError as error:
        raise SourceLayoutError(f"IdiSNA: el RSS no se puede leer ({error})") from error
    items = root.findall("./channel/item")
    if not items:
        raise SourceLayoutError("IdiSNA: el RSS no trae convocatorias")
    found = []
    for item in items:
        title, link = item.findtext("title", "").strip(), item.findtext("link", "").strip()
        html = item.findtext("description", "")
        ref = REF.search(link)
        if not (title and ref and html):
            raise SourceLayoutError(f"IdiSNA: convocatoria sin título, enlace o texto: {title!r}")
        text = _text(html)
        closing, published, contract = CLOSING.search(text), PUBLISHED.search(text), CONTRACT.search(text)
        deadline = spanish_date(*closing.group(1, 2, 3)) if closing else None
        if deadline is None:
            raise SourceLayoutError(f"IdiSNA: {title} sin fecha de cierre legible")
        opened = spanish_date(*published.groups()) if published else None
        found.append({
            "ref": ref.group(1), "title": title, "url": link, "html": html,
            "deadline": deadline.isoformat(), "deadline_time": clock(closing.group(4)),
            "published_on": opened.isoformat() if opened else None,
            "contract": contract.group(1).strip().rstrip(".") if contract else None,
        })
    return found


class IdisnaSource(Source):
    id = "idisna"
    name = COMPANY
    homepage = HOMEPAGE
    scope = "Comunidad Foral de Navarra"
    apply_label = "Ver la convocatoria y enviar la candidatura"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._html: dict[str, str] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        entries = [e for e in parse_feed(http.get(FEED))
                   if not deadline_passed(e["deadline"], e["deadline_time"], now)]
        self._html = {e["ref"]: e["html"] for e in entries}
        return [
            ListedOffer(
                ref=e["ref"], title=e["title"], company=COMPANY, url=e["url"], apply_url=e["url"],
                kind=None, deadline=e["deadline"], deadline_time=e["deadline_time"],
                published_on=e["published_on"], contract=e["contract"],
            )
            for e in entries
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        html = self._html.get(offer.ref)
        if html is None:
            return OfferDetail()
        return OfferDetail(sections=[{"title": "Convocatoria", "level": 2, "html": sanitize(html)}],
                           location="Navarra")
