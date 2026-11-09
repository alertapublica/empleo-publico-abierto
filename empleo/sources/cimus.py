"""CiMUS (Centro Singular de Investigación en Medicina Molecular e Enfermidades Crónicas, USC).

Centro de la Universidade de Santiago de Compostela, no fundación. Drupal: `/es/empleo` es una
tabla sin fechas con todas las convocatorias desde 2024 (62 filas, sin paginación), en orden de
número. El plazo está en cada ficha: un campo estructurado con el último día (`field-deadline-job`,
sin hora: el `datetime` lleva 12:00Z) y, en el texto, «Apertura recepción de candidaturas:
DD/MM/AAAA» y «Fecha fin candidaturas: DD/MM/AAAA 23:59». «Fecha fin enmiendas» es la subsanación
de solicitudes y no se usa.

Solo se leen las `FICHAS` primeras filas: salen 2 o 3 convocatorias al mes y el plazo dura de 4 a
15 días. Vale el día mayor entre el campo y el texto; la hora, solo si el texto da ese mismo día.
Es oferta la ficha con plazo cuyo fin no ha pasado. Clave: id del nodo. El puesto
(«Investigador/a Colaborador/a») no es un tipo de contrato: el contrato queda sin indicar. Solo se
enlaza la ficha: los documentos incluyen listas de admitidos.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

from ..dates import clock, latest
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from .base import Source

SITE = "https://cimus.usc.gal"
PAGE = f"{SITE}/es/empleo"
FICHAS = 5
DMY = r"(\d{2})/(\d{2})/(\d{4})"


def _day(found: re.Match) -> date:
    day, month, year = found.groups()[:3]
    return date(int(year), int(month), int(day))


def parse_list(html: str) -> list[dict]:
    rows = BeautifulSoup(html, "html.parser").select("main table tbody tr")
    if not rows:
        raise SourceLayoutError("CiMUS: no se encuentra la tabla de convocatorias")
    found = []
    for row in rows:
        link = row.select_one(".tit-Job a[href]")
        if link is None:
            raise SourceLayoutError("CiMUS: fila sin título")
        found.append({"title": " ".join(link.get_text().split()), "url": SITE + link["href"]})
    return found


def parse_ficha(html: str) -> dict:
    article = BeautifulSoup(html, "html.parser").select_one("article.node--type-job[data-history-node-id]")
    if article is None:
        raise SourceLayoutError("CiMUS: ficha sin convocatoria")
    body = article.select_one(".field--name-field-offer")
    text = " ".join(body.get_text(" ").split()) if body else ""
    field = article.select_one(".field--name-field-deadline-job time[datetime]")
    mentions = []
    if field is not None:
        mentions.append((date.fromisoformat(field["datetime"][:10]), None))
    end = re.search(rf"Fecha fin candidaturas:\s*{DMY}\s*([0-2]?\d[:.][0-5]\d)?", text)
    if end:
        mentions.append((_day(end), clock(end.group(4))))
    start = re.search(rf"Apertura recepción de candidaturas:\s*{DMY}", text)
    published = re.search(rf"Fecha de publicación:\s*{DMY}", text)
    deadline, hour = latest(mentions)
    return {
        "ref": article["data-history-node-id"],
        "deadline": deadline.isoformat() if deadline else None, "deadline_time": hour,
        "opens_on": _day(start).isoformat() if start else None,
        "published_on": _day(published).isoformat() if published else None,
    }


class CimusSource(Source):
    id = "cimus"
    name = "CiMUS (USC)"
    homepage = PAGE
    scope = "Galicia"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_list(http.get(PAGE))[:FICHAS]:
            e = parse_ficha(http.get(row["url"]))
            if not e["deadline"] or deadline_passed(e["deadline"], e["deadline_time"], now):
                continue
            offers.append(ListedOffer(
                ref=e["ref"], title=row["title"], company="Universidade de Santiago de Compostela",
                url=row["url"], apply_url=row["url"], kind=None, deadline=e["deadline"],
                deadline_time=e["deadline_time"], opens_on=e["opens_on"], published_on=e["published_on"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(location="Santiago de Compostela")
