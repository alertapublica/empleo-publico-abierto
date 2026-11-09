"""Cetarsa (Compañía Española de Tabaco en Rama).

Una página de WordPress por año (`/empleo-2026/`). Cada sección («Ofertas de Empleo Activas –
Convocatoria Libre», «Bolsas… – Activas», «… – Promoción Interna», «… – Finalizadas») agrupa
convocatorias en bloques desplegables, y cada una trae una tabla con fecha y descripción de
cada documento publicado. El plazo no está en un campo: es una fila de texto («Se establece
plazo de solicitudes hasta el 16 de Noviembre las 14:00 horas del 2026»).

Es oferta una convocatoria libre o bolsa activa cuyo plazo sigue abierto. La promoción
interna no admite candidaturas externas: solo se anuncia. Del resto de convocatorias activas se
anuncian todos sus comunicados, con el texto completo: ahí están los cambios de fecha y lugar de
los exámenes. Los enlaces de la tabla se repiten entre filas, así que no se usan.
"""
from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from html import escape

from bs4 import BeautifulSoup

from ..dates import clock, latest, spanish_date
from ..http import Client
from ..model import MADRID, Announcement, ListedOffer, OfferDetail, SourceLayoutError, selection_system
from ..sanitize import sanitize
from .base import Source

PAGE = "https://www.cetarsa.es/empleo-2026/"
COMPANY = "Cetarsa"
APPLICATION = re.compile(
    r"(?:plazo\s+de\s+solicitudes|ampliaci[óo]n\s+del\s+plazo)[^.]*?hasta\s+el\s+(\d{1,2})\s+de\s+"
    r"([A-Za-záéíóú]+)([^.]*?)(\d{4})", re.I)
JOB = re.compile(r".*(?:Trabajo de|puestos? de)\s+(.+?)\s+en la Compañ", re.I)
POSITIONS = re.compile(r"\((\d+)\)")
ISO = re.compile(r"\d{4}-\d{2}-\d{2}")
SKIP_ROWS = ("anexo", "bases")


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def _deadline(rows: list[dict]) -> tuple[date | None, str | None]:
    """Último día de solicitudes y su hora («… las 14:00 horas del 2026»); si lo amplían, vale la fecha mayor."""
    days = []
    for row in rows:
        for day, month, between, year in APPLICATION.findall(row["text"]):
            found = spanish_date(day, month, year)
            if found:
                days.append((found, clock(between)))
    return latest(days)


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one(".entry-content")
    if content is None:
        raise SourceLayoutError("Cetarsa: no se encuentra el contenido de la página")
    found = []
    for group in content.find_all("div", class_="wp-block-group", recursive=False):
        heading = group.find("p", class_="alignwide")
        details = group.find_all("details")
        if not details:
            continue
        if heading is None:
            raise SourceLayoutError("Cetarsa: convocatorias sin encabezado de sección")
        section = _clean(heading.get_text(" ")).rstrip(":").strip()
        lowered = section.lower()
        for block in details:
            summary = block.find("summary")
            title = _clean(summary.get_text(" ")) if summary else ""
            rows = []
            for tr in block.select("tbody tr"):
                cells = tr.find_all("td")
                if len(cells) < 2 or not ISO.fullmatch(_clean(cells[0].get_text())):
                    raise SourceLayoutError("Cetarsa: fila de documentos sin fecha o descripción")
                rows.append({"date": _clean(cells[0].get_text()), "text": _clean(cells[1].get_text(" "))})
            if not title or not rows:
                raise SourceLayoutError("Cetarsa: convocatoria sin título o sin documentos")
            job = JOB.match(title)
            positions = POSITIONS.search(title)
            deadline, hour = _deadline(rows)
            found.append({
                "section": section,
                "active": "activas" in lowered,
                "internal": "promoción interna" in lowered or "promocion interna" in lowered,
                "bank": "bolsa" in lowered,
                "title": title,
                "job": _clean(job.group(1)) if job else title,
                "positions": int(positions.group(1)) if positions else None,
                "ref": hashlib.sha1(f"{section}|{title}".encode()).hexdigest()[:10],
                "rows": rows,
                "deadline": deadline,
                "deadline_time": hour,
            })
    if not found:
        raise SourceLayoutError("Cetarsa: no se lee ninguna convocatoria")
    return found


class CetarsaSource(Source):
    id = "cetarsa"
    name = "Cetarsa"
    homepage = PAGE
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._items: list[dict] = []

    def _now(self) -> date:
        return self._today or datetime.now(MADRID).date()

    def _is_open(self, item: dict) -> bool:
        return (item["active"] and not item["internal"] and item["deadline"] is not None
                and item["deadline"] >= self._now())

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._items = parse_page(http.get(PAGE))
        return [
            ListedOffer(
                ref=item["ref"], title=item["job"], company=COMPANY, url=PAGE, apply_url=PAGE,
                kind="bolsa" if item["bank"] else "indefinido", positions=item["positions"],
                category="Convocatoria libre", deadline=item["deadline"].isoformat(),
                deadline_time=item["deadline_time"],
            )
            for item in self._items if self._is_open(item)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        item = next((i for i in self._items if i["ref"] == offer.ref), None)
        if item is None:
            return OfferDetail()
        rows = "".join(f"<li>{escape(r['date'])}: {escape(r['text'])}</li>" for r in item["rows"])
        return OfferDetail(sections=[
            {"title": "Convocatoria", "level": 2, "html": sanitize(f"<p>{escape(item['title'])}</p>")},
            {"title": "Documentos publicados", "level": 2, "html": sanitize(f"<ul>{rows}</ul>")},
            {"title": "Cómo presentar la candidatura", "level": 2,
             "html": "<p>Las bases de la convocatoria, en la página oficial, explican dónde y cómo "
                     "presentar la candidatura y qué tipo de contrato se ofrece.</p>"},
        ])

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Los comunicados de cada convocatoria activa que ya no admite candidaturas."""
        items = {}
        for item in self._items:
            if not item["active"] or self._is_open(item):
                continue
            if item["internal"]:
                what, access = "Promoción interna", "interna"
            elif item["bank"]:  # el encabezado oficial dice a quién se dirige: se muestra tal cual
                what, access = "Bolsa temporal para personal de Cetarsa", None
            else:
                what, access = "Convocatoria libre", "libre"
            system = selection_system(" ".join([item["title"], *(r["text"] for r in item["rows"])]))
            for row in item["rows"]:
                if row["text"].lower().startswith(SKIP_ROWS):
                    continue
                notice = Announcement(
                    date=row["date"], process=f"{item['job']} · {what}", title=row["text"], url=PAGE,
                    via="bolsa" if item["bank"] else "otro", access=access,
                    contract="temporal" if item["bank"] else "indefinido", system=system,
                    process_url=PAGE,
                )
                items[notice.key] = notice
        return list(items.values())
