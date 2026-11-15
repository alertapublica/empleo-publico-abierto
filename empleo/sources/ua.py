"""Universidad de Alicante: plazas de personal investigador y técnico para proyectos de investigación.

El Servicio de Selección y Formación (`ssp.ua.es/es/selecinvest/`) publica dos tablones: personal
investigador («I-PI 87-26»: en formación, colaborador, júnior) y personal técnico («I-PTGAI 55-26»:
tecnólogo, especialista). Cada convocatoria es un puesto con su ficha. Las tarjetas del tablón (40 y
23 el 2026-11-15, sin paginar, de la más nueva a la más antigua) traen el código («Convocatoria I-PI
87-26»), un párrafo con el puesto y el proyecto, que es el título literal, el departamento o instituto
y la fecha de publicación en el DOGV. Las convocatorias siguen en el tablón hasta dos meses después
de su última resolución.

La ficha trae la resolución de la convocatoria («…para la contratación temporal/indefinida…», de
donde sale el contrato), la categoría, el enlace a las bases en el DOGV y la pestaña «Solicitudes» con
«PLAZO DE PRESENTACIÓN DE SOLICITUDES: Del 09 al 20 de noviembre de 2026» (sin hora). El plazo se abre
al día siguiente de la publicación y dura unas dos semanas, así que solo se abren las fichas
publicadas en los últimos `HORIZON_DAYS` días (decidido con el usuario el 2026-11-15). La pestaña
«Resoluciones» (listas de personas) no se lee. Las fichas antiguas redirigen al login de UACloud: se
saltan. La solicitud es un trámite común de la sede en el que se elige la convocatoria: se enlaza la
ficha, que lo explica. Alguna tarjeta trae una errata en el código («I-PI 79-25» enlaza a la 79-26):
vale el de la ficha. Del informe de Codex (encargo 26, 2026-11-14).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from bs4 import BeautifulSoup

from ..dates import numeric_date, spanish_date
from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://ssp.ua.es/es/selecinvest/"
LISTS = (
    SITE + "03-personal-investigador/actual/plazas-personal-investigador-para-proyectos-de-investigacion.html",
    SITE + "04-personal-tecnico/actual/plazas-personal-tecnico-para-proyectos-investigacion.html",
)
COMPANY = "Universidad de Alicante"
HORIZON_DAYS = 60
FICHA = re.compile(r"^https://ssp\.ua\.es/es/selecinvest/0[34]-[a-z-]+/(\d{4})/([a-z]+\d+)/[\w.-]+\.html$")
CODE = re.compile(r"^Convocatoria\s+(I-[A-Z]+\s+\d+-\d+)$")
DAY = re.compile(r"\d{2}/\d{2}/\d{4}")
PERIOD = re.compile(
    r"PLAZO DE PRESENTACI[ÓO]N DE SOLICITUDES:\s*Del\s+(\d{1,2})(?:\s+de\s+([a-záéíóú]+))?(?:\s+de\s+(\d{4}))?"
    r"\s+al\s+(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.I)
CONTRACT = re.compile(r"contrataci[óo]n (temporal|indefinida)", re.I)
KINDS = {"temporal": "temporal", "indefinida": "indefinido"}


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_list(html: str) -> list[dict]:
    cards = BeautifulSoup(html, "html.parser").select("div.noticia__contenedor-contenido")
    if not cards:
        raise SourceLayoutError("Universidad de Alicante: el tablón no tiene convocatorias")
    found = []
    for card in cards:
        link, day = card.select_one("h3 a[href]"), card.select_one(".noticia__fecha")
        paragraphs = [_clean(p.get_text(" ")) for p in card.select(".card-text p")]
        paragraphs = [p for p in paragraphs if p]
        address = FICHA.match(link["href"]) if link else None
        code = CODE.match(_clean(link.get_text(" "))) if link else None
        published = DAY.fullmatch(_clean(day.get_text(" "))) if day else None
        if not (address and code and published and paragraphs):
            raise SourceLayoutError(f"Universidad de Alicante: tarjeta sin enlace, código, fecha o puesto "
                                    f"({_clean(card.get_text(' '))[:120]!r})")
        department = paragraphs[1] if len(paragraphs) > 1 and not paragraphs[1].startswith("Fecha") else None
        found.append({
            "ref": f"{address.group(1)}-{address.group(2)}", "url": link["href"], "code": code.group(1),
            "title": paragraphs[0].removesuffix("."), "department": department.removesuffix(".") if department else None,
            "published_on": numeric_date(published.group(0)),
        })
    return found


def _period(text: str) -> tuple[str, str]:
    """Inicio y fin del plazo. Si la pestaña da más de uno (una reapertura), el que acaba más tarde."""
    periods = []
    for found in PERIOD.finditer(text):
        first_day, first_month, first_year, last_day, last_month, last_year = found.groups()
        last = spanish_date(last_day, last_month, last_year)
        first = spanish_date(first_day, first_month or last_month, first_year or last_year)
        if first and last and first > last and not first_year:  # «Del 22 de diciembre al 9 de enero de 2027»
            first = spanish_date(first_day, first_month or last_month, int(last_year) - 1)
        if first is None or last is None or first > last:
            raise SourceLayoutError(f"Universidad de Alicante: plazo imposible: {found.group(0)!r}")
        periods.append((last.isoformat(), first.isoformat()))
    if not periods:
        raise SourceLayoutError("Universidad de Alicante: ficha sin plazo de presentación legible")
    last, first = max(periods)
    return first, last


def parse_ficha(html: str) -> dict | None:
    """Datos de la ficha; None si la UA ya la ha retirado tras el login de UACloud."""
    soup = BeautifulSoup(html, "html.parser")
    main = soup.find(id="contenido-pagina")
    if main is None:
        if "autentica.cpd.ua.es" in html or "UACloud" in _clean(soup.title.get_text(" ") if soup.title else ""):
            return None
        raise SourceLayoutError("Universidad de Alicante: ficha sin contenido")
    heading, resolution = main.find("h1"), main.find("h2")
    code = CODE.match(_clean(heading.get_text(" "))) if heading else None
    if code is None or resolution is None:
        raise SourceLayoutError("Universidad de Alicante: ficha sin código o sin resolución")
    contract = CONTRACT.search(_clean(resolution.get_text(" ")))
    category = main.select_one(".badge.text-bg-success")

    def outside(section) -> bool:
        return section.find_parent(class_="col-md-3") is None and section.find_parent(attrs={"data-name": "pestanyas"}) is None

    blocks = [s for s in main.select('section[data-type="component-tiny-text-ua"]') if outside(s)]
    for title in main.find_all(["h2", "h3", "h4", "h5", "h6"]):
        title.name = "p"  # la ficha no tiene más títulos que el suyo: son párrafos destacados
    sections = [{"title": "Convocatoria", "level": 2,
                 "html": sanitize("".join(s.decode_contents() for s in blocks))}]
    data = main.select_one(".col-md-3 section[data-type='component-tiny-text-ua']")
    if data is not None:
        sections.append({"title": "Datos de la convocatoria", "level": 2, "html": sanitize(data.decode_contents())})
    tabs = {}
    for button in main.select("ul.nav-tabs button[aria-controls]"):
        pane = main.find(id=button["aria-controls"])
        name = _clean(button.get_text(" "))
        if pane is not None and name != "Resoluciones":  # listas de personas
            tabs[name] = pane
            sections.append({"title": name, "level": 2, "html": sanitize(pane.decode_contents())})
    if "Solicitudes" not in tabs:
        raise SourceLayoutError("Universidad de Alicante: ficha sin la pestaña «Solicitudes»")
    first, last = _period(_clean(tabs["Solicitudes"].get_text(" ")))
    return {
        "code": code.group(1), "opens_on": first, "deadline": last,
        "contract": contract.group(0) if contract else None,
        "kind": KINDS[contract.group(1).lower()] if contract else None,
        "category": _clean(category.get_text(" ")) if category else None,
        "sections": [s for s in sections if s["html"]],
    }


class UaSource(Source):
    id = "ua"
    name = "Universidad de Alicante"
    homepage = SITE
    scope = "Comunitat Valenciana"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud en la web oficial"
    required_sections = ("Convocatoria", "Solicitudes")

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}
        self._rows: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        oldest = (now.astimezone(MADRID).date() - timedelta(days=HORIZON_DAYS)).isoformat()
        offers = []
        for page in LISTS:
            for row in parse_list(http.get(page)):
                if row["published_on"] < oldest:
                    continue
                ficha = parse_ficha(http.get(row["url"]))
                if ficha is None or deadline_passed(ficha["deadline"], None, now):
                    continue
                self._fichas[row["ref"]], self._rows[row["ref"]] = ficha, row
                offers.append(ListedOffer(
                    ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                    kind=ficha["kind"], contract=ficha["contract"], category=ficha["category"], code=ficha["code"],
                    opens_on=ficha["opens_on"], deadline=ficha["deadline"],
                ))
        return offers

    def enrich(self, http: Client) -> dict[str, dict]:
        # La fecha del DOGV va aquí y no en el listado: el motor solo pide estos datos a las ofertas que
        # no la tienen, y así entra también el departamento (la ficha no lo da).
        return {ref: {"published_on": row["published_on"], "department": row["department"]}
                for ref, row in self._rows.items()}

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        if ficha is None:
            return None
        # Sin lugar de trabajo en la ficha (hay sedes fuera de Alicante): queda el ámbito de la fuente.
        return OfferDetail(sections=ficha["sections"])
