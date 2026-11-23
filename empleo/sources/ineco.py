"""Ineco (Ingeniería y Economía del Transporte), sociedad mercantil estatal.

Ofertas ordinarias: ePreselec (`ineco.epreselec.com`, de InfoJobs), tras Imperva. A un cliente sin agente
de navegador le da 405 («Pardon Our Interruption»), y desde una IP doméstica ni contesta; desde el Worker
de relay/ y con agente de navegador da la página entera (comprobado el 16/11/2026). Es ASP.NET WebForms:

- El listado trae todas las ofertas en una página («Total ofertas: 197»): por oferta, `data_idOferta`
  (el `ref`), «28942 - Técnico/a…» (código y título; a veces sin guion), «(PLANTILLA / OFERTA)» o
  «(BECA)», «Madrid, España» (o solo el país: «Costa Rica», «Otros Países») y la fecha de publicación.
  Ningún plazo: la oferta sigue abierta mientras esté en el listado.
- La ficha se abre con `Ofertas.aspx?Id_Oferta=<data_idOferta>`, con guion bajo (`?IdOferta=` no): es la
  URL que el propio listado pone en la barra al abrir una ficha, y en GET y sin sesión el servidor la
  devuelve con el listado debajo (comprobado con Chromium el 16/11/2026). Es el enlace de cada oferta.
- Tras un centenar de fichas seguidas (primera lectura, 16/11/2026, entonces por postback), Imperva
  contesta a todo con «Pardon Our Interruption» y un captcha, también al Worker. Por eso cada lectura
  pide como mucho FICHAS_POR_LECTURA fichas (las pendientes, en las siguientes) y, al primer captcha,
  deja las demás.

Becas y ofertas fuera de España se leen como las demás; la web no las saca en la portada (site.off_front).

Sus convocatorias públicas (tasas de reposición) no van por ePreselec, sino por dos páginas de People
Experts: tasa de reposición ordinaria
(TRO) y específica (TRE, y las repescas de vacantes desiertas). Cada página es una sola landing de
4-5 MB con secciones `section-N`:

- «Inscríbete: Convocatoria - Relación de Puestos …»: un panel por bloque con la cabecera
  «CONVOCATORIA TRE26 – BLOQUE 2 SEPTIEMBRE (EN PROCESO DE RESOLUCIÓN)» y la tabla de puestos. En
  plazo, la cabecera da el cierre sin año («(INSCRIPCIÓN HASTA 11:59 DEL 12 DE JUNIO INCLUIDO – CLIQUE
  AQUÍ PARA INSCRIBIRSE)», captura del 7/6/2026) y la tabla gana la columna «INSCRÍBETE», que abre un
  formulario en la misma página. Los rótulos de la parte de arriba («Abierto el plazo…») se quedan
  sin actualizar: no se usan.
- «Comunicados TRO26», «COMUNICADOS TR-REPESCA»…: una sección por convocatoria, cada comunicado con
  «29/10/2026 (CONVOCATORIA TRE26 BLOQUE 1)» (a veces «25/02/26») y el título en el párrafo siguiente.
  La etiqueta de bloque es irregular («BLOQUES 2 y 3», «BLOQUE 1 DIRECTIVOS», o ninguna): por eso el
  proceso es la convocatoria, no el bloque.
- «Listados …»: relaciones de personas. No se leen.

Un proceso por sección de comunicados. Su estado sale de las cabeceras de sus bloques: abierto si
alguno está en plazo, finalizado si todos dicen «RESUELTO», en curso si no. Una cabecera con otro
rótulo es un cambio de la página. Acceso libre: «Podrá optar cualquier persona que cumpla con lo
establecido en las bases» (ineco.com, ofertas de empleo público).
"""
from __future__ import annotations

import re
from datetime import date, datetime

from bs4 import BeautifulSoup

from ..dates import clock, spanish_date
from ..http import Client
from ..model import MADRID, Announcement, ListedOffer, OfferDetail, SourceLayoutError, selection_system
from ..sanitize import sanitize
from .base import Source

ORDINARIA = "https://inecoreposicionordinaria.people-experts.com/ineco"
ESPECIFICA = "https://inecoreposicionespecifica.people-experts.com/ineco"
PAGES = (ORDINARIA, ESPECIFICA)

