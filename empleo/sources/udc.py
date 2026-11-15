"""Universidade da Coruña: convocatorias de contratación con cargo a proyectos de investigación (PCTI).

Se publican en el tablón de la sede electrónica (`sede.udc.gal`, sin robots.txt), categoría «Anuncios
institucionais» (`/services/electronic_board/category/7`, 15 anuncios por página, `?page=N`, del más nuevo al
más antiguo), mezcladas con sus resoluciones, listas, actas y correcciones y con otros anuncios. Cada convocatoria
es un contrato: «Conv. contrat. 2026/CP/263. Facultade de Dereito» (263 en 2026, unas 25 al mes). La fecha del
tablón no trae año («10 nov»): se toma el del día y, si queda en el futuro, el anterior. Se leen páginas hasta
pasar `WINDOW_DAYS` días (máximo `MAX_PAGES`).

La ficha (`/services/electronic_board/EXP2026/NNNNNN`) da «Data de publicación: 10/11/2026», el título y, detrás,
la categoría y la jornada («Colaborador de investigación a tempo completo»), y el anuncio en PDF (GL y ES). El
título es «categoría · centro» (los dos, literales de la ficha) y el código, «2026/CP/263»; si la ficha no trae la
categoría así, el título del tablón.

**El plazo no se publica como fecha.** El PDF dice «PLAZO: 5 días hábiles a partir del día siguiente al de la
publicación en el tablón de anuncios de la Sede electrónica de la UDC» (las 7 de la muestra del 2026-11-15). La
fecha se calcula (decidido con el usuario el 2026-11-15) y la web la marca como calculada (`deadline_rule`):
hábiles son los días que no son sábado, domingo ni festivo del calendario oficial de la sede
(`/info/official_calendar`, un PDF por año). El órgano está en A Coruña: sus festivos locales son inhábiles para
todos (art. 30.6 de la Ley 39/2015); los de Ferrol y Oleiros solo alargan el plazo a quien vive allí, y el 24 y
el 31 de diciembre (oficinas cerradas) y el 30 de enero (día de la Universidade) son dudosos: cuentan como hábiles,
y así sale la fecha más temprana posible. Un año sin calendario en `HOLIDAYS` detiene la fuente.

El listado no da plazo: con los 5 días solo decide qué convocatorias siguen abiertas (y no abre la ficha de las
vencidas). La fecha y la regla las pone la ficha, que lee el PDF una sola vez (`fetch_detail`; pesa unos 400 KB),
y solo si su texto dice literalmente «PLAZO: 5 días hábiles a partir del día siguiente al de la publicación en el
tablón…»: otro número de días, otra redacción o un año sin calendario dejan la oferta con «Plazo: no consta» y la
ficha avisa (revisión de Codex, respuesta45). Del PDF se copia también el título del proyecto. Dos plantillas de
PDF: una de ellas (LaTeX) separa las tildes («d ´ ıas h´ abiles»): se recomponen. Correcciones de una convocatoria
abierta («Corrección erros»): se enlazan en la ficha si ya están al leerla (una posterior no llega: la ficha no se
relee) y no cambian el plazo.
Sin municipio: hay centros en A Coruña y en Ferrol.
"""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..pdftext import read_pdf
from ..sanitize import sanitize
from .base import Source

SITE = "https://sede.udc.gal"
INDEX = SITE + "/services/electronic_board/category/7"
COMPANY = "Universidade da Coruña"
WINDOW_DAYS = 14  # 5 hábiles con Semana Santa o Navidad caben en unos 11 días naturales
MAX_PAGES = 12
DAYS = 5
RULE = ("5 días hábiles a partir del día siguiente al de la publicación en el tablón de anuncios de la Sede "
        "electrónica de la UDC")
# Calendario oficial de la sede: festivos nacionales y de Galicia y locales de A Coruña.
HOLIDAYS = {
    2026: {"01-01", "01-06", "02-17", "03-19", "04-02", "04-03", "05-01", "06-24", "07-25", "08-15", "10-07",
           "10-12", "12-08", "12-25"},
}
MONTHS = {**{m: n for n, m in enumerate("xan feb mar abr mai xuñ xul ago set out nov dec".split(), 1)},
          **{m: n for n, m in enumerate("ene feb mar abr may jun jul ago sep oct nov dic".split(), 1)}}
EXP = re.compile(r"/services/electronic_board/EXP\d{4}/\d+$")
CALL = re.compile(r"^Conv(?:oc)?\.?\s+contrat(?:ación|\.)?\s+(\d{4}/CP/\d+)\.?\s+(.+?)\.?$", re.I)
NOT_CALL = re.compile(r"resoluci|listax|\blista|\bacta\b|rvit|\bvit\b|correcc|cualific|calific|admitid|renuncia|"
                      r"proposta|propuesta|baremo|desist|rectific|entrevist|anula|modific|desert|adxudic|adjudic|"
                      r"puntua|recurso", re.I)
