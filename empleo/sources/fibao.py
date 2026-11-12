"""FIBAO (Fundación para la Investigación Biosanitaria de Andalucía Oriental).

`/ofertas/todas/?estado=Abierta` lista las convocatorias que el portal da por abiertas, veinte por
página (con más, enlaza `?page=2`; la fuente se detiene en vez de leer solo la primera). Cada una es
un `article` con la fecha de publicación, si tiene resolución y el título con su número delante
(«90/2026.- Técnico/a Investigación…»), enlazado a `/ofertas/ficha/N/`. El plazo solo está en la
ficha: «Fecha fin de presentación de solicitudes: DD/MM/AAAA», sin hora. Publica unas 90 al año, con
plazos de una o dos semanas.

Es oferta la ficha con el fin del plazo sin vencer. No son empleo abierto y no se leen: las
convocatorias dirigidas a personal con vinculación laboral con las instituciones del instituto
(«con vinculación laboral a alguna de las instituciones») y las «Búsqueda de candidatos/as» para
presentarse con FIBAO a una ayuda (PTA y similares), que no llevan número. De los documentos de la
ficha se enlazan las bases, no las resoluciones ni las listas.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import spanish_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.fibao.es"
PAGE = SITE + "/ofertas/todas/?estado=Abierta"
HOMEPAGE = SITE + "/ofertas/todas/"
INTERNAL = re.compile(r"con\s+vinculación\s+laboral\s+a\s+alguna\s+de\s+las\s+instituciones", re.I)
GRANT_SEARCH = re.compile(r"Búsqueda\s+(?:de\s+)?candidat", re.I)
LISTS = re.compile(r"resoluci|lista|admitid|exclui|baremo|provisional|definitiv|tribunal", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("a[href*='page=']"):
        raise SourceLayoutError("FIBAO: más de una página de convocatorias abiertas")
    found = []
    for article in soup.select("article.article_item"):
        link, heading = article.find("a", href=re.compile(r"^/ofertas/ficha/\d+/$")), article.find("h3")
        if link is None or heading is None:
            raise SourceLayoutError("FIBAO: convocatoria sin enlace o sin título")
        published = re.search(r"(\d{1,2}) de (\w+) de (\d{4})", _clean(article.get_text(" ")))
        day = spanish_date(*published.groups()) if published else None
        found.append({
            "ref": link["href"].strip("/").rsplit("/", 1)[1], "url": urljoin(SITE, link["href"]),
            "title": _clean(heading.get_text(" ")), "published_on": day.isoformat() if day else None,
        })
    if not found and "ofertas de empleo" not in soup.get_text().lower():
        raise SourceLayoutError("FIBAO: la página no es la lista de ofertas")
    return found


def parse_ficha(html: str) -> dict:
    content = BeautifulSoup(html, "html.parser").select_one("article.article_oferta div.article_content_text")
    if content is None:
        raise SourceLayoutError("FIBAO: ficha sin convocatoria")
    text = _clean(content.get_text(" "))
    end = re.search(r"Fecha fin de presentación de solicitudes:\s*(\d{2})/(\d{2})/(\d{4})", text)
    deadline = date(int(end.group(3)), int(end.group(2)), int(end.group(1))).isoformat() if end else None
    paragraphs = []
    for p in content.find_all("p", recursive=False):
        line = _clean(p.get_text(" "))
        if line.startswith(("Estado:", "Fecha fin de presentación")) or p.find("a"):
            continue
        paragraphs.append(str(p))
    sections = [{"title": "Convocatoria", "level": 2, "html": sanitize("".join(paragraphs))}] if paragraphs else []
    documents = []
    for row in content.select("table tr"):
        cells, link = row.find_all("td"), row.find("a", href=True)
        if len(cells) < 2 or link is None or LISTS.search(cells[0].get_text()):
            continue
        documents.append(f'<li><a href="{escape(urljoin(SITE, link["href"]), quote=True)}">{escape(_clean(cells[0].get_text(" ")))}</a></li>')
    if documents:
        sections.append({"title": "Documentación", "level": 2, "html": sanitize(f"<ul>{''.join(documents)}</ul>")})
    return {"deadline": deadline, "internal": bool(INTERNAL.search(text)), "sections": sections}


class FibaoSource(Source):
    id = "fibao"
    name = "FIBAO (Fundación para la Investigación Biosanitaria de Andalucía Oriental)"
    homepage = HOMEPAGE
    scope = "Andalucía"
    apply_label = "Ver la convocatoria y cómo inscribirse"
    title_code = re.compile(r"(?P<code>\d+/\d{4})\.-\s*(?P<title>.+)")

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._sections: dict[str, list[dict]] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_list(http.get(PAGE)):
            if GRANT_SEARCH.match(row["title"]):
                continue
            ficha = parse_ficha(http.get(row["url"]))
            if ficha["internal"] or not ficha["deadline"] or deadline_passed(ficha["deadline"], None, now):
                continue
            self._sections[row["ref"]] = ficha["sections"]
            offers.append(ListedOffer(
                ref=row["ref"], **self.labels(row["title"], row["ref"]), company="FIBAO",
                url=row["url"], apply_url=row["url"], kind=None, deadline=ficha["deadline"],
                published_on=row["published_on"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        sections = self._sections.get(offer.ref)
        if sections is None:
            sections = parse_ficha(http.get(offer.url))["sections"]
        return OfferDetail(sections=sections)