CODE = r"TR[OE]\s?\d{2}|TR-REPESCA(?:[\s-]*\d+)?"
COMUNICADOS = re.compile(rf"^comunicados\s+({CODE})$", re.I)
HEADER = re.compile(rf"^CONVOCATORIA\s+({CODE})\s*[-–]\s*.+?\(([^()]*)\)\.?$", re.I)
OPEN = re.compile(
    r"^INSCRIPCI[ÓO]N HASTA\s+(?:LAS\s+)?(?:(\d{1,2}[:.]\d{2})\s*(?:H(?:ORAS)?\.?\s*)?)?(?:(?:DEL?|EL)\s+)?"
    r"(?:D[ÍI]A\s+)?(\d{1,2})\s+DE\s+([A-ZÁÉÍÓÚ]+)(?:\s+DE\s+(\d{4}))?\b", re.I)
STAMP = re.compile(r"^(\d{1,2})/(\d{1,2})/(\d{4}|\d{2})\b")
NAMES = {"TRO": "Tasa de reposición ordinaria", "TRE": "Tasa de reposición específica"}

EPRESELEC = "https://ineco.epreselec.com/Ofertas/Ofertas.aspx"
TOTAL = re.compile(r"Total ofertas:\s*(\d+)")
PUBLISHED = re.compile(r"^(\d{1,2}) de ([a-záéíóú]+),\s*(\d{4})$", re.I)
OFFER_TYPES = {"PLANTILLA / OFERTA": None, "BECA": "beca"}
FICHAS_POR_LECTURA = 20
IMPERVA = "Pardon Our Interruption"
# Apartados de la ficha, en su orden: id del `span` y título.
DETAIL_SECTIONS = (("lCentroOficina", "Oficina"), ("lDescripcionEmpresa", "Descripción"),
                   ("lFunciones", "Funciones"), ("lRequisitos", "Requisitos"), ("lSeOfrece", "Se ofrece"))


def _text(node) -> str:
    return " ".join(node.get_text(" ").split())


def _key(code: str) -> str:
    return re.sub(r"[\s-]", "", code).upper()


def process_name(code: str) -> str:
    """«TRE26» → «Tasa de reposición específica 2026 (TRE26)»."""
    found = re.fullmatch(r"(TR[OE])\s?(\d{2})", code, re.I)
    if found:
        return f"{NAMES[found.group(1).upper()]} 20{found.group(2)} ({code})"
    return f"Repesca de tasas de reposición ({code})"


def _deadline(label: str, today: date) -> tuple[str, str | None]:
    """Cierre de un bloque en plazo. Sin año, el más cercano a hoy (el bloque está abierto)."""
    found = OPEN.match(label)
    if not found:
        raise SourceLayoutError(f"Ineco: plazo ilegible en «{label}»")
    hour, day, month, year = found.groups()
    years = [int(year)] if year else [today.year - 1, today.year, today.year + 1]
    days = [d for d in (spanish_date(day, month, y) for y in years) if d]
    if not days:
        raise SourceLayoutError(f"Ineco: fecha imposible en «{label}»")
    closest = min(days, key=lambda d: abs((d - today).days))
    return closest.isoformat(), clock(hour)


def _block(anchor, today: date) -> tuple[str, dict]:
    """Convocatoria («TRO26») y estado de un bloque, por su cabecera."""
    label = _text(anchor)
    found = HEADER.match(label)
    if not found:
        raise SourceLayoutError(f"Ineco: cabecera de bloque inesperada «{label}»")
    status = found.group(2).strip()
    upper = status.upper()
    if upper == "RESUELTO":
        block = {"state": "finalizado"}
    elif upper.startswith("EN PROCESO DE RESOLUCI"):
        block = {"state": "curso"}
    elif upper.startswith("INSCRIPCI"):
        deadline, hour = _deadline(status, today)
        block = {"state": "abierto", "deadline": deadline, "deadline_time": hour}
    else:
        raise SourceLayoutError(f"Ineco: estado de bloque desconocido «{status}»")
    return found.group(1), block


def block_states(soup: BeautifulSoup, today: date) -> dict[str, list[dict]]:
    """Bloques de cada convocatoria (clave sin espacios ni guiones) con su estado."""
    blocks: dict[str, list[dict]] = {}
    for anchor in soup.select(".panel-title a"):
        code, block = _block(anchor, today)
        blocks.setdefault(_key(code), []).append(block)
    return blocks


