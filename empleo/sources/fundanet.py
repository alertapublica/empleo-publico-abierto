"""Fundanet «ConvocatoriasPropias»: IDIBELL, FISABIO, IDIVAL e i+12.

Las cuatro fundaciones usan la misma aplicación. El listado es una tabla de servidor
(`#GvConvocatorias`) con título, inicio y fin de la presentación de solicitudes, con hora
(«20/11/2026 23:59»), y en IDIBELL e IDIVAL una columna de estado. IDIBELL e IDIVAL listan
también las cerradas (cientos de filas, sin paginar); FISABIO e i+12 solo las abiertas (`Estado=A`).

Es oferta toda fila cuyo fin no ha pasado, con su hora; si aún no ha empezado, se guarda el
inicio. La columna de estado no se usa: mandan las fechas (el 2026-11-08 coincidían en todas
las filas). La inscripción se hace desde la propia ficha (botón «Crear Solicitud»).

La ficha (`VerConvocatoria/N`) trae el texto de la convocatoria (`div.InfoConvocatoria`) y los
documentos. Solo se enlazan las bases: entre los documentos puede haber listas de personas
(IDIVAL publica ahí «Admitidos y excluidos»). El contrato se toma literal de la ficha
(IDIBELL: «Contract duration: Permanent by project») o, en FISABIO e i+12, de sus bases en PDF
(«Tipo de contrato laboral: contrato indefinido», «• Contrato: Indefinido Art.23 Bis de la Ley
14/2011.»). IDIVAL no lo da en un campo fijo. En i+12 la ficha solo trae la categoría, el
investigador principal y la referencia: el puesto, las funciones y el perfil están en las bases.

La ubicación es la comunidad de la fundación: las fichas no dan un lugar de trabajo
uniforme. Sin ninguna abierta (i+12, 2026-11-13), la tabla trae una sola fila `tr.t-no-data` vacía:
es lista vacía; cualquier otra fila sin enlace o sin fechas detiene la lectura.

IDIBELL redacta las convocatorias en inglés: `/es/`, `/ca/` y `/en/` dan el mismo texto (solo
cambia la interfaz) y su web enlaza este listado. Se copian tal cual, marcadas `lang="en"`.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import clock, numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..pdftext import read_pdf
from ..sanitize import sanitize
from .base import Source

MOMENT = re.compile(r"(\d\d/\d\d/\d{4})\s+(\d{1,2}:\d\d)")
DETAIL = re.compile(r"/VerConvocatoria/(\d+)")
HEADERS = ("Título", "F.Inicio Presentación de Solicitudes", "F.Fin Presentación de Solicitudes")
CONTRACT = re.compile(r"^(?:Contract duration|Duración del contrato|Tipo de contrato)\s*:\s*(.+)$", re.I)
BASES_CONTRACT = re.compile(r"Tipo de contrato(?: laboral)?:\s*(.+?)\s+-\s", re.I)  # FISABIO
IMAS12_CONTRACT = re.compile(r"\bContrato:\s*(.+?)\s+[•\uf0b7]")  # viñeta «•» o la de Symbol


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _moment(text: str, what: str) -> tuple[str, str]:
    found = MOMENT.search(text)
    if not found:
        raise SourceLayoutError(f"{what}: fecha ilegible: {text!r}")
    return numeric_date(found.group(1)), clock(found.group(2))


def parse_listing(html: str, what: str) -> list[dict]:
    table = BeautifulSoup(html, "html.parser").find(id="GvConvocatorias")
    if table is None:
        raise SourceLayoutError(f"{what}: no se encuentra la tabla de convocatorias")
    rows = table.find_all("tr")
    headers = tuple(_text(th) for th in rows[0].find_all("th")) if rows else ()
    if headers[:3] != HEADERS:
        raise SourceLayoutError(f"{what}: columnas inesperadas: {headers}")
    if len(rows) == 2 and "t-no-data" in (rows[1].get("class") or []) and not _text(rows[1]):
        return []
    found = []
    for row in rows[1:]:
        cells = row.find_all("td")
        link = cells[0].find("a", href=DETAIL) if cells else None
        if link is None or len(cells) < 3:
            raise SourceLayoutError(f"{what}: fila sin enlace o sin fechas")
        opens_on, _ = _moment(_text(cells[1]), what)
        deadline, hour = _moment(_text(cells[2]), what)
        found.append({
            "ref": DETAIL.search(link["href"]).group(1), "title": _text(link), "href": link["href"],
            "opens_on": opens_on, "deadline": deadline, "deadline_time": hour,
        })
    return found


def parse_detail(html: str, base: str, lang: str | None = None) -> tuple[OfferDetail, str | None]:
    """Texto de la convocatoria y contrato literal; también el enlace a las bases."""
    soup = BeautifulSoup(html, "html.parser")
    info = soup.select_one("div.InfoConvocatoria")
    if info is None:
        raise SourceLayoutError("Fundanet: ficha sin el texto de la convocatoria")
    contract = None
    for node in info.find_all(["li", "p"]):
        match = CONTRACT.match(_text(node))
        if match:
            contract = match.group(1).rstrip(".").strip()
            break
    bases = next((a["href"] for a in soup.select("p.Documents a[href]")
                  if "DescargarDocumentoBases" in a["href"]), None)
    bases = urljoin(base, bases) if bases else None
    sections = [{"title": "Convocatoria", "level": 2, "html": sanitize(info.decode_contents())}]
    if lang:  # solo el texto de la fuente: «Documentos de la convocatoria» es nuestro
        sections[0]["lang"] = lang
    if bases:
        sections.append({"title": "Documentos de la convocatoria", "level": 2,
                         "html": sanitize(f'<ul><li><a href="{escape(bases, quote=True)}">Bases de la convocatoria</a></li></ul>')})
    return OfferDetail(sections=sections, contract=contract), bases


class FundanetSource(Source):
    apply_label = "Ver la convocatoria y presentar la solicitud"

    def __init__(self, id: str, name: str, listing: str, scope: str, bases_contract: re.Pattern | None = None,
                 title_code: re.Pattern | None = None, text_lang: str | None = None,
                 now: datetime | None = None) -> None:
        self.id = id
        self.name = name
        self.homepage = listing
        self.listing = listing
        self.scope = scope
        self.bases_contract = bases_contract
        self.title_code = title_code
        self.text_lang = text_lang
        if text_lang:
            self.detail_version = 2  # relee las fichas abiertas para marcar su idioma
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        return [
            ListedOffer(
                ref=row["ref"], title=row["title"], company=self.name,
                url=urljoin(self.listing, row["href"]), apply_url=urljoin(self.listing, row["href"]),
                kind=None, opens_on=row["opens_on"], deadline=row["deadline"],
                deadline_time=row["deadline_time"],
            )
            for row in parse_listing(http.get(self.listing), self.name)
            if not deadline_passed(row["deadline"], row["deadline_time"], now)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        detail, bases = parse_detail(http.get(offer.url), self.listing, self.text_lang)
        if self.bases_contract and bases and detail.contract is None:
            found = self.bases_contract.search(read_pdf(http, bases, f"{self.name}, bases de {offer.ref}"))
            detail.contract = found.group(1).rstrip(". ") if found else None
        detail.location = self.scope
        return detail


IDIBELL = FundanetSource(
    id="idibell", name="IDIBELL", scope="Cataluña", text_lang="en",  # redacta en inglés también en /es/
    title_code=re.compile(r"(?P<code>\d{2}-\d{3}_[A-Z]+_[A-Z]+)\s*(?:-\s+)?(?P<title>.+)"),  # «26-108_MS_XG …»
    listing="https://idibell.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/DetalleTipoConvocatoria/OE?Estado=T",
)
FISABIO = FundanetSource(
    id="fisabio", name="FISABIO", scope="Comunitat Valenciana", bases_contract=BASES_CONTRACT,
    # «2026/67 UN/A TÉCNICO/A DE INVESTIGACIÓN (T3) PLAZA 146 RPT»
    title_code=re.compile(r"(?P<code>\d{4}/\d+)\s+(?P<title>.+?)(?:\s+(?P<extra>PLAZA\s+\d+\s+RPT))?"),
    listing="https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/DetalleTipoConvocatoria/EMPLEO?Estado=A",
)
IDIVAL = FundanetSource(
    id="idival", name="IDIVAL", scope="Cantabria",
    title_code=re.compile(r"(?P<code>\d{4}\.\d+)\.?\s+(?P<title>.+)"),  # «2026.76. Convocatoria…»
    listing="https://aplicacionesidival.idival.org/ConvocatoriasPropias/es/Convocatorias/DetalleTipoConvocatoria/EMPLEO?Estado=T",
)
IMAS12 = FundanetSource(
    id="imas12", name="i+12 (FIBH12O)", scope="Comunidad de Madrid", bases_contract=IMAS12_CONTRACT,
    # Título literal («PERSONAL INVESTIGADOR( REF. 2611/14). DR. Rojo»): sin la referencia y el
    # investigador principal, seis de las dieciséis del 2026-11-12 serían «PERSONAL INVESTIGADOR».
    listing="https://fibh12o.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/DetalleTipoConvocatoria/rh?Estado=A",
)
