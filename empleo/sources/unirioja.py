"""Universidad de La Rioja: contratos con cargo a proyectos y contratos de investigación de «Talento investigador».

Dos páginas del Servicio de Gestión de la Investigación (WordPress con Elementor): «Contrato Cargo a
Proyectos» (técnicos para un proyecto) y «Talento Investigador» (contratos de investigación para la
captación de talento, por área). Cada convocatoria es un bloque (`div.bloque-texto`), de la más nueva a
la más antigua y sin ficha propia: la resolución resumida, el investigador o las bases, «Plazo
(de) presentación (de) solicitudes: del 11 de noviembre al 25 de noviembre de 2026» (también «del 9 al
23 de junio de 2026», «del 14 al 28 noviembre de 2025» o «desde el 12 de septiembre hasta el 13 de
octubre de 2026»; sin hora) y los documentos en SharePoint: la convocatoria del BOR (con su fecha, que
es la de publicación), el impreso de solicitud y, después, las listas y el acta. Cada bloque que convoca
(«se convoca», «se anuncia») o trae un plazo tiene que traer un plazo y solo uno: si no, se detiene la
fuente. Los demás (avisos, «Convocatoria pendiente de publicación») se saltan (revisión de Codex, 51).

Entran los bloques en plazo (decidido con el usuario el 2026-11-16, opción C). Fuera: el PDI (la página
«PDI no permanente» y la aplicación `aps.unirioja.es/contratacionPDI` solo traen profesorado), las becas
de iniciación, las ayudas de movilidad y los contratos predoctorales y posdoctorales; el PTGAS va por
FileMaker WebDirect, sin plazos en el HTML, y la Fundación es otra fuente (centinela).

Título (decisión del 2026-11-16): «categoría · proyecto», como en la UHU. En proyectos, la categoría es lo
que va delante de los dos puntos («TÉCNICA/O: se convoca…», con `humane_caps`) y el proyecto, lo que
sigue a «titulado:», sin comillas; su referencia («08-01-ID26», «TESTACOS+», «PID2024-161126NB-I00») va
a `code` y, en minúsculas, es el identificador. En talento, la categoría es «Contrato de investigación
para la captación de talento» y el área, la última frase de la resolución («Computación Científica»);
identificador, el número de la resolución. Un bloque en plazo que no encaje detiene la fuente (el
formato antiguo, «Resolución 1903/2025… de un técnico…», solo está en bloques cerrados). La ficha copia
el bloque entero. Municipio: Logroño.

Red: www.unirioja.es se lee directa y, si falla, por el Worker de Madrid (`RESPALDO_CF`): la Fundación
y aps.unirioja.es dan 429 a Actions. Sondeo de Codex (encargo 40, inventario9) y lectura puntual del
2026-11-16 (1 en plazo: 08-01-ID26).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..dates import spanish_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from ..text import humane_caps
from .base import Source

SITE = "https://www.unirioja.es/administracion-y-servicios/servicio-de-gestion-de-la-investigacion"
PROYECTOS = SITE + "/contrato-cargo-a-proyectos/"
TALENTO = SITE + "/talento/"
COMPANY = "Universidad de La Rioja"
TALENT_CATEGORY = "Contrato de investigación para la captación de talento"
MONTH = r"[a-záéíóú]+"
PERIOD = re.compile(
    rf"Plazo (?:de )?presentación (?:de )?solicitudes\s*:\s*(?:del|desde el)\s+(\d{{1,2}})(?:\s+de)?"
    rf"(?:\s+({MONTH}))?(?:\s+de\s+(\d{{4}}))?\s+(?:al|hasta el)\s+(\d{{1,2}})\s+(?:de\s+)?({MONTH})\s+de\s+(\d{{4}})",
    re.I)
BOR = re.compile(rf"convocatoria(?: BOR)?\s*\((?:BOR\s+)?(\d{{1,2}}) de ({MONTH}) de (\d{{4}})\)", re.I)
PROJECT = re.compile(r"^([^:]{3,40}):\s*se convoca\b.*?\bProyecto (?:de referencia )?(.+?),?\s+titulado:?\s*(.+)$")
TALENT = re.compile(r"\bconvocatoria de contratos de investigación para la captación de talento\b.*\.\s*([^.]+?)\.?$")
CALL = re.compile(r"\bse (?:convoca|anuncia)\b|\bplazo\b", re.I)  # bloque de convocatoria, no un aviso
RESOLUTION = re.compile(r"^Resolución (?:número )?(\d+)/(\d{4})\b")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _period(text: str) -> tuple[str, str]:
    """Primer y último día del plazo; detiene si no hay exactamente uno o no es una fecha válida."""
    found = PERIOD.findall(text)
    if len(found) != 1:
        raise SourceLayoutError(f"Universidad de La Rioja: bloque con {len(found)} plazos ({text[:120]!r})")
    day1, month1, year1, day2, month2, year2 = found[0]
    end = spanish_date(day2, month2, year2)
    start = spanish_date(day1, month1 or month2, year1 or year2) if end else None
    if start and not year1 and start > end:  # «del 20 de diciembre al 3 de enero de 2027»
        start = spanish_date(day1, month1, int(year2) - 1)
    if not (start and end) or start > end:
        raise SourceLayoutError(f"Universidad de La Rioja: plazo ilegible ({text[:160]!r})")
    return start.isoformat(), end.isoformat()


def parse_blocks(html: str) -> list[dict]:
    """Todos los bloques de la página, con el plazo y la fecha del BOR; el título se lee aparte."""
    blocks = BeautifulSoup(html, "html.parser").select("div.bloque-texto")
    if not blocks:
        raise SourceLayoutError("Universidad de La Rioja: la página no tiene bloques de convocatoria")
    found = []
    for block in blocks:
        text = _clean(block.get_text(" "))
        if not CALL.search(text):
            continue
        opens_on, deadline = _period(text)
        bor = BOR.search(text)
        published = spanish_date(*bor.groups()) if bor else None
        first = block.find("p")
        found.append({"lead": _clean(first.get_text(" ")) if first else "", "opens_on": opens_on,
                      "deadline": deadline, "published_on": published.isoformat() if published else None,
                      "html": sanitize(block.decode_contents())})
    return found


def _project_title(lead: str) -> tuple[str, str, str]:
    """(ref, título, código) de un contrato con cargo a proyecto."""
    match = PROJECT.match(lead)
    if not match:
        raise SourceLayoutError(f"Universidad de La Rioja: contrato en plazo sin categoría o proyecto ({lead[:160]!r})")
    category, code, name = (_clean(g) for g in match.groups())
    name = name.rstrip(".").strip().strip("“”\"").strip()
    return re.sub(r"[^a-z0-9]+", "-", code.lower()).strip("-"), f"{humane_caps(category)} · {humane_caps(name)}", code


def _talent_title(lead: str) -> tuple[str, str, None]:
    """(ref, título, sin código) de un contrato de talento."""
    match, number = TALENT.search(lead), RESOLUTION.match(lead)
    if not (match and number):
        raise SourceLayoutError(f"Universidad de La Rioja: contrato de talento en plazo sin área o resolución "
                                f"({lead[:160]!r})")
    return f"talento-{number.group(1)}-{number.group(2)}", f"{TALENT_CATEGORY} · {match.group(1)}", None


PAGES = ((PROYECTOS, _project_title), (TALENTO, _talent_title))


class UniriojaSource(Source):
    id = "unirioja"
    name = COMPANY
    homepage = PROYECTOS
    scope = "La Rioja"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._blocks: dict[str, str] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        self._blocks = {}
        offers = []
        for page, title_of in PAGES:
            for block in parse_blocks(http.get(page)):
                if deadline_passed(block["deadline"], None, now):
                    continue
                ref, title, code = title_of(block["lead"])
                if ref in self._blocks:
                    raise SourceLayoutError(f"Universidad de La Rioja: dos convocatorias en plazo con el mismo "
                                            f"identificador ({ref})")
                self._blocks[ref] = block["html"]
                offers.append(ListedOffer(
                    ref=ref, title=title, company=COMPANY, url=page, apply_url=page, kind=None,
                    deadline=block["deadline"], opens_on=block["opens_on"], published_on=block["published_on"],
                    code=code,
                ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        html = self._blocks.get(offer.ref) or self._find(http, offer)
        if html is None:
            return None
        return OfferDetail(location="Logroño", sections=[{"title": "La convocatoria", "level": 2, "html": html}])

    @staticmethod
    def _find(http: Client, offer: ListedOffer) -> str | None:
        """El bloque de la oferta en su página, en plazo o no (sin la caché de `list_offers`)."""
        title_of = dict(PAGES).get(offer.url)
        for block in parse_blocks(http.get(offer.url)) if title_of else []:
            try:
                if title_of(block["lead"])[0] == offer.ref:
                    return block["html"]
            except SourceLayoutError:  # bloques antiguos con otro formato
                continue
        return None