def _blocks_of(code: str, blocks: dict[str, list[dict]]) -> list[dict]:
    key = _key(code)
    if key[-1].isdigit():
        return blocks.get(key, [])
    # «COMUNICADOS TR-REPESCA» reúne las repescas numeradas («TR-REPESCA 2 – ENERO»).
    return [b for name, found in blocks.items() if name.startswith(key) for b in found]


def _state(blocks: list[dict], today: date) -> dict:
    opened = [b for b in blocks if b["state"] == "abierto" and b["deadline"] >= today.isoformat()]
    if opened:
        last = max(opened, key=lambda b: (b["deadline"], b["deadline_time"] or "99:99"))
        return {"state": "abierto", "deadline": last["deadline"], "deadline_time": last["deadline_time"]}
    if blocks and all(b["state"] == "finalizado" for b in blocks):
        return {"state": "finalizado"}
    return {"state": "curso"}


def _stamp(text: str) -> str | None:
    found = STAMP.match(text)
    if not found:
        return None
    day, month, year = found.groups()
    return date(int(year if len(year) == 4 else f"20{year}"), int(month), int(day)).isoformat()


def _heading(paragraph) -> bool:
    """Párrafo que es un rótulo: todo en negrita y en mayúsculas («… BLOQUES 1 y 2 …» vale).

    Hay frases del cuerpo en negrita («Se recuerda la necesidad de concurrir a las pruebas…»).
    """
    text = _text(paragraph)
    strong = " ".join("".join(node.get_text() for node in paragraph.find_all(["strong", "b"])).split())
    letters = [char for char in text if char.isalpha()]
    lower = sum(char.islower() for char in letters)
    return bool(letters) and strong == text and lower <= len(letters) * 0.05


def comunicados(section, process: str) -> list[tuple[str, str]]:
    """(fecha, título) de cada comunicado de una sección.

    Cada entrada empieza con «29/10/2026 (CONVOCATORIA TRE26 BLOQUE 1)». Los rótulos que siguen
    (negrita en mayúsculas) son sus comunicados: una entrada puede llevar varios del mismo día; sin
    ninguno, el comunicado es el primer párrafo. Las entradas vienen sin cerrar y se anidan: de cada una solo
    cuentan sus párrafos propios, y el contenedor de la sección (sin párrafos propios) se salta.
    """
    found = []
    for entry in section.select("div.col-sm-12"):
        paragraphs = [p for p in entry.find_all("p", recursive=False) if _text(p)]
        if not paragraphs:
            continue
        published = _stamp(_text(paragraphs[0]))
        if not published or len(paragraphs) < 2:
            raise SourceLayoutError(f"Ineco: comunicado sin fecha o sin título en {process}")
        titles = [_text(p) for p in paragraphs[1:] if _heading(p)] or [_text(paragraphs[1])]
        found.extend((published, title) for title in titles)
    return found


def parse_page(html: str, page: str, today: date) -> list[Announcement]:
    soup = BeautifulSoup(html, "html.parser")
    blocks = block_states(soup, today)
    phases = soup.select_one("section#section-0")
    system = selection_system(_text(phases)) if phases else None
    contract = "indefinido" if re.search(r"puestos de trabajo indefinidos", soup.get_text(" "), re.I) else None
    items = []
    sections = 0
    for section in soup.select("section[id^=section-]"):
        heading = section.find("h2")
        found = COMUNICADOS.match(_text(heading)) if heading else None
        if not found:
            continue
        sections += 1
        code = found.group(1)
        process = process_name(code)
        state = _state(_blocks_of(code, blocks), today)
        for published, title in comunicados(section, process):
            items.append(Announcement(
                date=published, process=process, title=title, url=f"{page}#{section['id']}",
                via="tasa", access="libre", contract=contract, system=system, process_url=page,
                apply_url=page if state["state"] == "abierto" else None, **state,
            ))
    if not sections:
        raise SourceLayoutError(f"Ineco: sin secciones de comunicados en {page}")
    return items


def offer_url(ref: str) -> str:
    return f"{EPRESELEC}?Id_Oferta={ref}"


def _published(text: str) -> str:
    found = PUBLISHED.match(text)
    day = spanish_date(*found.groups()) if found else None
    if day is None:
        raise SourceLayoutError(f"Ineco (ePreselec): fecha de publicación ilegible «{text}»")
    return day.isoformat()


