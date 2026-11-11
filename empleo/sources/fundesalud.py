"""FUNDESALUD (Fundación para la Formación y la Investigación de los Profesionales de la Salud
de Extremadura).

WordPress con Elementor. `/ofertas-de-empleo/` reparte las convocatorias en tres pestañas («En
fase de inscripción», «En proceso», «Cerrados»), todas en la misma página: una tarjeta
(`.e-loop-item`) por convocatoria con referencia, puesto, «Inicia», «Finaliza» (sin hora) y
«Nº plazas». La pestaña puede ir desfasada respecto a las fechas: mandan las fechas. La
referencia no sigue ningún formato («Ref. 22/2026», «Ref:18/2025», «REF. P26-03», «PMP25/2026»):
se muestra tal cual y la clave es el identificador de la entrada (`post-13387`).

Es oferta la tarjeta cuyo fin no ha pasado; si aún no ha empezado, se guarda el inicio. Los plazos
son muy cortos (dos o tres días). La ficha no se lee: junto a las bases enlaza listas de
admitidos y de puntuaciones.
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from .base import Source

PAGE = "https://fundesalud.es/ofertas-de-empleo/"
COMPANY = "FUNDESALUD"
POST = re.compile(r"post-(\d+)")
STARTS = re.compile(r"Inicia:\s*(\d\d/\d\d/\d{4})")
ENDS = re.compile(r"Finaliza:\s*(\d\d/\d\d/\d{4})")
SEATS = re.compile(r"Nº plazas:\s*(\d+)")


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def parse_page(html: str) -> list[dict]:
    items = BeautifulSoup(html, "html.parser").select(".e-loop-item")
    if not items:
        raise SourceLayoutError("FUNDESALUD: no se encuentran las convocatorias")
    found = []
    for item in items:
        text = _text(item)
        if not text:
            # Entrada publicada sin rellenar (pasó con la 23/2026): se salta hasta que tenga datos.
            print(f"AVISO fundesalud: tarjeta vacía, se salta: {item.get('class')}", file=sys.stderr)
            continue
        post =next((m.group(1) for c in item.get("class", []) if (m := POST.fullmatch(c))), None)
        starts, ends = STARTS.search(text), ENDS.search(text)
        label, title, link = item.select_one("p.elementor-heading-title"), item.find("h6"), item.find("a", href=True)
        if not (post and ends and title and link):
            raise SourceLayoutError(f"FUNDESALUD: convocatoria sin identificador, puesto, fin o enlace: {text[:80]}")
        seats = SEATS.search(text)
        reference = _text(label) if label and not STARTS.search(_text(label)) else ""
        found.append({
            "ref": post, "title": _text(title), "code": reference or None, "url": link["href"],
            "opens_on": numeric_date(starts.group(1)) if starts else None,
            "deadline": numeric_date(ends.group(1)),
            "positions": int(seats.group(1)) if seats else None,
        })
    if not found:
        raise SourceLayoutError("FUNDESALUD: todas las convocatorias están vacías")
    return found


class FundesaludSource(Source):
    id = "fundesalud"
    name = COMPANY
    homepage = PAGE
    scope = "Extremadura"
    apply_label = "Ver la convocatoria y cómo inscribirse"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(
                ref=e["ref"], title=e["title"], code=e["code"], company=COMPANY, url=e["url"],
                apply_url=e["url"], kind=None, positions=e["positions"], opens_on=e["opens_on"],
                deadline=e["deadline"],
            )
            for e in parse_page(http.get(PAGE)) if not deadline_passed(e["deadline"], None, now)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(location="Extremadura")
