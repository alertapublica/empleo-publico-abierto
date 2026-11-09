"""SEPI (Sociedad Estatal de Participaciones Industriales).

`/es/empleo-publico` (Drupal) lista los procesos en curso, cada uno en `.bloque-empleo` con título
(`h2`), enlace a la ficha y un texto libre de estado (`.plazo`). No hay fechas de publicación: la
carpeta de los PDF (`/2026-04/`) es el mes de subida. El texto de estado cambia con cada fase («El
plazo para reclamar…», «Concluido el plazo…»); solo es oferta la frase del plazo de presentación de
candidaturas o solicitudes, con la fecha completa («finaliza el 1 de junio de 2026 a las 23.59
horas», «finalizará a las 23.59 horas del día 27 de enero de 2026»). Comprobado en capturas del
Internet Archive de 2025 y 2026. La ficha da el mismo texto y los documentos.

`sepi.es` no responde desde Actions: se lee por el relay (`VIA_RELAY` en `http.py`).
Los documentos de las fases (Procesos) aún no se anuncian: no tienen fecha.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import CLOCK, first_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

PAGE = "https://www.sepi.es/es/empleo-publico"
COMPANY = "SEPI"
# La frase del plazo de candidaturas, hasta el punto final («23.59» no corta: le sigue una cifra).
APPLY = re.compile(r"plazo de presentaci[oó]n de (?:candidaturas|solicitudes)\b(.*?)(?:\.\s|\.?$)", re.I)


def _clean(text: str) -> str:
    return " ".join(text.split())


def deadline_of(text: str) -> tuple[str | None, str | None]:
    """Último día y hora del plazo de candidaturas, si el texto lo da con fecha completa."""
    days, hours = set(), set()
    for clause in APPLY.findall(text):
        day = first_date(clause)
        if day:
            days.add(day)
            hours.update(f"{int(h):02d}:{m}" for h, m in CLOCK.findall(clause))
    if len(days) > 1:
        raise SourceLayoutError(f"SEPI: varios plazos de candidaturas en «{text}»")
    if not days:
        return None, None
    return days.pop().isoformat(), hours.pop() if len(hours) == 1 else None


def parse_page(html: str) -> list[dict]:
    blocks = BeautifulSoup(html, "html.parser").select(".bloque-empleo")
    if not blocks:
        raise SourceLayoutError("SEPI: no se encuentran los procesos")
    found = []
    for block in blocks:
        title, link = block.select_one("h2"), block.select_one("a[href*='/empleo-publico/']")
        if title is None or link is None:
            raise SourceLayoutError("SEPI: proceso sin título o enlace")
        url = urljoin(PAGE, link["href"])
        status = block.select_one(".plazo")
        found.append({
            "ref": url.rstrip("/").rsplit("/", 1)[-1], "title": _clean(title.get_text(" ")), "url": url,
            "status": _clean(status.get_text(" ")) if status else "",
        })
    return found


def documents(html: str) -> list[tuple[str, str]]:
    """Documentos de la ficha: (nombre, enlace)."""
    found = []
    for link in BeautifulSoup(html, "html.parser").select(".module-descargas a.descargas[href]"):
        name = link.select_one(".descarga-name")
        found.append((_clean((name or link).get_text(" ")), urljoin(PAGE, link["href"])))
    return found


class SepiSource(Source):
    id = "sepi"
    name = "SEPI"
    homepage = PAGE
    apply_label = "Ver las bases y cómo presentar la candidatura"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._status: dict[str, str] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_page(http.get(PAGE)):
            deadline, hour = deadline_of(row["status"])
            if deadline is None or deadline_passed(deadline, hour, now):
                continue
            self._status[row["ref"]] = row["status"]
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                kind=None, deadline=deadline, deadline_time=hour,
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        sections = []
        if offer.ref in self._status:
            sections.append({"title": "Plazo", "level": 2, "html": sanitize(f"<p>{escape(self._status[offer.ref])}</p>")})
        items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
                        for label, url in documents(http.get(offer.url)))
        if items:
            sections.append({"title": "Documentos de la convocatoria", "level": 2, "html": sanitize(f"<ul>{items}</ul>")})
        return OfferDetail(sections=sections)