def parse_list(html: str, company: str) -> list[ListedOffer]:
    """Ofertas del listado de ePreselec."""
    soup = BeautifulSoup(html, "html.parser")
    total = TOTAL.search(_text(soup.select_one(".total-vacancies") or soup))
    if not total:
        raise SourceLayoutError("Ineco (ePreselec): sin «Total ofertas» (¿página de Imperva?)")
    offers = []
    for link in soup.select("a[data_idoferta]"):
        parts = {name: link.select_one(f".op-{name}") for name in ("titulo", "tipooferta", "provincia", "fecha")}
        if not all(parts.values()):
            raise SourceLayoutError(f"Ineco (ePreselec): oferta incompleta {link['data_idoferta']}")
        kind_text = _text(parts["tipooferta"]).strip("()")
        if kind_text not in OFFER_TYPES:
            raise SourceLayoutError(f"Ineco (ePreselec): tipo de oferta desconocido «{kind_text}»")
        place = _text(parts["provincia"])
        ref = link["data_idoferta"]
        offers.append(ListedOffer(
            ref=ref, title=_text(parts["titulo"]), company=company,
            url=offer_url(ref), apply_url=offer_url(ref), kind=OFFER_TYPES[kind_text],
            published_on=_published(_text(parts["fecha"])),
            country=place.rpartition(",")[2].strip(),
        ))
    if len(offers) != int(total.group(1)):
        raise SourceLayoutError(f"Ineco (ePreselec): {len(offers)} ofertas y el total dice {total.group(1)}")
    return offers


def _span(soup: BeautifulSoup, name: str):
    return soup.select_one(f"#ctl00_CPH_Body_{name}")


def parse_detail(soup: BeautifulSoup, ref: str) -> OfferDetail | None:
    """Ficha de la oferta `ref`, o None si la respuesta no es esa ficha."""
    anchor = soup.select_one(".onepage-oferta h1 a[name]")
    if anchor is None or anchor["name"] != ref:
        return None
    sections = []
    for name, title in DETAIL_SECTIONS:
        node = _span(soup, name)
        if node is not None and _text(node):
            sections.append({"title": title, "level": 2, "html": sanitize(f"<p>{node.decode_contents()}</p>")})
    if not any(section["title"] == "Funciones" for section in sections):
        raise SourceLayoutError(f"Ineco (ePreselec): ficha {ref} sin funciones")
    positions = _text(_span(soup, "lNumVacantes") or soup.new_tag("i"))
    province = _span(soup, "lProvinciaText")
    return OfferDetail(sections=sections, location=_text(province) if province is not None else None,
                       positions=int(positions) if positions.isdigit() else None)


class InecoSource(Source):
    id = "ineco"
    name = "Ineco"
    homepage = "https://www.ineco.com/ineco/talento/ofertas-de-empleo-publico"
    title_code = re.compile(r"(?P<code>\d{5})\s*-?\s*(?P<title>\S.*)")
    delay = 5.0  # fichas pesadas (el listado entero cada vez) tras Imperva: sin prisa

    def __init__(self):
        self._fichas = 0  # fichas pedidas en esta lectura
        self._blocked = False  # Imperva ya ha pedido captcha en esta lectura

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._fichas, self._blocked = 0, False
        return parse_list(http.get(EPRESELEC), self.name)

    def _page(self, html: str) -> BeautifulSoup:
        if IMPERVA in html:
            self._blocked = True
            raise SourceLayoutError("Ineco (ePreselec): captcha de Imperva; las fichas que faltan, en otra lectura")
        return BeautifulSoup(html, "html.parser")

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        if self._blocked or self._fichas >= FICHAS_POR_LECTURA:
            return None  # sigue pendiente: se lee en la lectura siguiente
        self._fichas += 1
        detail = parse_detail(self._page(http.get(offer_url(offer.ref))), offer.ref)
        if detail is None:
            raise SourceLayoutError(f"Ineco (ePreselec): ?Id_Oferta= no devuelve la ficha {offer.ref}")
        return detail

    def list_announcements(self, http: Client, now: datetime | None = None) -> list[Announcement]:
        today = (now or datetime.now(MADRID)).astimezone(MADRID).date()
        items = []
        for page in PAGES:
            items += parse_page(http.get(page), page, today)
        return items
