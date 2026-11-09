"""IMIB (Instituto Murciano de Investigación Biosanitaria), gestionado por la FFIS.

JSF (PrimeFaces) en `rrhh.ffis.es`. Por GET, la portada da 10 filas sin orden de fecha: código
(`IMIB26_C77BIS`), «DD/MM/AAAA-DD/MM/AAAA» (inicio y fin), estado, ubicación y fecha de la
convocatoria. El filtro «Abiertas» y las demás páginas piden enviar el formulario: no se usan. Las
10 filas son las de id más alto (los huecos de id no existen). Si incluso la de inicio más antiguo
sigue en plazo, puede haber abiertas fuera de la vista y la fuente se detiene.

La ficha nueva (`ofertaEmpleoNew.jsf`) no da la hora de cierre; la antigua (`ofertaEmpleo.jsf`,
mismo id) sí: «Desde el 03/11/2026 hasta las 10:00 del 09/11/2026». La hora varía (10:00, 13:00),
así que se lee la antigua de cada fila que siga en plazo. Vale el día mayor; la hora, solo si es de
ese día. Clave: código. Contrato sin indicar.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

from ..dates import latest
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from .base import Source

SITE = "https://rrhh.ffis.es"
PAGE = f"{SITE}/"
OLD = f"{SITE}/rrhh/ofertaEmpleo.jsf?id="
DMY = r"(\d{2})/(\d{2})/(\d{4})"


def _iso(day: str, month: str, year: str) -> str:
    return f"{year}-{month}-{day}"


def parse_page(html: str) -> list[dict]:
    rows = BeautifulSoup(html, "html.parser").select("tr[data-ri]")
    if not rows:
        raise SourceLayoutError("IMIB: no se encuentra la tabla de ofertas")
    found = []
    for row in rows:
        title, link = row.select_one("h3"), row.select_one("a[href*='id=']")
        items = [" ".join(li.get_text().split()) for li in row.select("ul li")]
        dates = re.fullmatch(rf"{DMY}-{DMY}", items[1]) if len(items) > 1 else None
        if title is None or link is None or dates is None:
            raise SourceLayoutError("IMIB: fila sin título, enlace o plazo")
        text = " ".join(row.get_text(" ").split())
        published = re.search(rf"Convocatoria \({DMY}\)", text)
        found.append({
            "ref": items[0], "title": " ".join(title.get_text().split()),
            "id": link["href"].rsplit("id=", 1)[-1], "url": SITE + link["href"],
            "opens_on": _iso(*dates.groups()[:3]), "deadline": _iso(*dates.groups()[3:]),
            "published_on": _iso(*published.groups()) if published else None,
        })
    return found


def parse_hour(html: str, deadline: str) -> tuple[str, str | None]:
    """Último día y hora: la ficha antigua puede traer la hora o una fecha mayor."""
    text = " ".join(BeautifulSoup(html, "html.parser").get_text(" ").split())
    mentions = [(date.fromisoformat(deadline), None)]
    found = re.search(rf"hasta las (\d{{1,2}}):(\d{{2}}) del {DMY}", text)
    if found:
        hour, minute, day, month, year = found.groups()
        mentions.append((date(int(year), int(month), int(day)), f"{int(hour):02d}:{minute}"))
    day, hour = latest(mentions)
    return day.isoformat(), hour


class ImibSource(Source):
    id = "imib"
    name = "IMIB (FFIS)"
    homepage = PAGE
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    scope = "Región de Murcia"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        rows = parse_page(http.get(PAGE))
        oldest = min(rows, key=lambda r: r["opens_on"])
        if not deadline_passed(oldest["deadline"], None, now):
            raise SourceLayoutError("IMIB: la fila más antigua sigue en plazo; puede haber más fuera de la vista")
        offers = []
        for row in rows:
            if deadline_passed(row["deadline"], None, now):
                continue
            deadline, hour = parse_hour(http.get(OLD + row["id"]), row["deadline"])
            if deadline_passed(deadline, hour, now):
                continue
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company="FFIS", url=row["url"], apply_url=row["url"],
                kind=None, opens_on=row["opens_on"], deadline=deadline, deadline_time=hour,
                published_on=row["published_on"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(location="Murcia")
