"""Hipódromo de la Zarzuela.

La página «Información corporativa» lista, bajo «Ofertas de empleo», los PDF de cada proceso:
primero las bases («Oferta de empleo. Puesto») y, cuando avanza, los listados y la adjudicación
(«… Oferta de empleo. Puesto»). Esos listados son de personas y no se copian.

La página no da plazo, plazas ni contrato: están en las bases. Un proceso solo es oferta si no tiene
más documentos que las bases y su plazo, leído en ellas, no ha vencido.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import escape
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError
from ..pdftext import deadlines, read_pdf
from ..sanitize import sanitize
from ..text import slug
from .base import Source

SITE = "https://www.hipodromodelazarzuela.es"
PAGE = f"{SITE}/informacion-corporativa"
COMPANY = "Hipódromo de la Zarzuela"
BASES = re.compile(r"^Oferta de empleo\.\s*(.+)$", re.I)
LATER = re.compile(r"^.+?\.\s*Oferta de empleo\.\s*(.+)$", re.I)
PUBLISHED = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
VACANCIES = re.compile(r"cobertura de\s+(un|una|\d+)\s+(?:puesto|plaza)", re.I)
FIXED_DISCONTINUOUS = "Modalidad fija discontinua. "


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def _title(process: str) -> str:
    discontinuous = process.startswith(FIXED_DISCONTINUOUS)
    name = _clean(process.removeprefix(FIXED_DISCONTINUOUS)).replace("_a", "/a")
    name = name[:1].upper() + name[1:]
    return f"{name} (fijo discontinuo)" if discontinuous else name


def parse_page(html: str) -> list[dict]:
    """Un diccionario por proceso: sus bases y la cantidad de documentos posteriores."""
    soup = BeautifulSoup(html, "html.parser")
    heading = next((h for h in soup.find_all("h2") if _clean(h.get_text()).upper() == "OFERTAS DE EMPLEO"), None)
    if heading is None:
        raise SourceLayoutError("Zarzuela: no aparece la sección «Ofertas de empleo»")
    section = heading.find_parent("div", class_="text-block") or heading.parent
    processes: dict[str, dict] = {}
    for link in section.select("span.file a[href]"):
        label = _clean(link.get_text(" "))
        url = urljoin(SITE, quote(link["href"], safe="/%:"))
        bases, later = BASES.match(label), LATER.match(label)
        if bases:
            processes[bases.group(1)] = {"process": bases.group(1), "bases": url, "later": 0}
        elif later:
            processes.setdefault(later.group(1), {"process": later.group(1), "bases": None, "later": 0})["later"] += 1
    if not processes:
        raise SourceLayoutError("Zarzuela: la sección de ofertas no lista ningún proceso")
    return [p for p in processes.values() if p["bases"]]


class ZarzuelaSource(Source):
    id = "zarzuela"
    name = "Hipódromo de la Zarzuela"
    homepage = PAGE
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._found: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = self._today or datetime.now(MADRID).date()
        offers = []
        for process in parse_page(http.get(PAGE)):
            if process["later"]:
                continue  # ya hay listados: la inscripción terminó
            text = read_pdf(http, process["bases"], f"Zarzuela, bases de {process['process']}")
            closing = deadlines(text)
            if not closing:
                raise SourceLayoutError(f"Zarzuela: no se encuentra el plazo en las bases de {process['process']}")
            if max(closing) < today:
                continue
            published = PUBLISHED.search(text[:400])
            vacancies = VACANCIES.search(text)
            amount = vacancies.group(1).lower() if vacancies else None
            title = _title(process["process"])
            ref = slug(title)
            self._found[ref] = {"text": text, "deadline": max(closing), "bases": process["bases"],
                                "published": f"{published.group(3)}-{published.group(2)}-{published.group(1)}" if published else None}
            offers.append(ListedOffer(
                ref=ref, title=title, company=COMPANY, url=PAGE, apply_url=process["bases"], kind="indefinido",
                positions=(1 if amount in ("un", "una") else int(amount)) if amount else None,
                category="Tasa de reposición" if "tasa de reposición" in text.lower() else None,
                deadline=max(closing).isoformat(),
            ))
        return offers

    def enrich(self, http: Client) -> dict[str, dict]:
        return {ref: {"published_on": data["published"]} for ref, data in self._found.items() if data["published"]}

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        data = self._found.get(offer.ref)
        if data is None:
            return OfferDetail()
        lines = [f"<li><strong>Inscripción hasta:</strong> {data['deadline'].strftime('%d/%m/%Y')}</li>"]
        sections = [
            {"title": "Datos del puesto", "level": 2, "html": sanitize(f"<ul>{''.join(lines)}</ul>")},
            {"title": "Documentos de la convocatoria", "level": 2,
             "html": sanitize(f'<ul><li><a href="{escape(data["bases"], quote=True)}">Bases de la convocatoria</a></li></ul>')},
        ]
        return OfferDetail(sections=sections, location="Madrid")
