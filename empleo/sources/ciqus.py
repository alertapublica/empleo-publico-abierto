"""CiQUS (Centro Singular de Investigación en Química Biolóxica e Materiais Moleculares, USC).

Centro de la Universidade de Santiago de Compostela, no fundación. Drupal: `/es/ofertas-de-empleo`
es una tabla con título (enlace a la ficha), plazo de presentación y estado. El plazo solo
aparece mientras está abierta o a punto de abrir, y con hora y zona en atributos
(`content="2026-11-13T23:59:00+01:00"`). El estado dice «Abierta» antes de que empiece el plazo:
no se usa.

Es oferta la fila con plazo cuyo fin no ha pasado; se guarda el inicio. Cada convocatoria agrupa
varias plazas: se ofrece como una sola, con su título literal. `robots.txt` pide 10 s entre
peticiones; solo se pide el listado.
"""
from __future__ import annotations

from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from .base import Source

SITE = "https://ciqus.usc.gal"
PAGE = f"{SITE}/es/ofertas-de-empleo"


def _moment(node) -> tuple[str, str]:
    """Día y hora en Madrid a partir del atributo ISO."""
    when = datetime.fromisoformat(node["content"]).astimezone(MADRID)
    return when.date().isoformat(), when.strftime("%H:%M")


def parse_page(html: str) -> list[dict]:
    table = BeautifulSoup(html, "html.parser").select_one("table.views-table")
    if table is None:
        raise SourceLayoutError("CiQUS: no se encuentra la tabla de convocatorias")
    found = []
    for row in table.select("tbody tr"):
        link = row.select_one("td.views-field-title-field a[href]")
        if link is None:
            raise SourceLayoutError("CiQUS: fila sin título")
        start, end = row.select_one(".date-display-start[content]"), row.select_one(".date-display-end[content]")
        if end is None:
            continue  # sin plazo publicado: cerrada o en trámite
        opens_on, _ = _moment(start) if start else (None, None)
        deadline, hour = _moment(end)
        found.append({
            "ref": link["href"].rstrip("/").rsplit("/", 1)[-1], "title": " ".join(link.get_text().split()),
            "url": SITE + link["href"], "opens_on": opens_on, "deadline": deadline, "deadline_time": hour,
        })
    return found


class CiqusSource(Source):
    id = "ciqus"
    name = "CiQUS (USC)"
    homepage = PAGE
    scope = "Galicia"
    delay = 10.0
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(
                ref=e["ref"], title=e["title"], company="Universidade de Santiago de Compostela", url=e["url"],
                apply_url=e["url"], kind=None, opens_on=e["opens_on"], deadline=e["deadline"],
                deadline_time=e["deadline_time"],
            )
            for e in parse_page(http.get(PAGE)) if not deadline_passed(e["deadline"], e["deadline_time"], now)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(location="Santiago de Compostela")
