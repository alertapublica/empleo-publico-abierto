"""SENASA (Servicios y Estudios para la Navegación Aérea y la Seguridad Aeronáutica).

Una sola página con todas las convocatorias desde 2019, cada una en un bloque `div.contrato`
con referencia (`98-26`), plazas, fecha de publicación y «fecha fin de vigencia» en AAAA-MM-DD.
La ficha es un PDF con texto, que da el centro de trabajo y la «Modalidad de contratación».
La inscripción es un formulario de la misma página.

Las bases en PDF no dan plazo: la única fecha es la «fecha fin de vigencia». En las cerradas cae
semanas o meses después de la publicación y varias coinciden en el mismo día, así que parece la
fecha en que SENASA retira la oferta, que puede prorrogar. Se ofrecen los bloques que tienen a la
vez el enlace de inscripción (el título enlaza al formulario solo en las abiertas) y una fecha
fin de vigencia no pasada. Los bloques sin referencia no son ofertas: resoluciones de procesos ya
cerrados y una llamada permanente a controladores aéreos sin plazo.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from ..pdftext import read_pdf
from ..sanitize import sanitize
from .base import Source

HOST = "https://www.senasa.es"
PAGE = f"{HOST}/index.php?idPag=13&lang=es-ES"
COMPANY = "SENASA"
ISO_DATE = r"(\d{4}-\d\d-\d\d)"
REF = re.compile(r"Referencia:\s*(\d+-\d\d)\b")
SEATS = re.compile(r"Plazas Vacantes:\s*(\d+)")
PUBLISHED = re.compile(r"Fecha de publicaci[óo]n:\s*" + ISO_DATE)
END = re.compile(r"Fecha fin de vigencia:\s*" + ISO_DATE)
CONTRACT = re.compile(r"Modalidad de contrataci[óo]n:\s*([^.]+?)\s*(?:\.|Pruebas de Selecci|$)")
CENTRE = re.compile(r"Centro de trabajo:\s*(.+?)\s+Direcci[óo]n de dependencia", re.I)
KIND = {"temporal": "temporal", "indefinido": "indefinido", "indefinida": "indefinido"}


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def parse_list(html: str) -> list[dict]:
    """Convocatorias con referencia, abiertas o no."""
    blocks = BeautifulSoup(html, "html.parser").select("div.contrato")
    entries = []
    for block in blocks:
        text = _text(block)
        ref = REF.search(text)
        if not ref:
            continue
        title, end, pdf = block.find("h1"), END.search(text), block.find("a", href=re.compile(r"\.pdf$", re.I))
        if not (title and end and pdf):
            raise SourceLayoutError(f"SENASA: la convocatoria {ref.group(1)} no tiene título, plazo o PDF")
        seats, published = SEATS.search(text), PUBLISHED.search(text)
        entries.append({
            "ref": ref.group(1),
            "title": _text(title),
            "positions": int(seats.group(1)) if seats else None,
            "published_on": published.group(1) if published else None,
            "deadline": end.group(1),
            "pdf": urljoin(HOST, pdf["href"]),
            "registration": title.find("a", onclick=re.compile("inscripcion")) is not None,
        })
    if not entries:
        raise SourceLayoutError("SENASA: no se encuentran convocatorias")
    return entries


def parse_pdf(text: str) -> dict:
    contract = CONTRACT.search(text)
    centre = CENTRE.search(text)
    literal = contract.group(1).strip() if contract else None
    return {
        "contract": literal,
        "kind": KIND.get((literal or "").lower()),
        "location": centre.group(1).strip() if centre else None,
    }


class SenasaSource(Source):
    id = "senasa"
    name = COMPANY
    homepage = PAGE
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = today_madrid(datetime.now(timezone.utc))
        return [
            ListedOffer(
                ref=entry["ref"], title=entry["title"], company=COMPANY, url=entry["pdf"], apply_url=PAGE,
                kind=None, positions=entry["positions"], deadline=entry["deadline"],
                published_on=entry["published_on"],
            )
            for entry in parse_list(http.get(PAGE)) if entry["registration"] and entry["deadline"] >= today
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        data = parse_pdf(read_pdf(http, offer.url, f"SENASA, convocatoria {offer.ref}"))
        link = f'<ul><li><a href="{escape(offer.url, quote=True)}">Convocatoria {escape(offer.ref)} (PDF)</a></li></ul>'
        return OfferDetail(
            sections=[{"title": "Documentos de la convocatoria", "level": 2, "html": sanitize(link)}],
            location=data["location"], contract=data["contract"], kind=data["kind"],
        )
