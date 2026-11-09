"""Sepides.

`sepides.es/empleo` tiene dos pestañas, «Procesos abiertos» y «Procesos cerrados», y en cada una un
desplegable por proceso con sus PDF. «Abierto» quiere decir en curso, no con la inscripción abierta:
los dos procesos que había al estudiarla ya estaban en la fase de listados.

Un proceso es oferta solo si está en «abiertos», todos sus documentos son de convocatoria (bases,
rectificaciones, ampliaciones de plazo; sin composición del órgano ni listados, que se publican
después del plazo) y el plazo que figura en esos PDF no ha vencido. Cualquier documento que no
reconozca lo deja fuera.
"""
from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup
from html import escape

from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError
from ..pdftext import deadlines, read_pdf
from ..sanitize import sanitize
from ..text import slug
from .base import Source

PAGE = "https://sepides.es/empleo"
OPEN_TAB = "PROCESOS ABIERTOS"
CALL = re.compile(r"^convocatoria\b", re.I)
EXTRA = re.compile(r"^(?:nota rectificativa|aviso de ampliaci[óo]n de plazo|nota:?\s)", re.I)
UPLOAD = re.compile(r"/uploads/(\d{4})/(\d{2})/")
PLACE = re.compile(r"Ubicaci[óo]n del centro de trabajo\s+([A-ZÁÉÍÓÚÑ][^.]+)\.")
VACANCIES = re.compile(r"N\.º de puestos a cubrir\s+(\d+)", re.I)
SMALL = {"de", "del", "la", "y", "e"}


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def _company(raw: str) -> str:
    """«SEPIDES E.P.E.» → «Sepides»; «SEPIDES GESTIÓN, S.G.E.I.C., …» → «Sepides Gestión»."""
    name = re.sub(r"\s+E\.P\.E\.?$", "", raw.split(",")[0].strip())
    return " ".join(w if w.lower() in SMALL and i else w.capitalize() for i, w in enumerate(name.lower().split()))


def parse_page(html: str) -> list[dict]:
    """Un diccionario por proceso: pestaña, título, empresa y documentos (etiqueta, URL)."""
    soup = BeautifulSoup(html, "html.parser")
    tabs = {button["aria-controls"]: _clean(button.get_text(" "))
            for button in soup.select('button[role="tab"][aria-controls]')}
    panels = soup.select('div[role="tabpanel"]')
    if OPEN_TAB not in tabs.values() or not panels:
        raise SourceLayoutError("Sepides: no se encuentran las pestañas de procesos abiertos y cerrados")
    processes = []
    for panel in panels:
        tab = tabs.get(panel.get("id"))
        if tab is None:
            continue
        for item in panel.select("details.e-n-accordion-item"):
            title = item.select_one(".e-n-accordion-item-title-text")
            if title is None:
                raise SourceLayoutError("Sepides: desplegable sin título")
            company = item.find("h6")
            processes.append({
                "tab": tab, "title": _clean(title.get_text(" ")),
                "company": _company(_clean(company.get_text(" "))) if company else "Sepides",
                "documents": [(_clean(a.get_text(" ")), a["href"]) for a in item.select("li a[href]")],
            })
    if not any(p["tab"] != OPEN_TAB for p in processes):
        raise SourceLayoutError("Sepides: no aparece ningún proceso cerrado; la página no tiene la forma esperada")
    return processes


def _is_registration_open(process: dict) -> bool:
    docs = process["documents"]
    return (process["tab"] == OPEN_TAB and any(CALL.match(label) for label, _ in docs)
            and all(CALL.match(label) or EXTRA.match(label) for label, _ in docs))


class SepidesSource(Source):
    id = "sepides"
    name = "Sepides"
    homepage = PAGE
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._found: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = self._today or datetime.now(MADRID).date()
        offers = []
        for process in parse_page(http.get(PAGE)):
            if not _is_registration_open(process):
                continue
            title = process["title"]
            base_label, base_url = next((d for d in process["documents"] if CALL.match(d[0])))
            text = read_pdf(http, base_url, f"Sepides, bases de {title}")
            closing = deadlines(text)
            for label, url in process["documents"]:
                if EXTRA.match(label):
                    closing += deadlines(read_pdf(http, url, f"Sepides, {label} de {title}"))
            if not closing:
                raise SourceLayoutError(f"Sepides: no se encuentra el plazo en las bases de {title}")
            if max(closing) < today:
                continue
            upload = UPLOAD.search(base_url)
            ref = slug(title) + (f"-{upload.group(1)}-{upload.group(2)}" if upload else "")
            place, vacancies = PLACE.search(text), VACANCIES.search(text)
            self._found[ref] = {"deadline": max(closing), "documents": process["documents"],
                                "place": _clean(place.group(1)) if place else None}
            offers.append(ListedOffer(
                ref=ref, title=title, company=process["company"], url=PAGE, apply_url=base_url,
                kind="indefinido" if re.search(r"indefinid", text[:3000], re.I) else "temporal",
                positions=int(vacancies.group(1)) if vacancies else None,
                deadline=max(closing).isoformat(),
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
