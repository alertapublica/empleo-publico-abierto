"""SARGA (Sociedad Aragonesa de Gestión Agroambiental).

`/ofertas-de-empleo-especifico/` (Elementor) lista las ofertas recientes: título, «Fecha de
publicación», «Fecha límite de recepción de candidatura», un botón «Inscripción» a la plataforma
de selección y las bases en PDF (a veces el mismo para varias convocatorias).

El botón y la etiqueta «Abierta» siguen días después del cierre, así que se ofrece lo que tiene
fecha límite no pasada. Las bases dicen la hora («finaliza el día 12 de noviembre de 2026 a las
14:00 horas»), el tipo de contrato y los puestos. Su texto sale a veces con letras cambiadas
(«Alcaæiz»): un dato con esos signos no se guarda.

`robots.txt` pide 10 s entre peticiones y prohíbe la paginación: se lee solo la primera página,
donde están las más recientes. Las convocatorias anuales de campaña (agosto) se publican en otra
página como texto libre y no se leen todavía.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape

from bs4 import BeautifulSoup

from ..dates import MONTHS, numeric_date, spanish_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from ..pdftext import read_pdf
from ..sanitize import sanitize
from ..text import slug
from .base import Source

PAGE = "https://www.sarga.es/ofertas-de-empleo-especifico/"
COMPANY = "SARGA"
DATE = re.compile(r"\d\d/\d\d/\d{4}")
CLOSING = re.compile(r"finaliza\s+el\s+(?:d[ií]a\s+)?(\d{1,2})\s+de\s+(" + "|".join(MONTHS) +
                     r")\s+de\s+(\d{4})\s+a\s+las\s+(\d{1,2})[:.](\d\d)", re.I)
FIELD = r"•\s*{}:\s*([^•]+?)\s*(?=•|El proceso|$)"
GARBLED = re.compile(r"[ØæœÆ]")
KIND = {"indefinido": "indefinido", "temporal": "temporal"}


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _labelled(card, label: str) -> str | None:
    node = card.find(string=re.compile(label))
    found = DATE.search(_text(node.find_parent("span"))) if node and node.find_parent("span") else None
    return numeric_date(found.group(0)) if found else None


def _card(heading):
    """Contenedor más cercano al título con las bases: en las cerradas, datos y botones van en columnas."""
    for node in heading.parents:
        if len(node.find_all(string=re.compile("Fecha límite"))) > 1:
            return None
        if node.find("a", href=re.compile(r"\.pdf$", re.I)):
            return node
    return None


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    headings = [h for h in soup.find_all("h3") if h.find_parent("div", class_="elementor-widget-wrap")
                and h.find_parent("div", class_="elementor-widget-wrap").find(string=re.compile("Fecha límite"))]
    if not headings:
        raise SourceLayoutError("SARGA: no se encuentran las ofertas")
    entries = []
    for heading in headings:
        title, card = _text(heading), _card(heading)
        pdf = card.find("a", href=re.compile(r"\.pdf$", re.I))["href"] if card else None
        deadline = _labelled(card, "Fecha límite") if card else None
        if not (pdf and deadline):
            raise SourceLayoutError(f"SARGA: «{title}» sin bases o sin fecha límite")
        published = _labelled(card, "Fecha de publicación")
        entries.append({
            # Varias convocatorias de campaña comparten PDF: la referencia es título y publicación.
            "ref": f"{slug(title)}-{(published or deadline).replace('-', '')}",
            "title": title,
            "published_on": published,
            "deadline": deadline,
            "pdf": pdf,
        })
    return entries


def _field(text: str, label: str) -> str | None:
    found = re.search(FIELD.format(label), text)
    value = found.group(1).strip() if found else None
    return None if not value or GARBLED.search(value) else value


def parse_bases(text: str) -> dict:
    closing = CLOSING.search(text)
    day = spanish_date(*closing.group(1, 2, 3)) if closing else None
    contract = _field(text, "Tipo de contrato")
    seats = _field(text, r"N[úœ]mero de puestos")
    return {
        "closing_day": day.isoformat() if day else None,
        "closing_time": f"{int(closing.group(4)):02d}:{closing.group(5)}" if closing else None,
        "contract": contract,
        "kind": KIND.get(re.split(r"[\s,]", contract)[0].lower()) if contract else None,
        "location": _field(text, "Lugar de trabajo"),
        "positions": int(seats) if seats and seats.isdigit() else None,
    }


class SargaSource(Source):
    id = "sarga"
    name = COMPANY
    homepage = PAGE
    detail_version = 2  # las plazas salen de las bases (#17)
    scope = "Aragón"
    delay = 10.0  # Crawl-delay de su robots.txt
    apply_label = "Ver la oferta y cómo inscribirse"

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = today_madrid(datetime.now(timezone.utc))
        return [
            ListedOffer(
                ref=e["ref"], title=e["title"], company=COMPANY, url=e["pdf"], apply_url=PAGE,
                kind=None, deadline=e["deadline"], published_on=e["published_on"],
            )
            for e in parse_page(http.get(PAGE)) if e["deadline"] >= today
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        bases = parse_bases(read_pdf(http, offer.url, f"SARGA, bases de {offer.title}"))
        link = f'<ul><li><a href="{escape(offer.url, quote=True)}">Bases de la oferta (PDF)</a></li></ul>'
        sections = [{"title": "Documentos de la convocatoria", "level": 2, "html": sanitize(link)}]
        same_day = bases["closing_day"] == offer.deadline
        return OfferDetail(
            sections=sections, location=bases["location"], contract=bases["contract"], kind=bases["kind"],
            deadline_time=bases["closing_time"] if same_day else None, positions=bases["positions"],
        )
