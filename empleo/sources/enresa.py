"""Enresa.

Una página de WordPress con la lista completa de convocatorias, cada una en su estado:
«Procesos abiertos» (plazo de candidaturas en curso), en proceso (plazo cerrado, resolviendo) y
cerrados. Cada convocatoria trae título con su código (DO-DE-26-028), el plazo y los documentos.

Solo los abiertos son ofertas. Los que están en proceso se anuncian sin fecha, porque la página
no da ninguna, y los cerrados recientes, por su fecha de fin.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import FULL_DATE, spanish_date
from ..http import Client
from ..model import MADRID, Announcement, ListedOffer, OfferDetail, SourceLayoutError, selection_system
from ..sanitize import sanitize
from ..text import humane_caps
from .base import Source

PAGE = "https://www.enresa.es/esp/empleo"
COMPANY = "Enresa"
RECENT_DAYS = 180
CODE = re.compile(r"(DO-[A-Z]{2}-\d{2}-\d{3})")
PERIOD = re.compile(
    r"del\s+(\d{1,2})\s+de\s+([A-Za-záéíóú]+)\s+al\s+(\d{1,2})\s+de\s+([A-Za-záéíóú]+)\s+de\s+(\d{4})", re.I)
FINISHED = re.compile(r"Finalizado:\s*el\s+(\d{1,2}\s+de\s+[A-Za-záéíóú]+\s+de\s+\d{4})", re.I)
JOB = re.compile(
    r"PUESTOS?\s+DE\s+(?:TRABAJO\s+(?:DE\s+)?)*(.+?)\s*(?:MEDIANTE|EN LA EMPRESA|\(DO-|$)", re.I)
POSITIONS = re.compile(r"VACANTE\s+DE\s+(UN|UNA|DOS|TRES|CUATRO|CINCO|\d+)\s+PUESTOS?", re.I)
NUMBERS = {"un": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5}
CENTRE = re.compile(r"\b(?:C\.A\.|C\.T\.|I\.N\.|C\.N\.)\s+(?:DE\s+)?(.+)$")


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def _job(title: str) -> str:
    match = JOB.search(title)
    if not match:
        return title
    job = _clean(match.group(1))
    # «3 PUESTOS DE TRABAJO EN LA I.N. SANTA MARÍA DE GAROÑA»: solo dice dónde, no qué puesto.
    if re.match(r"(?:EN|DEL?)\s", job, re.I):
        return f"{_positions(title) or 'Varios'} puestos {job}"
    return job


def _positions(title: str) -> int | None:
    match = POSITIONS.search(title)
    if not match:
        return None
    word = match.group(1).lower()
    return int(word) if word.isdigit() else NUMBERS.get(word)


def _centre(job: str) -> str | None:
    match = CENTRE.search(job)
    return match.group(1).title().replace(" De ", " de ") if match else None


def _period(text: str) -> tuple[date, date] | None:
    match = PERIOD.search(text)
    if not match:
        return None
    first_day, first_month, last_day, last_month, year = match.groups()
    end = spanish_date(last_day, last_month, year)
    start = spanish_date(first_day, first_month, year)
    if end and start and start > end:  # «del 20 de diciembre al 10 de enero de 2027»
        start = spanish_date(first_day, first_month, int(year) - 1)
    return (start, end) if start and end else None


def _process_name(row: dict) -> str:
    name = humane_caps(row["job"])
    if row["centre"]:
        name = re.sub(re.escape(row["centre"]), row["centre"], name, flags=re.I)
    return f"{name} ({row['ref']})" if CODE.fullmatch(row["ref"]) else name  # si no, es una huella interna


def _main_document(row: dict) -> str:
    """La convocatoria propiamente dicha; los anexos y listados vienen después o antes, sin orden fijo."""
    for label, url in row["documents"]:
        if label.lower().startswith("convocatoria"):
            return url
    return row["documents"][0][1] if row["documents"] else PAGE


def parse_listing(html: str, page_url: str = PAGE) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#listado-empleo")
    if container is None:
        raise SourceLayoutError("Enresa: no se encuentra la lista de convocatorias")
    rows = []
    for section in container.select("section[estado]"):
        heading = section.select_one("h3")
        status = section.select_one(".div-subtitulo-2 span")
        if heading is None or status is None:
            raise SourceLayoutError("Enresa: convocatoria sin título o sin estado")
        title = _clean(heading.get_text(" "))
        period_node = section.select_one(".div-subtitulo-1")
        period_text = _clean(period_node.get_text(" ")) if period_node else ""
        job = _job(title)
        documents, seen = [], set()
        for anchor in section.select("a[href]"):
            url = urljoin(page_url, anchor["href"])
            if url not in seen:
                seen.add(url)
                documents.append((_clean(anchor.get_text(" ")) or "Documento", url))
        # El código figura en el título o, si no, en el nombre de los documentos (…DO-DE-26-048…).
        code = CODE.search(title) or next(filter(None, (CODE.search(url) for _, url in documents)), None)
        finished = FINISHED.search(period_text)
        rows.append({
            "state": section["estado"],
            "ref": code.group(1) if code else hashlib.sha1(title.encode()).hexdigest()[:10],
            "title": title,
            "job": job,
            "positions": _positions(title),
            "centre": _centre(job),
            "kind": "temporal" if "contratación temporal" in title.lower() else "indefinido",
            "period": _period(period_text),
            "finished": FULL_DATE.search(finished.group(1)).groups() if finished else None,
            "documents": documents,
        })
    return rows


class EnresaSource(Source):
    id = "enresa"
    name = "Enresa"
    homepage = PAGE
    ref_code = CODE  # sin código en la web, el ref es un hash
    apply_label = "Ver la convocatoria y cómo presentarse"

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._rows: list[dict] = []

    def _now(self) -> date:
        return self._today or datetime.now(MADRID).date()

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._rows = parse_listing(http.get(PAGE))
        offers = []
        for row in self._rows:
            if row["state"] != "abierta" or not row["period"]:
                continue
            main = _main_document(row)
            offers.append(ListedOffer(
                ref=row["ref"], title=row["job"], company=COMPANY, url=PAGE, apply_url=main,
                kind=row["kind"], positions=row["positions"], category="Acceso libre",
                opens_on=row["period"][0].isoformat(), deadline=row["period"][1].isoformat(),
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        row = next((r for r in self._rows if r["ref"] == offer.ref), None)
        if row is None:
            return OfferDetail()
        first, last = (d.strftime("%d/%m/%Y") for d in row["period"])
        sections = [{
            "title": "Convocatoria", "level": 2,
            "html": sanitize(f"<p>{escape(row['title'])}</p><p>Plazo de presentación de candidaturas: "
                             f"del {first} al {last}.</p>"),
        }]
        if row["documents"]:
            items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
                            for label, url in row["documents"])
            sections.append({"title": "Documentos de la convocatoria", "level": 2,
                             "html": sanitize(f"<ul>{items}</ul>")})
        return OfferDetail(sections=sections, location=row["centre"])

    def enrich(self, http: Client) -> dict[str, dict]:
        return {}

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Procesos en curso y cerrados en los últimos meses, con enlace a la convocatoria."""
        limit = self._now() - timedelta(days=RECENT_DAYS)
        items = {}
        for row in self._rows:
            common = {
                "process": _process_name(row), "url": _main_document(row), "process_url": PAGE,
                "contract": row["kind"], "system": selection_system(row["title"]),
                "access": "libre" if "acceso libre" in row["title"].lower() else None, "location": row["centre"],
            }
            if row["state"] == "proceso":
                notice = Announcement(date="", title="Plazo de candidaturas cerrado. Proceso en curso.", **common)
            elif row["state"] == "cerrada" and row["finished"]:
                closed = spanish_date(*row["finished"])
                if not closed or closed < limit:
                    continue
                notice = Announcement(date=closed.isoformat(), title="Proceso finalizado",
                                      state="finalizado", **common)
            else:
                continue
            items[notice.key] = notice
        return list(items.values())