CORRECTION = re.compile(r"correcc", re.I)
PUBLISHED = re.compile(r"Data de publicación:\s*(\d{2}/\d{2}/\d{4})")
# En castellano o en gallego (algún anuncio «ES» va en gallego: 2026/CP/260).
PLAIN_RULE = re.compile(r"(?:plazo|prazo):\s*(\d+) dias habiles a partir d(?:el dia siguiente al de la|o dia seguinte ao da) "
                        r"publicacion (?:en el tablon|no taboleiro) de anuncios d(?:e la|a) sede electronica d(?:e la|a) udc")
LITERAL_RULE = re.compile(r"(?:PLAZO|PRAZO):\s*(\d+ días hábiles a partir d(?:el día siguiente al de la|o día seguinte ao da) "
                          r"publicación (?:en el tablón|no taboleiro) de anuncios d(?:e la|a) Sede electrónica d(?:e la|a) UDC)",
                          re.I)
PROJECT = re.compile(r"Título:\s*(.+?)\s+(?:Línea|Liña) de investigación\s*(?::|/)")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def business_deadline(published: date, days: int = DAYS) -> date:
    """Último día de «N días hábiles a partir del día siguiente al de la publicación»."""
    day, counted = published, 0
    while counted < days:
        day += timedelta(days=1)
        if day.year not in HOLIDAYS:
            raise SourceLayoutError(f"Universidade da Coruña: falta el calendario oficial de {day.year} (HOLIDAYS)")
        if day.weekday() < 5 and day.strftime("%m-%d") not in HOLIDAYS[day.year]:
            counted += 1
    return day


def _board_day(day: str, month: str, today: date) -> date:
    number = MONTHS.get(month.lower().rstrip("."))
    if number is None:
        raise SourceLayoutError(f"Universidade da Coruña: mes desconocido en el tablón ({month!r})")
    found = date(today.year, number, int(day))
    return found if found <= today else date(today.year - 1, number, int(day))


def parse_board(html: str, today: date) -> list[dict]:
    items = BeautifulSoup(html, "html.parser").select("li.announcement")
    if not items:
        raise SourceLayoutError("Universidade da Coruña: el tablón está vacío")
    found = []
    for item in items:
        day, month, link = item.select_one(".day"), item.select_one(".month"), item.select_one(".link a[href]")
        if not (day and month and link and EXP.search(link["href"])):
            raise SourceLayoutError(f"Universidade da Coruña: anuncio sin fecha o sin enlace ({_clean(item.get_text(' '))[:120]!r})")
        found.append({"date": _board_day(_clean(day.get_text()), _clean(month.get_text()), today),
                      "title": _clean(link.get("title") or link.get_text(" ")), "url": urljoin(SITE, link["href"])})
    return found


def next_page(html: str, current: int) -> str | None:
    """Siguiente página del tablón, si el paginador la ofrece."""
    soup = BeautifulSoup(html, "html.parser")
    wanted = f"page={current + 1}"
    return INDEX + f"?{wanted}" if soup.select_one(f'a[href$="{wanted}"]') else None


def parse_ficha(html: str) -> dict:
    box = BeautifulSoup(html, "html.parser").select_one("#announcement")
    published = PUBLISHED.search(_clean(box.get_text(" "))) if box else None
    title = box.select_one("h1") if box else None
    if not (published and title):
        raise SourceLayoutError("Universidade da Coruña: ficha sin «Data de publicación» o sin título")
    heading = _clean(title.get_text(" "))
    texts = [text for p in box.select("p") if "date" not in (p.get("class") or []) and (text := _clean(p.get_text(" ")))]
    # «título, categoría.», «título. categoría.» o la categoría en el párrafo de después del título (o sola).
    rest = [text for text in texts if text != heading]
    if rest and rest[0].startswith(heading):
        category = rest[0][len(heading):].strip(" ,.") or None
    else:
        category = rest[0].strip(" .") if len(rest) == 1 else None
    documents = [(_clean(a.get_text(" ")), urljoin(SITE, a["href"])) for a in box.select("ul a[href]")]
    pdf = next((url for label, url in documents if label.startswith("Anuncio ES")), None)
    pdf = pdf or next((url for label, url in documents if label.startswith("Anuncio")), None)
    return {"published_on": numeric_date(published.group(1)), "heading": heading, "category": category,
            "documents": documents, "pdf": pdf}


