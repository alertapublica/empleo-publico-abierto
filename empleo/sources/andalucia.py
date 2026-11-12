"""Junta de Andalucía: ofertas de empleo de las entidades instrumentales.

Un solo portal (Drupal) con las convocatorias de personal laboral de agencias, fundaciones,
sociedades mercantiles y consorcios del sector público andaluz, desde noviembre de 2019. El listado
con «Sólo convocatorias en plazo de solicitud» (`field_ofem_fecha_fin_value[1]=1`) y 50 por página
trae una tabla con el puesto, el contrato, el estado y la entidad, y arriba «14 recursos
disponibles»: las filas leídas tienen que cuadrar con esa cifra (con más de 50, se pasa de página;
más de `MAX_PAGES`, se detiene). Sin ninguna, «No se encontraron resultados coincidentes…».

La ficha tiene campos con nombre fijo: tipo de convocatoria, código (no siempre, y a veces es un
texto como «Según convocatoria en la Agencia»), fecha de publicación, «Plazo de solicitud:
09/11/2026 - 20/11/2026» (sin hora), plazas, lugar de trabajo («Camas (Sevilla)»), contrato literal,
titulaciones, otros requisitos, funciones y «Convocatoria y bases de la oferta» (bases, BOJA y, a
veces, el enlace de inscripción). La API de datos abiertos (`datos.juntadeandalucia.es`) trae lo
mismo, pero sin el nombre de la entidad (solo un código técnico), sin el inicio del plazo y sin
los documentos: por eso se lee el HTML. El estado «En curso» no sigue el plazo: mandan las fechas.

Se leen las ofertas de empleo, las de estabilización, las ofertas genéricas del SAE (la persona se
inscribe a través del Servicio Andaluz de Empleo) y las bolsas. No se leen la promoción interna,
las entidades que tienen fuente propia (FISEVI, FIBAO, VEIASA) ni lo que publican las consejerías
como tales (administración general, no empresas): solo entidades con forma de agencia, fundación,
sociedad, consorcio, empresa, escuela o instituto en el nombre. Una convocatoria subida varias veces
(mismo organismo, código, plazo y lugar, como las cuatro «2487» de Progreso y Salud del 2026-11-12) se
publica una vez. Sondeo del 2026-11-12, a partir del informe de Codex (encargo 8).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.juntadeandalucia.es"
HOMEPAGE = SITE + "/organismos/transparencia/empleo-publico/entidades-instrumentales/ofertas-empleo.html"
PAGE = HOMEPAGE + "?field_ofem_fecha_fin_value%5B1%5D=1&items_per_page=50"
PER_PAGE = 50
MAX_PAGES = 4
EMPTY = "No se encontraron resultados coincidentes"
FIELD = "block-field-blocknodeofertas-de-empleo-de-las-eeiifield-"
# Tipo de convocatoria -> se lee o no.
TYPES = {
    "Oferta de empleo": True,
    "Oferta de empleo de estabilización": True,
    "Oferta genérica SAE": True,
    "Bolsa de trabajo": True,
    "Promoción interna": False,
}
OWN_SOURCE = re.compile(r"\((?:FISEVI|FIBAO)\)|Verificaciones Industriales de Andalucía", re.I)
ENTITY = re.compile(r"\b(?:Agencia|Fundación|Sociedad|Consorcio|Empresa|Escuela|Instituto)\b|\bS\.\s?A\b", re.I)
PLAZO = re.compile(r"(\d{2})/(\d{2})/(\d{4})\s*-\s*(\d{2})/(\d{2})/(\d{4})")
CODE = re.compile(r"[\w./-]*\d[\w./-]*")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _day(d: str, m: str, y: str) -> str:
    return date(int(y), int(m), int(d)).isoformat()


def parse_list(html: str) -> tuple[int, list[dict]]:
    """(total que anuncia la página, filas de esta página)."""
    soup = BeautifulSoup(html, "html.parser")
    rows = soup.select("table tbody tr")
    summary = soup.select_one(".view-header__summary")
    if not rows:
        empty = soup.select_one(".view-empty")
        if empty is None or EMPTY not in _clean(empty.get_text(" ")):
            raise SourceLayoutError(f"Junta de Andalucía: listado sin tabla y sin «{EMPTY}»")
        return 0, []
    total = re.fullmatch(r"(\d+) recursos? disponibles?", _clean(summary.get_text(" "))) if summary else None
    if total is None:
        raise SourceLayoutError("Junta de Andalucía: no se lee cuántas convocatorias hay en plazo")
    found = []
    for row in rows:
        link = row.select_one("td[headers=view-field-ofem-denominacion-puesto-table-column] a[href]")
        entity = row.select_one("td[headers=view-field-organismo-table-column]")
        ref = re.search(r"/detalle/(\d+)\.html$", link["href"]) if link else None
        if ref is None or entity is None or not _clean(entity.get_text(" ")):
            raise SourceLayoutError("Junta de Andalucía: fila sin enlace a la ficha o sin entidad")
        found.append({"ref": ref.group(1), "url": urljoin(SITE, link["href"]),
                      "title": _clean(link.get_text(" ")), "entity": _clean(entity.get_text(" "))})
    return int(total.group(1)), found


def _block(soup: BeautifulSoup, name: str):
    return soup.find("div", class_=FIELD + name)


def _text(soup: BeautifulSoup, name: str) -> str | None:
    block = _block(soup, name)
    items = block.select(".field__item") if block else []
    return "; ".join(_clean(i.get_text(" ")) for i in items) or None


def _html(soup: BeautifulSoup, name: str) -> str:
    block = _block(soup, name)
    item = block.select_one(".field__item") if block else None
    return item.decode_contents() if item else ""


def parse_ficha(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    kind = _text(soup, "ofem-tipo-convocatoria")
    if kind not in TYPES:
        raise SourceLayoutError(f"Junta de Andalucía: tipo de convocatoria desconocido: {kind!r}")
    plazo = PLAZO.fullmatch(_text(soup, "ofem-fecha-ini") or "")
    if plazo is None:
        raise SourceLayoutError("Junta de Andalucía: ficha sin «Plazo de solicitud» con inicio y fin")
    published = _block(soup, "ofem-fecha-publi")
    published = published.find("time") if published else None
    places = _text(soup, "ofem-num-plazas")
    code = _text(soup, "ofem-codigo")
    sections = []
    data = [(label, _text(soup, name)) for label, name in (
        ("Tipo de convocatoria", "ofem-tipo-convocatoria"),
        ("Perfil del puesto de trabajo", "ofem-perfil-puesto-trabajo"),
        ("Titulación oficial requerida", "ofem-titulacion-oficial"),
        ("Titulación específica requerida", "ofem-titulacion-esp"))]
    lines = "".join(f"<p><strong>{escape(label)}:</strong> {escape(value)}</p>" for label, value in data if value)
    sections.append({"title": "Datos de la convocatoria", "level": 2, "html": sanitize(lines)})
    for title, name in (("Funciones", "ofem-funciones"), ("Otros requisitos", "ofem-otros-req")):
        body = _html(soup, name)
        if _clean(BeautifulSoup(body, "html.parser").get_text(" ")):
            sections.append({"title": title, "level": 2, "html": sanitize(body)})
    documents = []
    block = _block(soup, "ofem-convocatoria")
    for link in block.select("a[href]") if block else []:
        label = _clean(link.get_text(" ")) or _clean(link.get("title", ""))
        if label:
            documents.append(f'<li><a href="{escape(urljoin(SITE, link["href"]), quote=True)}">{escape(label)}</a></li>')
    if documents:
        sections.append({"title": "Convocatoria y bases de la oferta", "level": 2,
                         "html": sanitize(f"<ul>{''.join(documents)}</ul>")})
    return {
        "type": kind, "read": TYPES[kind],
        "opens_on": _day(*plazo.group(1, 2, 3)), "deadline": _day(*plazo.group(4, 5, 6)),
        "published_on": published["datetime"][:10] if published and published.get("datetime") else None,
        "positions": int(places) if places and places.isdigit() else None,
        "code": code if code and CODE.fullmatch(code) else None,
        "location": _text(soup, "ofem-lugartrabajo"),
        "contract": _text(soup, "ofem-tipo-contrato"),
        "sections": sections,
    }


def kind_of(announcement: str, contract: str | None) -> str | None:
    """Clave de KINDS solo si el tipo o el contrato lo dicen claro."""
    if announcement == "Bolsa de trabajo":
        return "bolsa"
    if not contract:
        return None
    if contract.startswith("Indefinido"):
        return "indefinido"
    if contract == "Duración determinada- prácticas":
        return "practicas"
    if contract.startswith("Duración determinada"):
        return "temporal"
    return None


class AndaluciaSource(Source):
    id = "andalucia"
    name = "Junta de Andalucía (entidades instrumentales)"
    homepage = HOMEPAGE
    scope = "Andalucía"
    apply_label = "Ver la convocatoria y cómo inscribirse"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def _rows(self, http: Client) -> list[dict]:
        total, rows = parse_list(http.get(PAGE))
        page = 1
        while len(rows) < total:
            if page >= MAX_PAGES:
                raise SourceLayoutError(f"Junta de Andalucía: más de {MAX_PAGES * PER_PAGE} convocatorias en plazo")
            more = parse_list(http.get(f"{PAGE}&page={page}"))[1]
            if not more:
                break
            rows += more
            page += 1
        if len(rows) != total:
            raise SourceLayoutError(f"Junta de Andalucía: se leen {len(rows)} convocatorias y la página dice {total}")
        return rows

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers, seen = [], set()
        for row in sorted(self._rows(http), key=lambda r: int(r["ref"])):
            if OWN_SOURCE.search(row["entity"]) or not ENTITY.search(row["entity"]):
                continue
            ficha = parse_ficha(http.get(row["url"]))
            if not ficha["read"] or deadline_passed(ficha["deadline"], None, now):
                continue
            if ficha["code"]:
                key = (row["entity"], ficha["code"], ficha["opens_on"], ficha["deadline"], ficha["location"])
                if key in seen:  # la misma convocatoria subida otra vez
                    continue
                seen.add(key)
            title, source_title = row["title"], None
            if ficha["code"]:
                bare = re.fullmatch(rf"(.+?)\s*-\s*{re.escape(ficha['code'])}", title)
                if bare:
                    title, source_title = bare.group(1), row["title"]
            self._fichas[row["ref"]] = ficha
            offers.append(ListedOffer(
                ref=row["ref"], title=title, company=row["entity"], url=row["url"], apply_url=row["url"],
                kind=kind_of(ficha["type"], ficha["contract"]), positions=ficha["positions"],
                deadline=ficha["deadline"], opens_on=ficha["opens_on"], published_on=ficha["published_on"],
                contract=ficha["contract"], code=ficha["code"], source_title=source_title,
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        return OfferDetail(sections=ficha["sections"], location=ficha["location"])
