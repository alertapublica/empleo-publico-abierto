"""ISDEFE (Ingeniería de Sistemas para la Defensa de España).

`seleccionisdefe.es/puestos` es una tabla con todas las convocatorias desde 2019 (unas 1.900
filas): fecha, nombre con el código del puesto, «Perfil del puesto» (`/convocatoria-N`),
«Calendario» (`/calendario-N`) y una columna que es el enlace «Inscribirse» (`/registro-N`) solo
mientras se admiten candidaturas. La última columna dice lo mismo en todas las filas y no se usa.

Solo se leen los calendarios de las filas con enlace de inscripción, y se ofrecen las que tienen
el hito de inscripción vigente según sus fechas. El perfil del puesto dice el contrato
(«SE OFRECE CONTRATO INDEFINIDO»).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from ..sanitize import sanitize
from .base import Source

HOST = "https://seleccionisdefe.es"
PAGE = f"{HOST}/puestos"
COMPANY = "ISDEFE"
CALL_ID = re.compile(r"/convocatoria-(\d+)$")
DATE = re.compile(r"\d\d/\d\d/\d{4}")
REGISTRATION = re.compile(r"^inscripci", re.I)
CONTRACT = re.compile(r"SE OFRECE (CONTRATO [A-ZÁÉÍÓÚÑ ]+?)\s*\.?$", re.I)
KIND = {"indefinido": "indefinido", "temporal": "temporal"}
MIN_ROWS = 20  # la tabla guarda el histórico (unas 1.900 filas): si encoge tanto, ha cambiado la página


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def parse_list(html: str) -> list[dict]:
    """Filas con enlace de inscripción, que son las únicas que pueden estar abiertas."""
    table = BeautifulSoup(html, "html.parser").find("table")
    headers = [_text(th) for th in table.find_all("th")] if table else []
    if headers[:2] != ["Fecha", "Nombre"]:
        raise SourceLayoutError("ISDEFE: no se encuentra la tabla de puestos")
    rows = table.select("tbody tr")
    if len(rows) < MIN_ROWS:
        raise SourceLayoutError(f"ISDEFE: la tabla de puestos solo tiene {len(rows)} filas")
    entries = []
    for row in rows:
        cells = row.find_all("td")
        profile = cells[2].find("a", href=CALL_ID) if len(cells) >= 5 else None
        if profile is None or not DATE.fullmatch(_text(cells[0])):
            raise SourceLayoutError("ISDEFE: fila sin fecha o sin perfil del puesto")
        registration = cells[4].find("a", href=True)
        if registration is None:
            continue
        call = CALL_ID.search(profile["href"]).group(1)
        entries.append({
            "ref": call,
            "title": _text(cells[1]),
            "published_on": numeric_date(_text(cells[0])),
            "url": f"{HOST}/convocatoria-{call}",
            "apply_url": registration["href"],
        })
    return entries


def parse_calendar(html: str) -> tuple[str, str] | None:
    """Primer y último día de inscripción, o None si el calendario no tiene ese hito."""
    for row in BeautifulSoup(html, "html.parser").select("table tbody tr"):
        cells = [_text(td) for td in row.find_all("td")]
        if len(cells) >= 3 and REGISTRATION.match(cells[0]) and DATE.fullmatch(cells[1]) and DATE.fullmatch(cells[2]):
            return numeric_date(cells[1]), numeric_date(cells[2])
    return None


def parse_profile(html: str) -> OfferDetail | None:
    soup = BeautifulSoup(html, "html.parser")
    title = soup.select_one("main h1.titulo")
    if title is None:
        return None
    body = "".join(str(node) for node in title.find_next_siblings())
    contract = next((m for p in title.find_next_siblings("p") if (m := CONTRACT.search(_text(p)))), None)
    literal = contract.group(1).capitalize() if contract else None
    kind = KIND.get(literal.split()[-1].lower()) if literal else None
    return OfferDetail(
        sections=[{"title": "Perfil del puesto", "level": 2, "html": sanitize(body)}],
        contract=literal, kind=kind,
    )


class IsdefeSource(Source):
    id = "isdefe"
    name = COMPANY
    homepage = PAGE
    # «Consultor/a SOC (2025-T00019)(7)»: no consta qué es el número final; va con el código.
    title_code = re.compile(r"(?P<title>.+?)\s*\((?P<code>\d{4}-T\d{5})\)\s*(?P<extra>\(\d+\)|\d+)?")

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = today_madrid(datetime.now(timezone.utc))
        offers = []
        for entry in parse_list(http.get(PAGE)):
            dates = parse_calendar(http.get(f"{HOST}/calendario-{entry['ref']}"))
            if dates is None or dates[1] < today:
                continue
            offers.append(ListedOffer(
                ref=entry["ref"], title=entry["title"], company=COMPANY, url=entry["url"],
                apply_url=entry["apply_url"], kind=None, published_on=entry["published_on"],
                opens_on=dates[0], deadline=dates[1],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return parse_profile(http.get(offer.url))
