"""FNMT-RCM (Fábrica Nacional de Moneda y Timbre – Real Casa de la Moneda).

Liferay. «Ofertas de Empleo Público / Empleo Fijo» (`/ofertas-de-empleo/ofertas-de-empleo-publico`)
lista 20 procesos por página, sin fechas, ordenados por su última modificación; cada uno lleva su
id de recurso (`span.asset-anchor`), que crece con la fecha de alta. La ficha (el enlace tal cual:
sin `p_r_p_assetEntryId` da «El usuario no existe») es una lista de comunicados en PDF con su fecha
(«(26-10-26) Aviso de convocatoria»). La «Bolsa de empleo» publica las bolsas resultantes (listas
de personas): no se lee.

Un proceso es oferta si todos sus comunicados son de convocatoria (aviso inicial o de convocatoria,
bases, ampliación o corrección) y el plazo que da el aviso («estará abierto desde el día 27 de
octubre hasta el 18 de noviembre de 2026») o, sin aviso, las bases, no ha vencido. El plazo se busca
tras «plazo de presentación» y solo vale entre el primer comunicado y 60 días después. Las fichas se
leen de la más nueva a la más antigua y se para en la primera que ya tiene otras fases (máx. 8; si
se llega al máximo, la fuente se detiene). Clave: id del recurso; las referencias `OE` y `FC` quedan en el título. Contrato: el texto de
la ficha tras «en régimen de». Detalle: el párrafo de presentación de la ficha, tal cual (dice el puesto y el departamento).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import latest
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..pdftext import deadlines_at, read_pdf
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.fnmt.es"
PAGE = f"{SITE}/ofertas-de-empleo/ofertas-de-empleo-publico"
COMPANY = "Fábrica Nacional de Moneda y Timbre – Real Casa de la Moneda"
NOTICE = re.compile(r"\((\d{2})-(\d{2})-(\d{2})\)")
CALL = re.compile(r"^(aviso (inicial|de convocatoria)|bases|ampliaci[oó]n de plazo|correcci[oó]n de errores)\b", re.I)
NOTICE_FIRST = re.compile(r"^aviso", re.I)
PLAZO = re.compile(r"plazo de presentaci[oó]n", re.I)
CONTRACT = re.compile(r"en régimen de (.+?)\.?$")
MAX_FICHAS = 8
MAX_PLAZO = 60


def parse_list(html: str) -> list[dict]:
    """Procesos del listado, del alta más reciente a la más antigua."""
    cells = BeautifulSoup(html, "html.parser").select("table.table-list td.table-title")
    if not cells:
        raise SourceLayoutError("FNMT: no se encuentra la tabla de procesos")
    found = []
    for cell in cells:
        anchor, link = cell.select_one("span.asset-anchor[id]"), cell.select_one("a[href]")
        if anchor is None or link is None or not anchor["id"].isdigit():
            raise SourceLayoutError("FNMT: fila sin id o enlace")
        found.append({"id": int(anchor["id"]), "title": " ".join(link.get_text().split()), "url": link["href"]})
    return sorted(found, key=lambda p: p["id"], reverse=True)


def parse_ficha(html: str) -> dict:
    article = BeautifulSoup(html, "html.parser").select_one(".asset-full-content .journal-content-article")
    if article is None:
        raise SourceLayoutError("FNMT: ficha sin contenido")
    intro = article.select_one("p")
    contract = CONTRACT.search(" ".join(intro.get_text().split())) if intro else None
    documents = []
    for item in article.select("li"):
        link, when = item.select_one("a[href]"), NOTICE.search(item.get_text())
        if link is None or when is None:
            raise SourceLayoutError("FNMT: comunicado sin enlace o fecha")
        day, month, year = when.groups()
        documents.append({"label": " ".join(link.get_text().split()), "url": urljoin(SITE, link["href"]),
                          "date": date(2000 + int(year), int(month), int(day))})
    if not documents:
        raise SourceLayoutError("FNMT: ficha sin comunicados")
    return {"documents": documents, "contract": contract.group(1) if contract else None,
            "intro": sanitize(str(intro)) if intro else ""}


def deadline_in(text: str, first: date) -> tuple[date, str | None] | None:
    """Fin de plazo tras «plazo de presentación», si cae en un margen verosímil."""
    found = [
        (day, hour) for start in PLAZO.finditer(text)
        for day, hour in deadlines_at(text[start.start():start.start() + 400])
        if first <= day <= first + timedelta(days=MAX_PLAZO)
    ]
    return latest(found) if found else None


class FnmtSource(Source):
    id = "fnmt"
    name = "FNMT-RCM"
    homepage = PAGE
    title_code = re.compile(r"(?P<code>OE\s+\d+/\d+)\s*-\s*(?P<title>.+)")  # «OE 25/26 - Médico de Empresa»
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"
    detail_version = 2  # el detalle es el párrafo de la ficha (#30)

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for count, process in enumerate(parse_list(http.get(PAGE)), 1):
            if count > MAX_FICHAS:
                raise SourceLayoutError(f"FNMT: las {MAX_FICHAS} fichas más nuevas siguen en convocatoria")
            ficha = parse_ficha(http.get(process["url"]))
            documents = ficha["documents"]
            if not all(CALL.match(d["label"]) for d in documents):
                break  # ya tiene otras fases: las anteriores, también
            source = next((d for d in documents if NOTICE_FIRST.match(d["label"])), documents[0])
            first = min(d["date"] for d in documents)
            text = read_pdf(http, source["url"], f"FNMT, {source['label']} de {process['title']}")
            found = deadline_in(text, first)
            if found is None or deadline_passed(found[0].isoformat(), found[1], now):
                continue
            offers.append(ListedOffer(
                ref=str(process["id"]), title=process["title"], company=COMPANY, url=process["url"], apply_url=process["url"],
                kind=None, contract=ficha["contract"], published_on=first.isoformat(),
                deadline=found[0].isoformat(), deadline_time=found[1],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        intro = parse_ficha(http.get(offer.url))["intro"]
        return OfferDetail(sections=[{"title": "Convocatoria", "level": 2, "html": intro}] if intro else [])
