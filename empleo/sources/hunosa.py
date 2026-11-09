"""Grupo Hunosa: de momento, las convocatorias de SADIM.

La página de empleo de Hunosa (`hunosa.es/empleo-publico/`) solo trae títulos cuyos enlaces ya
no existen. Las convocatorias vigentes del grupo están en `sadim.es/empleo`: un bloque por
proceso con título, código (P2026.02), estado o plazo en texto y los documentos.

El plazo se lee de la propia página («finaliza el próximo 16 de noviembre de 2026 a las 17:00»).
El contrato y la localidad, de las bases (PDF). Un proceso con el plazo vencido, desierto o
finalizado no es oferta.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import FULL_DATE, clock, latest, spanish_date
from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError
from ..pdftext import read_pdf
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.sadim.es"
PAGE = f"{SITE}/empleo/"
HOMEPAGE = "https://www.hunosa.es/empleo-publico/"
COMPANY = "SADIM"
CODE = re.compile(r"\s+(P\d{4}\.\d{2}(?:\.[IVX]+)?)$")
VACANCIES = re.compile(r"COBERTURA DE\s+(\d+)\s+PUESTO", re.I)
JOB = re.compile(r"PUESTO DE TRABAJO DE\s+(.+)$", re.I)
DEADLINE = re.compile(FULL_DATE.pattern + r"(?:\s*,?\s*a\s+las\s+(\d{1,2}[:.]\d{2}))?", re.I)
CLOSED = re.compile(r"desiert|finalizad|adjudicad", re.I)
LOCALITY = re.compile(r"Localidad:\s*(.+?)\.\s+(?:Tipo de contrato|Salario|Fecha)", re.I)
CONTRACT = re.compile(r"Tipo de contrato:\s*([^.]+)", re.I)


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    boxes = soup.select("div.reading-box")
    if not boxes:
        raise SourceLayoutError("SADIM: no se encuentran los bloques de ofertas vigentes")
    processes = []
    for box in boxes:
        heading = box.find("h2")
        title = _clean(heading.get_text(" ")) if heading else ""
        code = CODE.search(title)
        if code is None:
            raise SourceLayoutError(f"SADIM: proceso sin código en el título: {title!r}")
        extra = box.select_one(".reading-box-additional")
        status = " ".join(_clean(p.get_text(" ")) for p in (extra.find_all("p") if extra else [])
                          if "Documentación" not in p.get_text())
        pdfs = [urljoin(SITE, a["href"]) for a in box.find_all("a", href=True) if a["href"].lower().endswith(".pdf")]
        bases = next((u for u in pdfs if "BASES" in u.upper()), None)
        vacancies, job = VACANCIES.search(title), JOB.search(CODE.sub("", title))
        days = [(d, clock(hour)) for day, month, year, hour in DEADLINE.findall(status)
                if (d := spanish_date(day, month, year))]
        deadline, hour = latest(days)
        processes.append({
            "code": code.group(1), "status": status, "bases": bases,
            "title": (job.group(1) if job else CODE.sub("", title)).strip(),
            "positions": int(vacancies.group(1)) if vacancies else None,
            "deadline": deadline, "deadline_time": hour,
        })
    return processes


class HunosaSource(Source):
    id = "hunosa"
    name = "Grupo Hunosa"
    homepage = HOMEPAGE
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._texts: dict[str, str] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = self._today or datetime.now(MADRID).date()
        offers = []
        for process in parse_page(http.get(PAGE)):
            if CLOSED.search(process["status"]) or not process["deadline"] or process["deadline"] < today:
                continue
            if not process["bases"]:
                raise SourceLayoutError(f"SADIM: {process['code']} está abierto pero no enlaza sus bases")
            text = read_pdf(http, process["bases"], f"SADIM, bases de {process['code']}")
            self._texts[process["code"]] = text
            contract = CONTRACT.search(text)
            temporary = bool(contract) and "indefinid" not in contract.group(1).lower()
            offers.append(ListedOffer(
                ref=process["code"], title=process["title"].capitalize(), company=COMPANY, url=PAGE,
                apply_url=process["bases"], kind="temporal" if temporary else "indefinido",
                positions=process["positions"],
                category="Tasa de reposición" if "tasa de reposición" in text.lower() else None,
                deadline=process["deadline"].isoformat(), deadline_time=process["deadline_time"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        text = self._texts.get(offer.ref)
        if text is None:
            return OfferDetail()
        place = LOCALITY.search(text)
        deadline = date.fromisoformat(offer.deadline).strftime("%d/%m/%Y") if offer.deadline else None
        lines = [f"<li><strong>Inscripción hasta:</strong> {deadline}</li>"] if deadline else []
        sections = [{"title": "Documentos de la convocatoria", "level": 2,
                     "html": sanitize(f'<ul><li><a href="{escape(offer.apply_url, quote=True)}">Bases de la convocatoria</a></li></ul>')}]
        if lines:
            sections.insert(0, {"title": "Datos del puesto", "level": 2, "html": sanitize(f"<ul>{''.join(lines)}</ul>")})
        return OfferDetail(sections=sections, location=_clean(place.group(1)) if place else None)
