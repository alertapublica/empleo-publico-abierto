"""VEIASA (Verificaciones Industriales de Andalucía).

`Selección de personal` (Liferay) separa «Procesos abiertos» y «Procesos cerrados», cada uno con
enlaces a una página por convocatoria (`/w/…`). La lista de abiertos mezcla convocatorias ya
vencidas, bolsas («…B04I: LISTA DE CANDIDATOS/AS EN RESERVA…», que sí son convocatorias) y llamamientos al personal fijo
discontinuo (internos, no son ofertas): mandan las fechas.

El plazo va en el texto de cada convocatoria, redactado a mano y de muchas formas: «el plazo
permanecerá abierto desde el 21 de octubre hasta el 11 de noviembre de 2026, a las 23:59 horas»,
«finalizará a las 23:59 horas del día 2 de mayo de 2025», «hasta el DOMINGO 3 DE MAYO DE 2026 A LAS
23:59 HORAS». Se buscan las frases que hablan del plazo y dicen «hasta» o «finaliza», y vale la fecha
mayor. Es oferta la convocatoria con ese plazo sin vencer. Una petición por enlace de «abiertos»
(hoy, 6). Sin procesos: los documentos de las convocatorias no llevan fecha.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import MONTHS, clock, latest, spanish_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.veiasa.es"
PAGE = SITE + "/es/la-empresa/selecci%C3%B3n-de-personal"
COMPANY = "VEIASA"
NOT_OFFERS = re.compile(r"llamamiento", re.I)  # al personal fijo discontinuo: interno
# Una frase: hasta el punto final, pero no el de una hora («13.00 horas»).
_SENTENCE = r"(?:[^.]|(?<=\d)\.(?=\d))"
CLAUSE = re.compile(r"plazo" + _SENTENCE + r"{0,300}?(?:hasta|finaliz)" + _SENTENCE + r"{0,200}", re.I)
OTHER_PHASES = re.compile(r"alegaci|reclamaci|subsanaci|recurso", re.I)
WHEN = re.compile(r"(?:a\s+las\s+(\d{1,2}[:.]\d{2})\s*horas?\s+del?\s+(?:d[ií]a\s+)?)?(?:[a-záéíóú]+\s+)?(\d{1,2}) de ("
                  + "|".join(MONTHS) + r") de (\d{4})(?:,?\s*a\s+las\s+(\d{1,2}[:.]\d{2}))?", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    opened = soup.find(string=re.compile(r"Procesos abiertos"))
    closed = soup.find(string=re.compile(r"Procesos cerrados"))
    if opened is None or closed is None:
        raise SourceLayoutError("VEIASA: no se encuentran las listas de procesos abiertos y cerrados")
    stop = set(id(a) for a in closed.find_all_next("a"))
    found = []
    for link in opened.find_all_next("a", href=True):
        if id(link) in stop:
            break
        if "/w/" not in link["href"]:
            continue
        title = _clean(link.get_text(" ")).removeprefix("¡NUEVO!").strip()
        url = urljoin(SITE, link["href"].split("?")[0])
        found.append({"title": title, "url": url, "ref": url.rstrip("/").rsplit("/", 1)[-1]})
    return found


def deadline_of(text: str) -> tuple:
    """Último día (y hora) de las frases del plazo que dicen «hasta» o «finaliza»."""
    found = []
    for clause in CLAUSE.findall(_clean(text)):
        if OTHER_PHASES.search(clause):
            continue
        for before, day, month, year, after in WHEN.findall(clause):
            when = spanish_date(day, month, year)
            if when:
                found.append((when, clock(before or after)))
    return latest(found)


def parse_detail(html: str) -> dict:
    article = BeautifulSoup(html, "html.parser").select_one(".journal-content-article")
    if article is None:
        raise SourceLayoutError("VEIASA: convocatoria sin contenido")
    day, hour = deadline_of(article.get_text(" "))
    return {"deadline": day.isoformat() if day else None, "deadline_time": hour,
            "html": sanitize(article.decode_contents())}


class VeiasaSource(Source):
    id = "veiasa"
    name = "VEIASA (Verificaciones Industriales de Andalucía)"
    homepage = PAGE
    scope = "Andalucía"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._details: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_page(http.get(PAGE)):
            if NOT_OFFERS.search(row["title"]):
                continue
            detail = parse_detail(http.get(row["url"]))
            if detail["deadline"] is None or deadline_passed(detail["deadline"], detail["deadline_time"], now):
                continue
            self._details[row["ref"]] = detail
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"], kind=None,
                deadline=detail["deadline"], deadline_time=detail["deadline_time"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        detail = self._details.get(offer.ref) or parse_detail(http.get(offer.url))
        return OfferDetail(sections=[{"title": "La convocatoria", "level": 2, "html": detail["html"]}])
