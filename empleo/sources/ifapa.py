"""IFAPA (Instituto Andaluz de Investigación y Formación Agraria, Pesquera, Alimentaria y de la
Producción Ecológica), agencia de la Junta de Andalucía.

«Empleo Público» (Drupal, en el servidor de la Junta) lista las convocatorias de la más nueva a la más
antigua, 10 por página (`?page=N`, unas 50 páginas): título literal («Convocatoria de contratos
laborales en el marco de proyectos específicos de I+D+F (BOJA 220, pág 14781) - Tit. FP - Inv -»),
tipo, BOJA, plazo («Del 16/11/2026 al 27/11/2026», en `<time datetime>`) y estado. El estado no sigue
las fechas (la 65479 dice «En plazo de presentación» antes de abrir): mandan las fechas. Se pasa de
página mientras la última fila siga en plazo; más de `MAX_PAGES`, se detiene. El 2026-11-15, 6 en
plazo (2 abren el día 16), todas en la primera página, y 6–8 convocatorias al mes.

La ficha (`/node/N`) trae la publicación en un campo y, en el cuerpo, «Se convoca 1 contrato
laboral.», «Proyecto IDF: PR.FEMPA.DIP2023A.003 Innovación y fomento…», «Centro: IFAPA Centro Agua del
Pino (Cartaya - Huelva).» y «Titulación: Técnico Superior: Personal técnico de apoyo de I+D. Nivel
FPII.» (hasta 400 caracteres; a veces la categoría acaba en punto, no en dos puntos). El plazo acaba «hasta las 24:00 horas» del último día: sin hora (el
último día cuenta entero) y el literal queda en la ficha.

Título (decisión del 2026-11-15): la categoría (lo que va antes de «:» en la titulación) y el
proyecto sin su código, separados por « · »; el código del proyecto va a `code` y el título del
portal a `source_title`. Si la ficha no tiene exactamente un bloque de proyecto así (varios contratos
distintos, sin ver), se publica con el título del portal y la ficha deja un aviso. Ubicación: el centro,
tal cual (el paréntesis no siempre es el lugar: «Centro IFAPA de Málaga (sede de Churriana)»). Sin procesos: las listas de candidatos son de personas.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.juntadeandalucia.es"
PAGE = SITE + "/agriculturaypesca/ifapa/web/personas-estructuras-y-servicios/empleo-publico"
COMPANY = "IFAPA"
MAX_PAGES = 3
BLOCK = re.compile(r"Proyecto IDF\s*:\s*(.+?)\s*Centro\s*:\s*(.+?)\s*Titulaci[óo]n\s*:\s*(.+)$", re.S)
# «PR.FEMPA.DIP2023A.003», «(PR.INTC.ATIDRAI26.004)», «(CAICEM 2025-180)», «CAICEM 192/2025»; el acrónimo
# sin cifras que a veces lo sigue («(ATIDRAI_AGRO)») es parte del nombre.
PROJECT_CODE = re.compile(r"^\(?(PR\.[\w.-]+|[A-Z]{2,}[\w.-]* \d[\d/.-]*)\)?\s+")
# Categoría: lo que va antes de «:» o del primer punto («Titulado Grado Medio. Ingeniería…»).
CATEGORY = re.compile(r"^([^:.]{3,40}?)\s*[:.]\s")
POSITIONS = re.compile(r"Se convoca\s*(\d+)\s*contratos?\b", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_list(html: str) -> list[dict]:
    rows = BeautifulSoup(html, "html.parser").select(".view-empleo-publico .views-row")
    found = []
    for row in rows:
        link, times = row.select_one(".views-field-title a[href]"), row.select(".views-field-nothing time[datetime]")
        kind = row.select_one(".views-field-field-tipo .field-content")
        if link is None or len(times) != 2:
            raise SourceLayoutError("IFAPA: fila sin enlace o sin plazo")
        url = urljoin(SITE, link["href"])
        found.append({
            "ref": url.rstrip("/").rsplit("/", 1)[-1], "url": url, "title": _clean(link.get_text(" ")),
            "type": _clean(kind.get_text(" ")) if kind else None,
            "opens_on": times[0]["datetime"][:10], "deadline": times[1]["datetime"][:10],
        })
    if not found:
        raise SourceLayoutError("IFAPA: el listado de empleo público está vacío")
    return found


def contract_of(body) -> dict | None:
    """Categoría · proyecto, código, plazas y lugar del único bloque «Proyecto IDF» del cuerpo."""
    blocks = [li for li in body.find_all("li") if "Proyecto IDF" in li.get_text()]
    match = BLOCK.search(_clean(blocks[0].get_text(" "))) if len(blocks) == 1 else None
    if match is None:
        return None
    project, centre, degree = (part.strip() for part in match.groups())
    category, code = CATEGORY.match(degree), PROJECT_CODE.match(project)
    name = project[code.end():] if code else project
    if category is None or not name:
        return None
    seats = POSITIONS.search(blocks[0].get_text(" "))
    return {"title": f"{category.group(1)} · {name.rstrip('. ')}", "code": code.group(1) if code else None,
            "positions": int(seats.group(1)) if seats else None, "location": centre.rstrip(". ")}


def parse_ficha(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".field--name-field-cuerpo")
    published = soup.select_one(".field--name-field-fecha time[datetime]")
    if body is None or published is None:
        raise SourceLayoutError("IFAPA: ficha sin cuerpo o sin fecha de publicación")
    boja = soup.select_one(".field--name-field-enlace a[href]")
    contract = contract_of(body)
    for note in body.find_all("div", recursive=False):  # «Atención: No puede garantizarse…»
        note.decompose()
    return {"published_on": published["datetime"][:10], "contract": contract, "body": sanitize(str(body)),
            "boja": (_clean(boja.get_text(" ")), boja["href"]) if boja else None}


class IfapaSource(Source):
    id = "ifapa"
    name = "IFAPA"
    homepage = PAGE
    scope = "Andalucía"
    delay = 4.0  # servidor de la Junta, compartido con `andalucia`; algún reset en el estudio 26
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def _open_rows(self, http: Client) -> list[dict]:
        now = self._now or datetime.now(timezone.utc)
        found = []
        for page in range(MAX_PAGES):
            rows = parse_list(http.get(PAGE if page == 0 else f"{PAGE}?page={page}"))
            found += [row for row in rows if not deadline_passed(row["deadline"], None, now)]
            if deadline_passed(rows[-1]["deadline"], None, now):
                return found
        raise SourceLayoutError(f"IFAPA: más de {MAX_PAGES} páginas con convocatorias en plazo")

    def list_offers(self, http: Client) -> list[ListedOffer]:
        offers = []
        for row in self._open_rows(http):
            ficha = self._fichas[row["ref"]] = parse_ficha(http.get(row["url"]))
            contract = ficha["contract"] or {}
            offers.append(ListedOffer(
                ref=row["ref"], title=contract.get("title") or row["title"], company=COMPANY, url=row["url"],
                apply_url=row["url"], kind=None, contract=row["type"], positions=contract.get("positions"),
                deadline=row["deadline"], opens_on=row["opens_on"], published_on=ficha["published_on"],
                code=contract.get("code"), source_title=row["title"] if contract else None,
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        # Aquí y no en el listado: la oferta sale con el título del portal y la ficha avisa y se relee.
        if ficha["contract"] is None:
            raise SourceLayoutError("IFAPA: ficha sin un único bloque «Proyecto IDF / Centro / Titulación»")
        sections = [{"title": "La convocatoria", "level": 2, "html": ficha["body"]}]
        if ficha["boja"]:
            text, url = ficha["boja"]
            sections.append({"title": "Publicación oficial", "level": 2,
                             "html": sanitize(f'<p><a href="{escape(url, quote=True)}">{escape(text)}</a></p>')})
        return OfferDetail(location=ficha["contract"]["location"], sections=sections)
