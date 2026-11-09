"""Canal de Isabel II (Madrid): convocatorias públicas de empleo.

`convocatoriascanaldeisabelsegunda.es/puestos` es la misma aplicación que la de ISDEFE, con otra
tabla: fecha, código (`G00472026`), nombre, «Convocatoria» (`/convocatoria-N`), «Calendario»
(`/calendario-N`), estado («Cerrada inscripción») y una última columna («-»). Al revisarla
(2026-11-08) las 122 filas estaban cerradas: no se sabe qué dicen una abierta ni la última columna,
así que no se usan. El calendario trae la fase «Admisión de solicitudes» con inicio y fin, sin
hora; la fecha de la tabla coincide con el inicio.

Se leen los calendarios de las filas de los últimos 60 días (máx. 8; si hay más, la fuente se
detiene) y es oferta la que tiene la admisión en plazo. Las ofertas temporales (ePreselec, con reto
de Imperva) y la delegación de Cáceres (otra página) no se leen. Contrato sin indicar.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed, today_madrid
from .base import Source

HOST = "https://www.convocatoriascanaldeisabelsegunda.es"
PAGE = f"{HOST}/puestos"
COMPANY = "Canal de Isabel II"
CALL_ID = re.compile(r"/convocatoria-(\d+)$")
DATE = re.compile(r"\d\d/\d\d/\d{4}")
ADMISSION = re.compile(r"^admisi[oó]n de solicitudes", re.I)
MIN_ROWS = 20  # la tabla guarda el histórico
RECENT = 60
MAX_CALENDARS = 8


def _text(node) -> str:
    return " ".join(node.get_text(" ").split())


def parse_list(html: str) -> list[dict]:
    table = BeautifulSoup(html, "html.parser").find("table")
    rows = table.find_all("tr") if table else []
    if not rows or [_text(td) for td in rows[0].find_all("td")][:3] != ["FECHA", "CÓDIGO", "NOMBRE"]:
        raise SourceLayoutError("Canal: no se encuentra la tabla de puestos")
    if len(rows) - 1 < MIN_ROWS:
        raise SourceLayoutError(f"Canal: la tabla de puestos solo tiene {len(rows) - 1} filas")
    found = []
    for row in rows[1:]:
        cells = row.find_all("td")
        call = cells[3].find("a", href=CALL_ID) if len(cells) >= 5 else None
        if call is None or not DATE.fullmatch(_text(cells[0])) or cells[4].find("a", href=True) is None:
            raise SourceLayoutError("Canal: fila sin fecha, convocatoria o calendario")
        found.append({
            "ref": _text(cells[1]), "title": _text(cells[2]), "published_on": numeric_date(_text(cells[0])),
            "url": call["href"], "calendar": cells[4].find("a", href=True)["href"],
        })
    return found


def parse_calendar(html: str) -> tuple[str, str] | None:
    """Inicio y fin de la admisión de solicitudes, o None si el calendario no tiene esa fase."""
    for row in BeautifulSoup(html, "html.parser").select("table tr"):
        cells = [_text(td) for td in row.find_all("td")]
        if len(cells) >= 3 and ADMISSION.match(cells[0]) and DATE.fullmatch(cells[1]) and DATE.fullmatch(cells[2]):
            return numeric_date(cells[1]), numeric_date(cells[2])
    return None


class CanalSource(Source):
    id = "canal"
    name = "Canal de Isabel II"
    homepage = PAGE
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    scope = "Comunidad de Madrid"
    apply_label = "Ver las bases y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        since = (date.fromisoformat(today_madrid(now)) - timedelta(days=RECENT)).isoformat()
        recent = [row for row in parse_list(http.get(PAGE)) if row["published_on"] >= since]
        if len(recent) > MAX_CALENDARS:
            raise SourceLayoutError(f"Canal: {len(recent)} convocatorias en {RECENT} días; se esperaban como mucho {MAX_CALENDARS}")
        offers = []
        for row in recent:
            dates = parse_calendar(http.get(row["calendar"]))
            if dates is None or deadline_passed(dates[1], None, now):
                continue
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                kind=None, published_on=row["published_on"], opens_on=dates[0], deadline=dates[1],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail()
