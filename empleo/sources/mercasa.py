"""Mercasa.

`Únete a Mercasa` lista, por proceso, un título y los PDF: bases, anexos y, cuando avanza, las
ampliaciones de plazo y los listados de personas (que no se copian).

El plazo no está en la página sino en las bases y en las ampliaciones: «hasta las 12:00 h del 29 de
octubre de 2026». Un proceso es oferta si no tiene listados ni marca «finalizado» y su último plazo
(el mayor entre las bases y sus ampliaciones) no ha vencido.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import escape

from bs4 import BeautifulSoup

from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError
from ..dates import latest
from ..pdftext import deadlines_at, read_pdf
from ..sanitize import sanitize
from ..text import slug
from .base import Source

PAGE = "https://www.mercasa.es/que-es-mercasa/unete-a-mercasa/"
COMPANY = "Mercasa"
# Documentos que solo existen cuando la inscripción ya terminó, o el proceso se cerró.
AFTER_REGISTRATION = re.compile(
    r"(?:relaci[óo]n|calificaci|valoraci|listado|calendari|adjudica|resoluci|puntuaci|convocatoria de pruebas)", re.I)
EXTENSION = re.compile(r"ampliaci[óo]n.*plazo", re.I)
ADDRESS = re.compile(r"Centro de trabajo:[^()]*\(([^()]+)\)", re.I)


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


ACRONYMS = {"TIC", "TD", "ESG"}


def _sentence(title: str) -> str:
    """«TÉCNICO/A APOYO TIC» → «Técnico/a apoyo TIC»; si el título ya viene en minúsculas, se respeta."""
    if not title.isupper():
        return title
    words = [w if w in ACRONYMS else w.lower() for w in title.split()]
    text = " ".join(words)
    return text[:1].upper() + text[1:]


def parse_page(html: str) -> list[dict]:
    """Un diccionario por proceso, con sus documentos en el orden de la página."""
    soup = BeautifulSoup(html, "html.parser")
    links = soup.select("a.learn-more[href]")
    if not links:
        raise SourceLayoutError("Mercasa: no se encuentran los documentos de los procesos")
    processes: list[dict] = []
    for element in soup.select("div.wpb_text_column h2, a.learn-more[href]"):
        if element.name == "h2":
            processes.append({"title": _clean(element.get_text(" ")), "documents": []})
        elif processes:
            label = _clean(element.get_text(" "))
            if element["href"].lower().endswith(".pdf") and label:
                processes[-1]["documents"].append((label, element["href"]))
    processes = [p for p in processes if p["documents"]]
    if not processes:
        raise SourceLayoutError("Mercasa: ningún título va seguido de documentos")
    return processes


def _bases(process: dict) -> str | None:
    return next((url for label, url in process["documents"] if label.upper().startswith("BASES")), None)


def _is_candidate(process: dict) -> bool:
    if "finalizado" in process["title"].lower() or _bases(process) is None:
        return False
    return not any(AFTER_REGISTRATION.match(label) for label, _ in process["documents"])


class MercasaSource(Source):
    id = "mercasa"
    name = "Mercasa"
    homepage = PAGE
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._found: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = self._today or datetime.now(MADRID).date()
        offers = []
        for process in parse_page(http.get(PAGE)):
            if not _is_candidate(process):
                continue
            title = process["title"]
            text = read_pdf(http, _bases(process), f"Mercasa, bases de {title}")
            closing = deadlines_at(text)
            if not closing:
                raise SourceLayoutError(f"Mercasa: no se encuentra el plazo en las bases de {title}")
            for label, url in process["documents"]:
                if EXTENSION.search(label):
                    closing += deadlines_at(read_pdf(http, url, f"Mercasa, ampliación de {title}"))
            last_day, hour = latest(closing)
            if last_day < today:
                continue
            address = ADDRESS.search(text)
            ref = slug(title)
            self._found[ref] = {"deadline": last_day, "bases": _bases(process), "documents": process["documents"],
                                "place": _clean(address.group(1).rsplit(",", 1)[-1]) if address else None}
            offers.append(ListedOffer(
                ref=ref, title=_sentence(title), company=COMPANY, url=PAGE,
                apply_url=_bases(process), kind="indefinido" if re.search("indefinid", text, re.I) else "temporal",
                category="Tasa de reposición" if "tasa de reposición" in text.lower() else None,
                deadline=last_day.isoformat(), deadline_time=hour,
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        data = self._found.get(offer.ref)
        if data is None:
            return OfferDetail()
        items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
                        for label, url in data["documents"])
        line = f"<li><strong>Inscripción hasta:</strong> {data['deadline'].strftime('%d/%m/%Y')}</li>"
        return OfferDetail(
            sections=[
                {"title": "Datos del puesto", "level": 2, "html": sanitize(f"<ul>{line}</ul>")},
                {"title": "Documentos de la convocatoria", "level": 2, "html": sanitize(f"<ul>{items}</ul>")},
            ],
            location=data["place"],
        )
