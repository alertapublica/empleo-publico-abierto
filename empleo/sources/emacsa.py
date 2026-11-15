"""EMACSA (Empresa Municipal de Aguas de Córdoba).

`cuestionarios.emacsa.es` (ASP.NET; `ofertasempleo.emacsa.es` sirve lo mismo; sin `robots.txt`) tiene
en la portada una tarjeta por convocatoria, también las cerradas (5 el 2026-11-15): puesto, «Proceso
selectivo para la cobertura de 3 plazas de …» y «Plazo de inscripción abierto/cerrado» con el periodo
sin año ni hora («04 de noviembre - 30 de noviembre»). Las cerradas no enlazan nada: el número de cada
convocatoria sale del menú del pie («Información y Bases de la Convocatoria», `/convocatoria/N`).

La ficha es una lista de apartados con «Publicado el 30/07/2026» («Convocatoria y bases», «Lista
provisional de personas admitidas y excluidas», «Celebración del ejercicio…»), cada uno con sus
documentos y a veces un texto. El año del plazo sale del primer apartado publicado: el de la
publicación (el siguiente si el inicio quedara más de 30 días antes) y, para el fin, el del inicio (el
siguiente si el fin cae antes).

Se leen todas las fichas de la portada. Es oferta la que tiene el plazo sin vencer (manda la fecha,
no «abierto»); las demás son procesos, y sus comunicados son los apartados, con su fecha y enlace a la
ficha: entre los documentos hay listas de personas, que no se enlazan.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://cuestionarios.emacsa.es"
PAGE = SITE + "/Index"
COMPANY = "EMACSA"
MONTHS = {m: i for i, m in enumerate(
    "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split(), 1)}
PERIOD = re.compile(r"(\d{1,2}) de (\w+)\s*-\s*(\d{1,2}) de (\w+)")
POSITIONS = re.compile(r"cobertura de (\d+) plazas?\b", re.I)
PUBLISHED = re.compile(r"Publicado el (\d{2})/(\d{2})/(\d{4})")
NUMBER = re.compile(r"/(?:convocatoria|inscripciones)/(\d+)$")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _month(name: str) -> int:
    if name.lower() not in MONTHS:
        raise SourceLayoutError(f"EMACSA: mes desconocido en el plazo: «{name}»")
    return MONTHS[name.lower()]


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    menu = {}
    for link in soup.select("footer a[href]"):
        number = NUMBER.search(link["href"])
        if number:
            menu[_clean(link.get_text(" "))] = number.group(1)
    found = []
    for card in soup.select(".icon-block"):
        title_tag, texts = card.find("h5"), [_clean(p.get_text(" ")) for p in card.find_all("p")]
        period = next((PERIOD.search(t) for t in texts if "Plazo de inscripci" in t and PERIOD.search(t)), None)
        if title_tag is None or period is None:
            raise SourceLayoutError("EMACSA: tarjeta sin puesto o sin plazo de inscripción")
        title = _clean(title_tag.get_text(" "))
        apply = card.find("a", href=NUMBER)
        number = menu.get(title) or (NUMBER.search(apply["href"]).group(1) if apply else None)
        if number is None:
            raise SourceLayoutError(f"EMACSA: convocatoria sin ficha en el menú: «{title}»")
        d1, m1, d2, m2 = period.groups()
        found.append({
            "ref": number, "title": title, "url": f"{SITE}/convocatoria/{number}",
            "apply_url": urljoin(SITE, apply["href"]) if apply else None,
            "summary": next((t for t in texts if t.startswith("Proceso selectivo")), ""),
            "period": _clean(period.group(0)), "start": (int(d1), _month(m1)), "end": (int(d2), _month(m2)),
        })
    if not found:
        raise SourceLayoutError("EMACSA: la portada no tiene convocatorias")
    return found


def parse_detail(html: str) -> list[dict]:
    """Apartados de la ficha: título, fecha, documentos y texto."""
    soup = BeautifulSoup(html, "html.parser")
    sections: list[dict] = []
    for block in soup.select(".convocatoria .col.s12"):
        published = PUBLISHED.search(block.get_text(" "))
        heading = block.find("h5")
        if heading and published:
            day, month, year = published.groups()
            sections.append({"title": _clean(heading.get_text(" ")), "date": f"{year}-{month}-{day}",
                             "documents": [], "text": ""})
        elif sections:
            for link in block.select("a[href*='DescargarDoc']"):
                sections[-1]["documents"].append({"label": _clean(link.get_text(" ")), "url": urljoin(SITE, link["href"])})
            if "offset-top" in block.get("class", []) and block.find("p"):
                sections[-1]["text"] += "".join(str(p) for p in block.find_all("p"))
    if not sections:
        raise SourceLayoutError("EMACSA: ficha sin apartados fechados")
    return sections


def dates(row: dict, published: str) -> tuple[str, str]:
    """Inicio y fin del plazo, con el año que da la publicación de la convocatoria."""
    first = date.fromisoformat(published)
    start = date(first.year, row["start"][1], row["start"][0])
    if start < first - timedelta(days=30):
        start = date(first.year + 1, *reversed(row["start"]))
    end = date(start.year, row["end"][1], row["end"][0])
    if end < start:
        end = date(start.year + 1, *reversed(row["end"]))
    return start.isoformat(), end.isoformat()


class EmacsaSource(Source):
    id = "emacsa"
    name = "EMACSA (Aguas de Córdoba)"
    homepage = PAGE
    scope = "Andalucía"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._rows: list[tuple[dict, list[dict]]] | None = None

    def _read(self, http: Client) -> list[tuple[dict, list[dict]]]:
        if self._rows is None:
            self._rows = []
            for row in parse_page(http.get(PAGE)):
                sections = parse_detail(http.get(row["url"]))
                row["opens_on"], row["deadline"] = dates(row, min(s["date"] for s in sections))
                self._rows.append((row, sections))
        return self._rows

    def _is_offer(self, row: dict) -> bool:
        return not deadline_passed(row["deadline"], None, self._now or datetime.now(timezone.utc))

    def list_offers(self, http: Client) -> list[ListedOffer]:
        offers = []
        for row, sections in self._read(http):
            if not self._is_offer(row):
                continue
            seats = POSITIONS.search(row["summary"])
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"],
                apply_url=row["apply_url"] or row["url"], kind=None,
                positions=int(seats.group(1)) if seats else None, deadline=row["deadline"],
                opens_on=row["opens_on"], published_on=min(s["date"] for s in sections),
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        found = next(((r, s) for r, s in self._read(http) if r["ref"] == offer.ref), None)
        if found is None:
            return OfferDetail(location="Córdoba")
        row, sections = found
        parts = [{"title": "Plazo de inscripción", "level": 2, "html": sanitize(f"<p>{escape(row['period'])}</p>")}]
        if row["summary"]:
            parts.append({"title": "La convocatoria", "level": 2, "html": sanitize(f"<p>{escape(row['summary'])}</p>")})
        for section in sections:
            items = "".join(f'<li><a href="{escape(d["url"], quote=True)}">{escape(d["label"])}</a></li>'
                            for d in section["documents"])
            body = (f"<ul>{items}</ul>" if items else "") + section["text"]
            if body:
                parts.append({"title": section["title"], "level": 2, "html": sanitize(body)})
        return OfferDetail(location="Córdoba", sections=parts)

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Los apartados de las convocatorias con la inscripción cerrada, con su fecha."""
        return [
            Announcement(date=s["date"], process=row["title"], title=s["title"], url=row["url"], process_url=row["url"])
            for row, sections in self._read(http) if not self._is_offer(row)
            for s in sections
        ]
