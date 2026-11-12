"""CESGA (Centro de Supercomputación de Galicia): «Portal de Emprego».

Fundación pública de la Xunta y el CSIC. La portada (`emprego.cesga.es`, en gallego) tiene una
tabla con todas las convocatorias, también las cerradas (38 el 2026-11-12, 3 abiertas): referencia
(«HPQC-QEX-26-INV2 -TCC»), título, «Prazo» (solo el día), estado («Aberta», «En proceso»,
«Pechada») y plazas. El estado no se usa: mandan las fechas.

Es oferta la fila cuyo día de fin no ha pasado; de su ficha (`/oferta/<id>`) sale la hora
(«Límite de presentación: 13/11/2026 14:00»), la publicación («Data de publicación»), la
descripción y los documentos (bases, anexos, DOG). La descripción va en una variable de la página
con tres versiones (`galician`, `english`, `spanish`; la web enseña la gallega y cambia con
pestañas): se toma la castellana y, si está vacía, la gallega. El título solo está en gallego. Sin
fecha de inicio: las convocatorias se publican ya abiertas. La inscripción es un formulario de la
propia web («Aplicar Agora»). Sondeo del 2026-11-12, a partir del informe de Codex (encargo 8).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import clock, numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://emprego.cesga.es"
PAGE = SITE + "/"
HEADERS = ["Referencia", "Título", "Prazo", "Estado", "Prazas"]
DETAIL = re.compile(r"^/oferta/([0-9a-f]+)$")
DAY = re.compile(r"\d{2}/\d{2}/\d{4}")
MOMENT = re.compile(r"(\d{2}/\d{2}/\d{4})\s+(\d{1,2}:\d{2})")
# `spanish: `<h4>…</h4>`,` dentro de `const jobData = { description: {…} }`; una comilla invertida en
# el texto va escapada. Cada valor tiene que ser un literal entero (seguido de «,» o «}»): si la página
# pasara a concatenar o calcular el texto, no se encuentra la versión y la ficha se detiene.
JOB_DATA = re.compile(r"const jobData\s*=\s*\{\s*description:\s*\{")
VERSION = re.compile(r"\s*(galician|english|spanish):\s*`((?:[^`\\]|\\.)*)`\s*(?:,|(?=\}))", re.S)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    table = next((t for t in soup.find_all("table")
                  if [_clean(th.get_text(" ")) for th in t.select("thead th")][:5] == HEADERS), None)
    if table is None:
        raise SourceLayoutError("CESGA: no se encuentra la tabla de ofertas (o cambian sus columnas)")
    found = []
    for row in table.select("tbody tr"):
        cells = row.find_all("td")
        link = row.find("a", href=DETAIL)
        day = DAY.fullmatch(_clean(cells[2].get_text(" "))) if len(cells) >= 5 else None
        if link is None or day is None:
            raise SourceLayoutError("CESGA: fila sin enlace a la ficha o sin plazo")
        places = _clean(cells[4].get_text(" "))
        found.append({
            "ref": DETAIL.match(link["href"]).group(1), "url": urljoin(SITE, link["href"]),
            "code": _clean(cells[0].get_text(" ")) or None, "title": _clean(cells[1].get_text(" ")),
            "deadline": numeric_date(day.group(0)), "positions": int(places) if places.isdigit() else None,
        })
    if not found:
        raise SourceLayoutError("CESGA: la tabla de ofertas está vacía")
    return found


def _labelled(soup: BeautifulSoup, label: str) -> str | None:
    """Texto que sigue a «<strong>Límite de presentación:</strong>» en su mismo bloque."""
    strong = soup.find("strong", string=re.compile(rf"^\s*{label}:\s*$"))
    return _clean(strong.parent.get_text(" ")) if strong else None


def parse_ficha(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    deadline = MOMENT.search(_labelled(soup, "Límite de presentación") or "")
    if deadline is None:
        raise SourceLayoutError("CESGA: ficha sin «Límite de presentación» con día y hora")
    published = MOMENT.search(_labelled(soup, "Data de publicación") or "")
    start = JOB_DATA.search(html)
    versions, at = {}, start.end() if start else len(html)
    while found := VERSION.match(html, at):  # solo las claves seguidas, dentro de `description`
        versions[found.group(1)] = found.group(2).replace("\\`", "`")
        at = found.end()
    if "spanish" not in versions or "galician" not in versions:
        raise SourceLayoutError("CESGA: ficha sin las versiones de la descripción")
    sections = []
    if _clean(BeautifulSoup(versions["spanish"], "html.parser").get_text(" ")):
        sections.append({"title": "Descripción del puesto", "level": 2, "html": sanitize(versions["spanish"])})
    elif _clean(BeautifulSoup(versions["galician"], "html.parser").get_text(" ")):
        sections.append({"title": "Descripción del puesto", "level": 2, "html": sanitize(versions["galician"]),
                         "lang": "gl"})
    heading = next((h for h in soup.find_all("h4") if _clean(h.get_text(" ")) == "Documentación da convocatoria"), None)
    box = heading.find_next_sibling("div") if heading else None
    links = box.select("a[href]") if box else []
    documents = [f'<li><a href="{escape(urljoin(SITE, a["href"]), quote=True)}">{escape(_clean(a.get_text(" ")))}</a></li>'
                 for a in links if _clean(a.get_text(" "))]
    if documents:
        sections.append({"title": "Documentos de la convocatoria", "level": 2, "lang": "gl",
                         "html": sanitize(f"<ul>{''.join(documents)}</ul>")})
    return {
        "deadline": numeric_date(deadline.group(1)), "deadline_time": clock(deadline.group(2)),
        "published_on": numeric_date(published.group(1)) if published else None,
        "sections": sections,
    }


class CesgaSource(Source):
    id = "cesga"
    name = "CESGA (Centro de Supercomputación de Galicia)"
    homepage = PAGE
    scope = "Galicia"
    text_lang = "gl"  # el título; la descripción, en castellano si la hay
    apply_label = "Ver la convocatoria y presentar la candidatura"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_list(http.get(PAGE)):
            if deadline_passed(row["deadline"], None, now):
                continue
            ficha = parse_ficha(http.get(row["url"]))
            if deadline_passed(ficha["deadline"], ficha["deadline_time"], now):
                continue
            self._fichas[row["ref"]] = ficha
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=self.name, url=row["url"], apply_url=row["url"],
                kind=None, code=row["code"], positions=row["positions"], deadline=ficha["deadline"],
                deadline_time=ficha["deadline_time"], published_on=ficha["published_on"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        # Aquí y no en el listado: una ficha incompleta deja aviso y se relee, sin parar la fuente.
        titles = [section["title"] for section in ficha["sections"]]
        if titles != ["Descripción del puesto", "Documentos de la convocatoria"]:
            raise SourceLayoutError(f"CESGA: ficha sin descripción o sin documentos ({titles})")
        return OfferDetail(sections=ficha["sections"], location="Santiago de Compostela")
