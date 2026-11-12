"""IiSGM (Instituto de Investigación Sanitaria Gregorio Marañón): «Ofertas de empleo».

Contrata la Fundación para la Investigación Biomédica del Hospital Gregorio Marañón (FIBHGM). El
listado (`iisgm.com/ofertas-de-empleo/`, `/page/N`) tiene 12 tarjetas por página, de la más nueva
a la más antigua: título, «Ref.», estado («Abierta», «En proceso», «Cerrada», «Adjudicada») y
«Plazo» con inicio y fin en `<time datetime>` (sin hora). El estado no se usa: mandan las fechas.
El orden no sigue el cierre (en la página 3 del 2026-11-12, la 102 cierra en abril y la 101 en
julio): se leen todas las páginas que enlaza la paginación (4, unos seis meses), hasta `MAX_PAGES`.

Las becas («BECA UNIDAD TÉCNICA…»; también «OFERTA DE BECA…», por si acaso) salen en la misma lista y no se publican. La
ficha (`/ofertas-de-empleo/<id>/<slug>`) trae los datos del puesto (grupo de investigación,
categoría, titulación), los requisitos con la forma de presentarse (por correo) y «Documentos
relacionados» (la oferta en PDF). El título se copia tal cual, con su referencia: la «Ref.» de la
tarjeta tiene erratas («Re.103_2023» para la 103_2026). Sondeo del 2026-11-12, a partir del
informe de Codex (encargo 8).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://iisgm.com"
PAGE = SITE + "/ofertas-de-empleo/"
MAX_PAGES = 6
DETAIL = re.compile(r"^/ofertas-de-empleo/(\d+)/[\w-]+$")
DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
GRANT = re.compile(r"^\s*(?:OFERTA\s+DE\s+)?BECAS?\b", re.I)
PAGES = re.compile(r"/ofertas-de-empleo/page/(\d+)")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select("h2 a[href^='/ofertas-de-empleo/']")
    if not links:
        raise SourceLayoutError("IiSGM: no se encuentran las ofertas")
    found = []
    for link in links:
        card = link.find_parent("div", class_="columns")
        days = [t.get("datetime", "") for t in card.find_all("time")] if card else []
        ref = DETAIL.match(link["href"])
        if ref is None or len(days) != 2 or not all(DAY.fullmatch(d) for d in days):
            raise SourceLayoutError(f"IiSGM: tarjeta sin enlace a la ficha o sin plazo: {_clean(link.get_text(' '))!r}")
        found.append({"ref": ref.group(1), "url": urljoin(SITE, link["href"]), "title": _clean(link.get_text(" ")),
                      "opens_on": days[0], "deadline": days[1]})
    return found


def parse_detail(html: str) -> OfferDetail:
    soup = BeautifulSoup(html, "html.parser")
    panel = soup.select_one(".panel--view")
    data = panel.select_one("p.text-18") if panel else None
    if data is None:
        raise SourceLayoutError("IiSGM: ficha sin los datos del puesto")
    sections = [{"title": "Datos del puesto", "level": 2, "html": sanitize(data.decode_contents())}]
    heading = next((h for h in panel.find_all("h2") if _clean(h.get_text(" ")) == "Requisitos"), None)
    body = heading.find_next_sibling("div") if heading else None
    if body is None or not _clean(body.get_text(" ")):
        raise SourceLayoutError("IiSGM: ficha sin «Requisitos»")
    sections.append({"title": "Requisitos", "level": 2, "html": sanitize(body.decode_contents())})
    documents = []
    for link in panel.select("ul.related-docs a[href]"):
        size = link.find("span")
        if size:
            size.extract()
        label = _clean(link.get_text(" "))
        if label:
            url = quote(urljoin(SITE, link["href"]), safe=":/?=&%#")  # los PDF llevan espacios en el nombre
            documents.append(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>')
    if not documents:  # la oferta completa va en ese PDF
        raise SourceLayoutError("IiSGM: ficha sin «Documentos relacionados»")
    sections.append({"title": "Documentos relacionados", "level": 2, "html": sanitize(f"<ul>{''.join(documents)}</ul>")})
    return OfferDetail(sections=sections, location="Madrid")


class IisgmSource(Source):
    id = "iisgm"
    name = "IiSGM (Instituto de Investigación Sanitaria Gregorio Marañón)"
    homepage = PAGE
    scope = "Comunidad de Madrid"
    apply_label = "Ver la oferta y cómo presentarse"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def _rows(self, http: Client) -> list[dict]:
        html = http.get(PAGE)
        rows = parse_list(html)
        last = max((int(n) for n in PAGES.findall(html)), default=1)
        if last > MAX_PAGES:
            raise SourceLayoutError(f"IiSGM: {last} páginas de ofertas, más de {MAX_PAGES}")
        for page in range(2, last + 1):
            rows += parse_list(http.get(f"{PAGE}page/{page}"))
        return rows

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(ref=row["ref"], title=row["title"], company=self.name, url=row["url"], apply_url=row["url"],
                        kind=None, opens_on=row["opens_on"], deadline=row["deadline"])
            for row in self._rows(http)
            if not deadline_passed(row["deadline"], None, now) and not GRANT.search(row["title"])
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return parse_detail(http.get(offer.url))
