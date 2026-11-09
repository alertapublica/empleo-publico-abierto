"""Cofivacasa.

Una página de WordPress con un bloque por proceso: el primer enlace es el título y lleva a las
bases, después los comunicados y, al final, «Mes AAAA. Proceso abierto / cerrado / desistido».
No hay plazo ni día de publicación: solo mes y estado. Los comunicados quedan sin fecha exacta
y no se anuncian.

Las bases (PDF, comprobadas en el proceso de octubre de 2026) fijan contrato indefinido en la
sede social de Madrid y envío por correo; el plazo solo figura en ellas.
"""
from __future__ import annotations

import re
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import month_number
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError
from ..sanitize import sanitize
from .base import Source

PAGE = "https://cofivacasa.com/empleo-publico/"
COMPANY = "Cofivacasa"
STATE = re.compile(r"([A-Za-záéíóú]+)\s+(\d{4})\.\s*Proceso\s+([a-záéíóú]+)", re.I)
PREFIX = re.compile(r"^COFIVACASA\s*[–-]\s*", re.I)


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select("div.fusion-text")
    processes = []
    for block in blocks:
        paragraphs = block.find_all("p")
        first = paragraphs[0].find("a", href=True) if paragraphs else None
        status = STATE.search(_clean(paragraphs[-1].get_text(" "))) if paragraphs else None
        if not (first and status and month_number(status.group(1))):
            continue  # texto suelto que no es un proceso
        link = urljoin(PAGE, first["href"])
        documents = [(_clean(a.get_text(" ")), urljoin(PAGE, a["href"]))
                     for p in paragraphs[1:-1] for a in p.find_all("a", href=True)]
        title = PREFIX.sub("", _clean(first.get_text(" ")))
        processes.append({
            "title": title[:1].upper() + title[1:].lower(),
            "bases": link,
            "documents": documents,
            "month": month_number(status.group(1)),
            "year": int(status.group(2)),
            "state": status.group(3).lower(),
            "ref": re.sub(r"[^a-z0-9]+", "-", link.rsplit("/", 1)[-1].lower().removesuffix(".pdf")).strip("-"),
        })
    if blocks and not processes:
        raise SourceLayoutError("Cofivacasa: hay bloques de texto pero ninguno es un proceso")
    if not blocks:
        raise SourceLayoutError("Cofivacasa: no se encuentran los procesos")
    return processes


class CofivacasaSource(Source):
    id = "cofivacasa"
    name = "Cofivacasa"
    homepage = PAGE
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self) -> None:
        self._processes: list[dict] = []

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._processes = parse_page(http.get(PAGE))
        return [
            ListedOffer(
                ref=p["ref"], title=p["title"], company=COMPANY, url=PAGE, apply_url=p["bases"],
                kind="indefinido", category="Tasa de reposición" if "tasa-reposicion" in p["ref"] else None,
            )
            for p in self._processes if p["state"] == "abierto"
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        process = next((p for p in self._processes if p["ref"] == offer.ref), None)
        if process is None:
            return OfferDetail()
        items = f'<li><a href="{escape(process["bases"], quote=True)}">Bases de la convocatoria</a></li>' + "".join(
            f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>' for label, url in process["documents"])
        return OfferDetail(
            sections=[
                {"title": "Documentos de la convocatoria", "level": 2, "html": sanitize(f"<ul>{items}</ul>")},
                {"title": "Cómo presentar la candidatura", "level": 2,
                 "html": "<p>El plazo y el modo de presentación figuran en las bases: la candidatura se "
                         "envía por correo electrónico a empleo@cofivacasa.com.</p>"},
            ],
            location="Madrid",
        )
