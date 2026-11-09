"""Agencia EFE.

Dos páginas de WordPress (temporal e indefinido) con tablas TablePress. Cada fila trae
referencia, puesto, dirección, plazas, centro de trabajo, fecha de publicación, plazo,
situación y enlaces a las bases en PDF. No hay ficha propia ni formulario de inscripción:
la candidatura se presenta como indican las bases.

«Abierto» en la columna de situación significa proceso en curso, no plazo abierto: muchas
filas siguen «abiertas» meses después de vencer el plazo de candidaturas. Solo se
consideran ofertas las que aún admiten candidaturas.

`agenciaefe.es` responde 403 a las IP de Actions (desde el 2026-11-09): se lee por el relay
(`VIA_RELAY` en `http.py`).
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import MADRID, Announcement, ListedOffer, OfferDetail, SourceLayoutError
from ..sanitize import sanitize
from .base import Source

BASE = "https://agenciaefe.es"
PAGES = [
    ("temporal", f"{BASE}/empleo-efe-temporal/", "Contratación temporal"),
    ("indefinido", f"{BASE}/empleo-efe-indefinido/", "Oferta de empleo público"),
]
REQUIRED = [
    "Nº Referencia", "Puesto", "Dirección/Delegación", "Nº Plazas", "Centro trabajo",
    "Fecha publicación", "Plazo máximo presentación candidaturas", "Situación proceso",
]
OPEN = "abierto"
COMPANY = "Agencia EFE"


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def _date(value: str) -> str | None:
    for layout in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(value.strip(), layout).date().isoformat()
        except ValueError:
            continue
    return None


def _label(text: str, position: int) -> str:
    text = _clean(text).strip("- ").strip()
    if position == 0:
        return "Bases de la convocatoria"
    if text.lower() in ("", "ver"):
        return "Resolución"
    return text


def parse_listing(html: str, kind: str, category: str, page_url: str, today: date,
                  current: bool = True) -> list[dict]:
    """Filas «abiertas» con todos los datos de la tabla.

    `current` elige las que aún admiten candidaturas; si es False, las que siguen en
    tramitación con el plazo ya vencido."""
    soup = BeautifulSoup(html, "html.parser")
    tables = []
    for table in soup.select("table.tablepress"):
        head = table.find("tr")
        headers = [_clean(cell.get_text(" ")) for cell in head.find_all(["th", "td"])] if head else []
        if all(name in headers for name in REQUIRED):
            tables.append((table, headers))
    if not tables:
        raise SourceLayoutError("EFE: no se encuentra la tabla de convocatorias con sus columnas")

    rows: dict[str, dict] = {}
    for table, headers in tables:
        for tr in table.find_all("tr")[1:]:
            cells = tr.find_all(["td", "th"])
            if len(cells) != len(headers):
                continue
            values = {name: _clean(cell.get_text(" ")) for name, cell in zip(headers, cells)}
            ref = values["Nº Referencia"]
            if not ref or values["Situación proceso"].lower() != OPEN:
                continue
            deadline = _date(values["Plazo máximo presentación candidaturas"])
            expired = bool(deadline) and deadline < today.isoformat()
            if expired == current:
                continue
            documents, seen = [], set()
            for position, anchor in enumerate(tr.find_all("a", href=True)):
                url = urljoin(page_url, anchor["href"])
                if url not in seen:
                    seen.add(url)
                    documents.append((_label(anchor.get_text(" "), position), url))
            positions = values["Nº Plazas"]
            rows[ref] = {
                "ref": ref,
                "title": values["Puesto"],
                "department": values["Dirección/Delegación"] or None,
                "positions": int(positions) if positions.isdigit() else None,
                "location": values["Centro trabajo"] or None,
                "published_on": _date(values["Fecha publicación"]),
                "deadline": deadline,
                "observations": values.get("Observaciones", "").strip("- ").strip() or None,
                "documents": documents,
                "kind": kind,
                "category": category,
                "url": documents[0][1] if documents else page_url,
            }
    return list(rows.values())


def _to_listed(row: dict) -> ListedOffer:
    return ListedOffer(
        ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"],
        apply_url=row["url"], kind=row["kind"], positions=row["positions"],
        category=row["category"], deadline=row["deadline"],
    )


def _detail(row: dict) -> OfferDetail:
    sections = []
    if row["documents"]:
        items = "".join(
            f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
            for label, url in row["documents"]
        )
        sections.append({"title": "Documentos de la convocatoria", "level": 2,
                         "html": sanitize(f"<ul>{items}</ul>")})
    if row["observations"]:
        sections.append({"title": "Observaciones", "level": 2,
                         "html": sanitize(f"<p>{escape(row['observations'])}</p>")})
    sections.append({
        "title": "Cómo presentar la candidatura", "level": 2,
        "html": "<p>Las bases de la convocatoria explican cómo y dónde presentar la candidatura. "
                "La Agencia EFE no publica una ficha propia de cada oferta.</p>",
    })
    return OfferDetail(sections=sections, location=row["location"])


class EfeSource(Source):
    id = "efe"
    name = "Agencia EFE"
    homepage = f"{BASE}/empleo-efe-indefinido/"
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._rows: dict[str, dict] = {}
        self._in_progress: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = self._today or datetime.now(MADRID).date()
        self._rows, self._in_progress = {}, {}
        for kind, url, category in PAGES:
            html = http.get(url)
            for row in parse_listing(html, kind, category, url, today):
                self._rows.setdefault(row["ref"], row)
            if kind == "indefinido":
                for row in parse_listing(html, kind, category, url, today, current=False):
                    self._in_progress.setdefault(row["ref"], row)
        return [_to_listed(row) for row in self._rows.values()]

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Procesos indefinidos cuyo plazo venció pero siguen en tramitación."""
        items = []
        for row in self._in_progress.values():
            day = row["published_on"] or row["deadline"]
            if not day or not row["deadline"]:
                continue
            closed = date.fromisoformat(row["deadline"]).strftime("%d/%m/%Y")
            items.append(Announcement(
                date=day, process=f"{row['title']} ({row['ref']})",
                title=f"Plazo de candidaturas finalizado el {closed}. Proceso en curso.", url=row["url"],
                via="oep", access="libre", contract="indefinido", process_url=PAGES[1][1],
            ))
        return items

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        row = self._rows.get(offer.ref)
        return _detail(row) if row else OfferDetail()

    def enrich(self, http: Client) -> dict[str, dict]:
        # Todo viene ya en el listado: no hace falta otra petición.
        return {
            ref: {"published_on": row["published_on"], "location": row["location"],
                  "department": row["department"]}
            for ref, row in self._rows.items()
        }
