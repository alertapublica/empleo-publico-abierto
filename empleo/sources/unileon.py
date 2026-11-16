"""Universidad de León: plazas de personal investigador con cargo a proyectos y PTGAS laboral de acceso libre.

Listado único del Servicio de Recursos Humanos, «Convocatorias de selección o provisión de PTGAS/PDI/PI»
(`/convocatorias-ptgas-pdi`, Drupal 8, vista con filtros por GET y 20 tarjetas por página). Se pide filtrado
por «Tipo de Plaza» (1028 «PTGAS Laboral» y 1029 «Personal Investigador») y por «Fecha de resolución (igual o
mayor)», que en realidad filtra por la fecha de inicio del plazo: los últimos 120 días (los plazos de 2026 van
de una semana a 20 días hábiles). Se leen todas las páginas (`a[rel=next]`; más de MAX_PAGES detiene). El
filtro por «Estado» no sirve: hay tarjetas «ABIERTO» con el plazo de mayo vencido y otras «EN PROCESO» o
«FINALIZADO» según el día. Mandan las fechas.

Tarjeta (`div.panel.panel-primary`): tipo de plaza (cabecera), título literal enlazado a la ficha, «Desde:» y
«Hasta:» (`time[datetime]`, sin hora), «Sistema de acceso» y estado. Entran las de acceso «Libre»; «Bolsa»,
«Promoción Interna», «Consurso de Traslados» (sic) y «Transformaciones y Otras contrataciones temporales»
(atribuciones provisionales de funciones) se saltan (opción C, decidido con el usuario el 2026-11-16), y también
las que dicen «bolsa» en el título: «Convocatoria Bolsa Sucesiva convoca un nuevo plazo de incorporación a la
bolsa…» sale con acceso «Libre». Un tipo o un sistema desconocidos detienen la fuente.

Ficha: los mismos campos, el cuerpo (en las de investigación, «Podrán presentarse hasta las 12:00 horas del día
26 de noviembre de 2026, a través del formulario…»; en PTGAS, la resolución) y «Archivos Públicos» (PDF de la
convocatoria y luego listas y exámenes). La hora del cuerpo da `deadline_time`; si el cuerpo da otro día que la
tarjeta, se detiene. Publicación = la fecha de «Convocatoria (12/11/2026)» en los adjuntos, si está. Se copian el
cuerpo y los adjuntos (la tabla, como lista de enlaces).

Título (decisión del usuario del 2026-11-16): «categoría · Proyecto clave», como UHU, UJI y La Rioja. Literal:
«Convocatoria de [2 ]Plaza[s] de Personal con cargo al Proyecto AM250. Personal Técnico (TP 20 horas - 5
plazas)». El HTML no trae el nombre del proyecto, solo la clave (el nombre está en el PDF). Categoría = lo que
va tras el punto, con minúsculas fuera del paréntesis; el paréntesis, literal. Formato largo de mayo
(«CONVOCATORIA PÚBLICA PARA LA CONTRATACIÓN DE PERSONAL INVESTIGADOR Y TÉCNICO … CLAVE AG424_II»): «Personal
investigador y técnico · Clave AG424_II». La clave va a `code`. Otros formatos y el PTGAS: el literal con
`humane_caps`. Plazas: «2 Plazas» del título o «- 5 plazas» del paréntesis.

Identificador = slug de la ficha (Drupal añade «-1», «-2» a los repetidos). Sin municipio (León y Ponferrada).
Fuera: PDI (profesorado), PTGAS funcionario, bolsas y procesos internos. Sondeo (Codex, encargo 53) y lectura
puntual del 2026-11-16.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import numeric_date, spanish_date
from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from ..text import humane_caps
from .base import Source

SITE = "https://www.unileon.es"
LIST = SITE + "/convocatorias-ptgas-pdi"
TYPES = {"PTGAS Laboral": "1028", "Personal Investigador": "1029"}
COMPANY = "Universidad de León"
WINDOW_DAYS = 120
MAX_PAGES = 10
FREE = "Libre"
SKIPPED = {"Bolsa", "Promoción Interna", "Consurso de Traslados", "Concurso de Traslados",
           "Transformaciones y Otras contrataciones temporales"}
PROJECT = re.compile(r"^Convocatoria de (?:(?P<n>\d+) )?Plazas? de Personal con cargo al Proyecto (?P<code>.+?)\.\s+"
                     r"(?P<category>\S.*)$", re.I)
PUBLIC = re.compile(r"^CONVOCATORIA PÚBLICA PARA LA CONTRATACIÓN DE (?P<category>PERSONAL .+?) DE LA UNIVERSIDAD DE "
                    r"LEÓN CON CARGO A .+,\s*CLAVE (?P<code>\S+)$", re.I)
POOL = re.compile(r"\bbolsas?\b", re.I)  # «Bolsa Sucesiva…» va a veces con acceso «Libre»
PLACES = re.compile(r"\b(\d+) plazas\b", re.I)
UNTIL = re.compile(r"hasta las (\d{1,2})[:.](\d{2}) horas del día (\d{1,2}) de ([a-záéíóú]+) de (\d{4})", re.I)
CALL_FILE = re.compile(r"^Convocatoria \((\d{2}/\d{2}/\d{4})\)$")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def index_url(now: datetime) -> str:
    since = (now.astimezone(MADRID) - timedelta(days=WINDOW_DAYS)).strftime("%d-%m-%Y")
    types = "&".join(f"field_tipo_de_plaza_target_id%5B{n}%5D={n}" for n in TYPES.values())
    return f"{LIST}?{types}&field_fecha_de_inicio_value={since}"


def _day(card, label: str, title: str) -> str:
    for span in card.select("span.fechas"):
        if _clean(span.get_text(" ")).startswith(label):
            stamp = span.find("time")
            if stamp and re.match(r"\d{4}-\d{2}-\d{2}T", stamp.get("datetime", "")):
                return stamp["datetime"][:10]
    raise SourceLayoutError(f"ULE: «{title[:80]}» sin fecha «{label}» legible")


def parse_list(html: str) -> tuple[list[dict], str | None]:
    """Tarjetas de la página (todas, con su tipo y sistema) y la URL de la siguiente."""
    soup = BeautifulSoup(html, "html.parser")
    if soup.select_one("form#views-exposed-form-ule-list-contenido-page-7") is None:
        raise SourceLayoutError("ULE: la página no es el listado de convocatorias")
    rows = []
    for card in soup.select("div.panel.panel-primary"):
        kind, link = card.select_one("h4.panel-title"), card.select_one("h3 a[href]")
        access = card.select_one("div.proceso")
        if not (kind and link and access):
            raise SourceLayoutError(f"ULE: tarjeta sin tipo, título o sistema de acceso ({_clean(card.get_text(' '))[:120]!r})")
        title = _clean(link.get_text(" "))
        kind = _clean(kind.get_text(" "))
        if kind not in TYPES:
            raise SourceLayoutError(f"ULE: tipo de plaza inesperado {kind!r} en «{title[:80]}»")
        access = _clean(access.get_text(" ")).removeprefix("Sistema de acceso:").strip()
        if access != FREE and access not in SKIPPED:
            raise SourceLayoutError(f"ULE: sistema de acceso desconocido {access!r} en «{title[:80]}»")
        url = urljoin(LIST, link["href"])
        opens_on, deadline = _day(card, "Desde", title), _day(card, "- Hasta", title)
        if opens_on > deadline:
            raise SourceLayoutError(f"ULE: plazo al revés en «{title[:80]}» ({opens_on} > {deadline})")
        rows.append({"ref": url.rstrip("/").rsplit("/", 1)[-1], "kind": kind, "access": access, "title": title,
                     "url": url, "opens_on": opens_on, "deadline": deadline})
    following = soup.select_one("nav.pager-nav a[rel=next]")
    return rows, urljoin(LIST, following["href"]) if following else None


def _category(text: str) -> str:
    """«Personal Técnico (TP 20 horas)» → «Personal técnico (TP 20 horas)»: minúsculas fuera del paréntesis."""
    head, paren, rest = text.partition("(")
    head = head.strip()
    head = head[:1].upper() + head[1:].lower()
    return f"{head} {paren}{rest}".strip() if paren else head


def labels(row: dict) -> dict:
    literal = row["title"]
    project = PROJECT.match(literal) if row["kind"] == "Personal Investigador" else None
    public = PUBLIC.match(literal) if row["kind"] == "Personal Investigador" else None
    if project or public:
        found = project or public
        category = _category(found["category"])
        word = "Proyecto" if project else "Clave"
        places = project["n"] if project and project["n"] else None
        places = places or (PLACES.search(found["category"]).group(1) if PLACES.search(found["category"]) else None)
        return {"title": f"{category} · {word} {found['code']}", "category": category.split(" (")[0],
                "code": found["code"], "source_title": literal, "positions": int(places) if places else None}
    title = humane_caps(literal)
    return {"title": title, "category": None, "code": None, "source_title": None if title == literal else literal,
            "positions": None}


def parse_ficha(html: str, deadline: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    content = soup.select_one("div.region-content")
    title = content.select_one(".field--name-node-title") if content else None
    if title is None:
        raise SourceLayoutError("ULE: ficha sin título")
    title = _clean(title.get_text(" ")).removeprefix("Título").strip()
    body = content.select_one(".field--name-body")
    files = content.select_one(".field--name-field-archivos-publicos")
    text = _clean(body.get_text(" ")) if body else ""
    hours = set()
    for hour, minute, day, month, year in UNTIL.findall(text):
        found = spanish_date(day, month, year)
        if found is None or found.isoformat() != deadline:
            raise SourceLayoutError(f"ULE: la ficha de «{title[:80]}» da otro fin de plazo ({day} de {month} de "
                                    f"{year}; tarjeta: {deadline})")
        hours.add(f"{int(hour):02d}:{minute}")
    if len(hours) > 1:
        raise SourceLayoutError(f"ULE: la ficha de «{title[:80]}» da varias horas de cierre ({sorted(hours)})")
    published = []
    for a in files.select("a[href]") if files else []:
        match = CALL_FILE.match(_clean(a.get_text(" ")))
        if match:
            published.append(numeric_date(match.group(1)))
    parts = []
    if body is not None:
        for a in body.select("a[href]"):
            a["href"] = urljoin(LIST, a["href"])
        parts.append(body.decode_contents())
    links = [f'<li><a href="{escape(urljoin(LIST, a["href"]))}">{escape(_clean(a.get_text(" ")))}</a></li>'
             for a in (files.select("a[href]") if files else [])]
    if links:  # la tabla de Drupal, como lista de enlaces
        parts.append(f"<p>Archivos públicos:</p><ul>{''.join(links)}</ul>")
    if not parts:
        raise SourceLayoutError(f"ULE: la ficha de «{title[:80]}» no trae cuerpo ni adjuntos")
    return {"deadline_time": hours.pop() if hours else None, "published_on": min(published) if published else None,
            "html": sanitize("".join(parts))}


class UnileonSource(Source):
    id = "unileon"
    name = COMPANY
    homepage = LIST
    scope = "Castilla y León"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        rows, url = [], index_url(now)
        for _ in range(MAX_PAGES):
            found, url = parse_list(http.get(url))
            rows.extend(found)
            if url is None:
                break
        else:
            raise SourceLayoutError(f"ULE: más de {MAX_PAGES} páginas de convocatorias en {WINDOW_DAYS} días")
        offers, seen = [], set()
        for row in rows:
            if (row["ref"] in seen or row["access"] != FREE or POOL.search(row["title"])
                or deadline_passed(row["deadline"], None, now)):
                continue
            seen.add(row["ref"])
            ficha = parse_ficha(http.get(row["url"]), row["deadline"])
            if deadline_passed(row["deadline"], ficha["deadline_time"], now):
                continue
            self._fichas[row["ref"]] = ficha
            found = labels(row)
            offers.append(ListedOffer(
                ref=row["ref"], title=found["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                kind=None, positions=found["positions"], category=found["category"], code=found["code"],
                source_title=found["source_title"], published_on=ficha["published_on"], opens_on=row["opens_on"],
                deadline=row["deadline"], deadline_time=ficha["deadline_time"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url), offer.deadline)
        return OfferDetail(deadline_time=ficha["deadline_time"],
                           sections=[{"title": "La convocatoria", "level": 2, "html": ficha["html"]}])
