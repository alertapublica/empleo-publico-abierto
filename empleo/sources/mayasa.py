"""Mayasa (Minas de Almadén y Arrayanes, S.A., S.M.E.), Grupo SEPI.

WordPress con JetEngine. `/trabaja-con-nosotros/` lista todos los procesos (5 al revisarla), cada
uno en `.jet-engine-listing-overlay-wrap[data-url]` con estado («Cerrado»), «· PUBLICADO
DD-MM-AAAA», título (`h3`), contrato si lo hay («Indefinido ·»), ubicación («Almadén (Ciudad Real)
·») y «CIERRE · DD-MM-AAAA». Mandan las fechas, no el estado. La ficha (la misma `data-url`) es la
lista de comunicados con fecha y PDF; el primero es la convocatoria, que da la hora («finaliza el
día 27 de mayo a las 23:59 horas», sin año): vale solo si el día y el mes son los del cierre del
listado. La ficha y el PDF se leen solo para las que siguen en plazo. Clave: ruta de la ficha.

Al revisarla (2026-11-08) las 5 estaban cerradas: un bloque abierto está sin ver.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

from ..dates import MONTHS, clock, spanish_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..pdftext import read_pdf
from .base import Source

PAGE = "https://mayasa.es/trabaja-con-nosotros/"
COMPANY = "Minas de Almadén y Arrayanes (MAYASA)"
DMY = r"(\d{2})-(\d{2})-(\d{4})"
HOUR = re.compile(r"finaliza el d[ií]a (\d{1,2}) de (" + "|".join(MONTHS) + r")(?: de (\d{4}))? a las (\d{1,2}:\d{2})", re.I)


def _iso(day: str, month: str, year: str) -> str:
    return f"{year}-{month}-{day}"


def _fields(node) -> list[str]:
    """Textos de los widgets sin anidar, en orden."""
    return [" ".join(w.get_text().split()) for w in node.select(".elementor-widget") if w.select_one(".elementor-widget") is None]


def parse_page(html: str) -> list[dict]:
    blocks = BeautifulSoup(html, "html.parser").select(".jet-engine-listing-overlay-wrap[data-url]")
    if not blocks:
        raise SourceLayoutError("Mayasa: no se encuentran los procesos")
    found = []
    for block in blocks:
        title = block.select_one("h3")
        text = " ".join(block.get_text(" ").split())
        published, closes = re.search(rf"PUBLICADO {DMY}", text), re.search(rf"CIERRE · {DMY}", text)
        if title is None or published is None or closes is None:
            raise SourceLayoutError("Mayasa: proceso sin título, publicación o cierre")
        title = " ".join(title.get_text().split())
        fields = _fields(block)
        after = fields[fields.index(title) + 1:] if title in fields else []
        contract = after[0].strip("· ") if after else ""
        place = after[1].strip("· ") if len(after) > 1 else ""
        found.append({
            "ref": block["data-url"].rstrip("/").rsplit("/", 1)[-1], "title": title, "url": block["data-url"],
            "published_on": _iso(*published.groups()), "deadline": _iso(*closes.groups()),
            "contract": contract or None, "place": place or None,
        })
    return found


def convocatoria(html: str) -> str | None:
    """PDF del comunicado de convocatoria (el más antiguo que empieza por «Convocatoria»)."""
    found = []
    for item in BeautifulSoup(html, "html.parser").select(".jet-listing-grid__item"):
        fields = [f for f in _fields(item) if f]
        link = item.select_one("a[href$='.pdf']")
        when = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", fields[0]) if fields else None
        if link and when and len(fields) > 1 and fields[1].lower().startswith("convocatoria"):
            found.append((_iso(*when.groups()), link["href"]))
    return min(found)[1] if found else None


def hour_for(text: str, deadline: str) -> str | None:
    """Hora de cierre si el texto la da para el mismo día y mes del listado."""
    day = date.fromisoformat(deadline)
    for d, month, year, hour in HOUR.findall(text):
        when = spanish_date(d, month, year or str(day.year))
        if when and (when.month, when.day) == (day.month, day.day) and (not year or when.year == day.year):
            return clock(hour)
    return None


class MayasaSource(Source):
    id = "mayasa"
    name = "Mayasa"
    homepage = PAGE
    apply_label = "Ver las bases y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._places: dict[str, str | None] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_page(http.get(PAGE)):
            if deadline_passed(row["deadline"], None, now):
                continue
            pdf = convocatoria(http.get(row["url"]))
            hour = hour_for(read_pdf(http, pdf, f"Mayasa, convocatoria de {row['title']}"), row["deadline"]) if pdf else None
            if deadline_passed(row["deadline"], hour, now):
                continue
            self._places[row["ref"]] = row["place"]
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                kind=None, contract=row["contract"], published_on=row["published_on"],
                deadline=row["deadline"], deadline_time=hour,
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(location=self._places.get(offer.ref))