def repair(text: str) -> str:
    """Recompone las tildes que la plantilla LaTeX separa: «d ´ ıas h´ abiles» → «días hábiles»."""
    text = re.sub(r"\s?´\s?([aeiouAEIOUı])", lambda m: unicodedata.normalize("NFC", ("i" if m[1] == "ı" else m[1]) + "\u0301"), text)
    return unicodedata.normalize("NFC", text.replace("ı\u0301", "í").replace("ı", "i"))


def parse_pdf(text: str) -> dict:
    text = repair(_clean(text))
    plain = "".join(c for c in unicodedata.normalize("NFD", text.lower()) if not unicodedata.combining(c))
    rule = PLAIN_RULE.search(plain)
    literal = LITERAL_RULE.search(text)
    project = PROJECT.search(text)
    return {"days": int(rule.group(1)) if rule else None, "rule": literal.group(1) if literal else None,
            "project": project.group(1).strip(" .") if project else None}


class UdcSource(Source):
    id = "udc"
    name = "Universidade da Coruña"
    homepage = INDEX
    scope = "Galicia"
    text_lang = "gl"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}
        self._corrections: dict[str, list[tuple[str, str]]] = {}

    def _board(self, http: Client, today: date) -> list[dict]:
        oldest = today - timedelta(days=WINDOW_DAYS)
        found, url = [], INDEX
        for page in range(1, MAX_PAGES + 1):
            html = http.get(url)
            rows = parse_board(html, today)
            found += rows
            url = next_page(html, page)
            if url is None or rows[-1]["date"] < oldest:
                return found
        raise SourceLayoutError(f"Universidade da Coruña: más de {MAX_PAGES} páginas en {WINDOW_DAYS} días")

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        today = now.astimezone(MADRID).date()
        calls: dict[str, tuple[dict, str]] = {}
        for row in self._board(http, today):
            match = CALL.match(row["title"])
            if match is None:
                continue
            code = match.group(1)
            if CORRECTION.search(row["title"]):
                self._corrections.setdefault(code, []).append((row["title"], row["url"]))
            elif not NOT_CALL.search(match.group(2)) and code not in calls:  # la más nueva, si se republica
                calls[code] = (row, match.group(2))
        offers = []
        for code, (row, center) in calls.items():
            # Con la fecha del tablón se descartan las vencidas sin abrir su ficha.
            if deadline_passed(business_deadline(row["date"]).isoformat(), None, now):
                continue
            ref = code.replace("/", "-").lower()
            ficha = self._fichas[ref] = parse_ficha(http.get(row["url"]))
            deadline = business_deadline(date.fromisoformat(ficha["published_on"])).isoformat()
            if deadline_passed(deadline, None, now):
                continue
            title = f"{ficha['category']} · {center}" if ficha["category"] else row["title"]
            # Sin plazo en el listado: lo pone la ficha cuando el PDF confirma la regla. Si no la confirma,
            # la oferta queda con «Plazo: no consta», nunca con una fecha supuesta.
            offers.append(ListedOffer(
                ref=ref, title=title, company=COMPANY, url=row["url"], apply_url=row["url"], kind=None,
                published_on=ficha["published_on"], code=code,
                source_title=row["title"] if ficha["category"] else None,
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        if not ficha["pdf"]:
            raise SourceLayoutError("Universidade da Coruña: ficha sin el anuncio en PDF")
        found = parse_pdf(read_pdf(http, ficha["pdf"], f"Universidade da Coruña, anuncio {offer.code}"))
        if found["days"] != DAYS or not found["rule"]:
            # Otro número de días: el listado deja de ver la convocatoria a los cinco y la cerraría antes de tiempo.
            raise SourceLayoutError(f"Universidade da Coruña: el anuncio {offer.code} no dice «PLAZO: {DAYS} días hábiles "
                                    f"a partir del día siguiente al de la publicación en el tablón…» (días: {found['days']})")
        deadline = business_deadline(date.fromisoformat(ficha["published_on"])).isoformat()
        sections = []
        if found["project"]:
            sections.append({"title": "Proyecto", "level": 2, "html": f"<p>{escape(found['project'])}</p>"})
        rule = {"title": "Plazo de presentación", "level": 2, "html": f"<p>{escape(found['rule'])}.</p>"}
        if "seguinte" in found["rule"]:  # redactado en gallego
            rule["lang"] = self.text_lang
        sections.append(rule)
        documents = ficha["documents"] + self._corrections.get(offer.code or "", [])
        if documents:
            items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>' for label, url in documents)
            sections.append({"title": "Documentos", "level": 2, "html": sanitize(f"<ul>{items}</ul>")})
        return OfferDetail(sections=sections, deadline=deadline, deadline_rule=found["rule"])
