"""FRCB-IDIBAPS (Fundació de Recerca Clínic Barcelona - IDIBAPS).

`Ofertes de feina` (web del Clínic, en catalán) tiene dos pestañas en la misma página: `#active`
(«Obertes», todas en una página: 28 el 2026-11-11) y `#inactive` («Tancades», 318 páginas de
histórico, que no se leen). Cada tarjeta da el título («[FRCB-IDIBAPS] Tècnic Plataformes … (Convocatòria
FU-338/2026)»), enlazado al PDF de la convocatoria, la «Data límit» sin hora y el estado. Hay un hueco
para resoluciones, vacío en todas las vistas: de momento no hay procesos.

Es oferta la tarjeta de `#active` con la fecha límite sin vencer. El código de la convocatoria es el
`ref` y se enseña aparte del título. Los títulos mezclan catalán, castellano e inglés: se dejan tal
cual, con `lang="ca"`.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from .base import Source

PAGE = "https://www.clinicbarcelona.org/ca/idibaps/carrera-professional-idibaps/ofertes-de-treball"
COMPANY = "FRCB-IDIBAPS"
DAY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
CODE = re.compile(r"\(Convocat[òo]ria ([A-Z]+(?:-[A-Z]+)*-\d+/\d{4})\)\s*$")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_page(html: str) -> list[dict]:
    """Las tarjetas de la pestaña «Obertes»."""
    active = BeautifulSoup(html, "html.parser").select_one("#active")
    if active is None:
        raise SourceLayoutError("IDIBAPS: no se encuentra la pestaña de ofertas abiertas")
    found = []
    for card in active.select(".research-offer-card"):
        link = card.select_one(".legend-list__inner-data a[href]")
        values = [_clean(v.get_text(" ")) for v in card.select(".legend-list__inner-data") if not v.select_one(".p-small")]
        day = next((DAY.fullmatch(v) for v in values if DAY.fullmatch(v)), None)
        if link is None or day is None:
            raise SourceLayoutError("IDIBAPS: oferta sin enlace o sin fecha límite")
        title = _clean(link.get_text(" "))
        code = CODE.search(title)
        found.append({
            "title": title, "url": urljoin(PAGE, link["href"]),
            "ref": code.group(1) if code else urljoin(PAGE, link["href"]),
            "deadline": date(int(day.group(3)), int(day.group(2)), int(day.group(1))).isoformat(),
        })
    return found


class IdibapsSource(Source):
    id = "idibaps"
    name = "FRCB-IDIBAPS"
    homepage = PAGE
    scope = "Cataluña"
    text_lang = "ca"
    apply_label = "Ver la convocatoria (PDF) y cómo presentarse"
    title_code = re.compile(r"\[FRCB-IDIBAPS\]\s*(?P<title>.+?)\s*\(Convocat[òo]ria (?P<code>[A-Z]+(?:-[A-Z]+)*-\d+/\d{4})\)")
    ref_code = re.compile(r"[A-Z]+(?:-[A-Z]+)*-\d+/\d{4}")

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                        kind=None, deadline=row["deadline"])
            for row in parse_page(http.get(PAGE)) if not deadline_passed(row["deadline"], None, now)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        link = f'<p><a href="{escape(offer.url, quote=True)}">Convocatoria en PDF</a>, con las funciones, los requisitos, el contrato y cómo presentar la candidatura.</p>'
        return OfferDetail(location="Barcelona", sections=[{"title": "La convocatoria", "level": 2, "html": link}])
