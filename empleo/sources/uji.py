"""Universitat Jaume I: plazas de personal investigador y tecnólogo con cargo a proyectos (tablón TAO).

Tablón de anuncios oficial de la sede (`/seu/info-adm/tao/`), categoría 14 «Convocatòries PI»: una sola
página de servidor, sin paginar, con todo el histórico (unas 560 convocatorias el 2026-11-16) agrupado por
subcategoría (`div.tao-box#tao-box-catNNNN`): «Places» de personal investigador predoctoral en formació
(1000), júnior (1001), tecnòleg o gestor superior (1010) y bàsic (1011), y «Altres processos… de places»
(PIPPI, PIPPT). Entran solo esas. Las «Borses» (2000–2011, PIPBI, PIPBT: procesos para formar una bolsa) se
saltan (decisión del usuario del 2026-11-16, regla de la opción C). Una subcategoría desconocida detiene la
fuente.

Cada convocatoria sale dos veces: la tarjeta visible y una copia oculta (`div.tao-concursos-pdi#convocatoria-
N`) que además enlaza sus concursos (`convocatoriesRH?pConv=N&pConcurso=1&pCategoria=14`). Se lee la oculta.
La tarjeta trae el título literal y, mientras hay un plazo en curso, «Inici de presentació de sol·licituds
13/11/26» y «Fi de presentació de sol·licituds 26/11/26» (año de dos cifras, sin hora) y un aviso «Queden 11
dies» que no se usa. Cerrada, dice «Disponible únicament per a consulta». **Ese plazo no es siempre el de
solicitudes**: es el «Termini» de la última resolución, y con la lista provisional de admitidos la tarjeta
enseña el de subsanación unas veces como «Inici termini d'esmena …» y otras con la misma etiqueta de
solicitudes (la 3563 el 2026-11-16: «sol·licituds» 04/11–17/11, cuando el plazo fue 14/10–27/10). Por eso la
tarjeta solo descarta (si su plazo ya pasó, el de solicitudes también) y el plazo lo da la ficha. Una tarjeta
sin ninguna de esas formas, o con un plazo ilegible o al revés, detiene. El 2026-11-16, 13 tarjetas con plazo
en curso y 10 en plazo de solicitudes (las otras tres, en subsanación).

La ficha (la del primer concurso) trae la «Data de resolució», el DOGV, el concurso («Concurs: Personal
investigador júnior») con «Inici/Fi de presentació de sol·licituds» (año entero), el «Codi Registre» (el número
del título) y las resoluciones con su «Data de publicació», su «Termini» y sus PDF. Plazo = el del concurso, que
debe coincidir con el «Termini» de la resolución «per la qual es convoca» (si no, o si hay varios, se detiene);
una resolución que amplía o modifica el plazo también detiene (sin casos vistos: revisar a mano). Publicación =
la primera «Data de publicació» (o la del DOGV). Se copia entera, en valenciano (`lang="ca"`).

Título (decisión del usuario del 2026-11-16): «categoría · proyecto», como UHU, IFAPA y La Rioja. Formato
actual del literal: «23207 plaça de personal investigador júnior per col·laborar en el projecte d'investigació:
“25I412 NOM DEL PROJECTE”, dirigit per … Grup d'investigació: …». Categoría = lo que va tras «plaça de» (el
nombre del concurso no es uniforme: «Plaça de personal tecnòleg…»); proyecto = lo que va entre comillas, con
`humane_caps` y su código tal cual («26I445»; algunos no lo llevan: «PECATHS - …»). El número de
delante va a `code` y el literal, a `source_title`. Formatos antiguos («22927 PROJECTE D'INVESTIGACIÓ 24I344.
GRUP D'INVESTIGACIÓ: …») y convocatorias con varios concursos («CONVOCATÒRIA ÚNICA: 08 CONTRACTES PREDOCTORALS
(PROGRAMA ESTATAL FPI-AEI 2026)»): el literal sin el número, con `humane_caps` y los códigos tal cual, y la
categoría del concurso si es uno solo.

Identificador: `pConv`. PTGAS fuera: su categoría (2) es funcionarial (escalas, concursos de puestos, bolsas de
interinos; la subcategoría «Places de personal laboral temporal» está «No activa»). Fundació: plazos relativos.
Ubicación: Castelló de la Plana (campus único). Robots.txt veta `/seu/`; se lee igual a su ritmo (decisión del
usuario). Sondeo de Codex (encargo 52) y HTML del 2026-11-16.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from ..text import humane_caps
from .base import Source

SITE = "https://www.uji.es"
INDEX = SITE + "/seu/info-adm/tao/?pFechaIni=&pFechaFin=&pCategoria=14&pTextoCercar=&pAccion="
COMPANY = "Universitat Jaume I"
PLACES = {"1000", "1001", "1010", "1011", "PIPPI", "PIPPT"}
POOLS = {"2000", "2001", "2002", "2010", "2011", "PIPBI", "PIPBT"}  # «Borses»: fuera
SHORT_DAY = r"(\d{2})/(\d{2})/(\d{2})"
OPENS = re.compile(r"Inici de presentació de sol·licituds\s+" + SHORT_DAY)
CLOSES = re.compile(r"Fi de presentació de sol·licituds\s+" + SHORT_DAY)
CLOSED = re.compile(r"Disponible únicament per a consulta|termini d['’]esmena")
TITLE = re.compile(r"^(?P<registry>\d+) plaça de (?P<category>.+?) per col·laborar en el projecte d['’]investigació:?\s*"
                   r"[“«\"](?:(?P<code>\S*\d\S*)\s+)?(?P<name>[^“”«»\"]+)[”»\"]\s*(?:,\s*dirigit per\b|\.\s)")
DAY = r"\d{2}/\d{2}/\d{4}"
CONVENES = re.compile(r"\bes convoca\b")
EXTENDS = re.compile(r"(?i)\bampli\w*\b.{0,60}\btermini\b|\btermini\b.{0,60}\bampli\w*\b|\bmodifica\w*\b.{0,60}\btermini\b")
REGISTRY = re.compile(r"^(\d+)\s+")
CODES = re.compile(r"\S*\d\S*")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _caps(text: str) -> str:
    """`humane_caps` sin tocar los códigos con cifras («24I344», «FPI-AEI 2026»)."""
    result = humane_caps(text)
    for code in set(CODES.findall(text)):
        result = re.sub(re.escape(code), lambda _, code=code: code, result, flags=re.I)
    return result


def _day(match: re.Match) -> str:
    day, month, year = match.groups()
    return numeric_date(f"{day}/{month}/20{year}")


def _period(text: str, title: str) -> tuple[str, str] | None:
    """Inicio y fin del plazo de solicitudes de la tarjeta; None si ya solo es para consulta."""
    opens, closes = OPENS.findall(text), CLOSES.findall(text)
    if not opens and not closes and CLOSED.search(text):
        return None
    if len(opens) != 1 or len(closes) != 1:
        raise SourceLayoutError(f"UJI: «{title[:80]}» sin un plazo de solicitudes legible ({text[-160:]!r})")
    try:
        first, last = _day(OPENS.search(text)), _day(CLOSES.search(text))
    except ValueError as error:
        raise SourceLayoutError(f"UJI: fecha imposible en «{title[:80]}» ({error})") from error
    if first > last:
        raise SourceLayoutError(f"UJI: plazo al revés en «{title[:80]}» ({first} > {last})")
    return first, last


def parse_list(html: str) -> list[dict]:
    """Las convocatorias de plazas, en el orden de la página, con su plazo (None si cerrada) y concursos."""
    boxes = BeautifulSoup(html, "html.parser").select("div.tao-box[id^=tao-box-cat]")
    if not boxes:
        raise SourceLayoutError("UJI: el tablón no tiene subcategorías de convocatorias PI")
    found = []
    for box in boxes:
        kind = box["id"].removeprefix("tao-box-cat")
        if kind in POOLS:
            continue
        if kind not in PLACES:
            raise SourceLayoutError(f"UJI: subcategoría desconocida {kind!r} "
                                    f"({_clean(box.find('h4').get_text(' ')) if box.find('h4') else ''})")
        for call in box.select("div.tao-concursos-pdi[id^=convocatoria-]"):
            heading = call.select_one("p.customText strong")
            links = [(_clean(a.get_text(" ")), urljoin(INDEX, a["href"]))
                     for a in call.select('ul li a[href*="convocatoriesRH"]')]
            title = _clean(heading.get_text(" ")) if heading else ""
            if not (title and links):
                raise SourceLayoutError(f"UJI: convocatoria sin título o sin concursos ({call['id']})")
            conv = parse_qs(urlparse(links[0][1]).query).get("pConv", [""])[0]
            if f"convocatoria-{conv}" != call["id"]:
                raise SourceLayoutError(f"UJI: el concurso de {call['id']} apunta a pConv={conv!r}")
            item = call.select_one("div.item.tao-item")
            period = _period(_clean(item.get_text(" ")) if item else "", title)
            found.append({"ref": conv, "kind": kind, "title": title, "concursos": [label for label, _ in links],
                          "url": links[0][1], "opens_on": period[0] if period else None,
                          "deadline": period[1] if period else None})
    if not found:
        raise SourceLayoutError("UJI: el tablón no tiene ninguna convocatoria de plazas")
    return found


def labels(row: dict) -> dict:
    """Título «categoría · proyecto», categoría, código y título literal (ver el docstring del módulo)."""
    literal, match, registry = row["title"], TITLE.match(row["title"]), REGISTRY.match(row["title"])
    if match:  # la categoría del título: el nombre del concurso no es uniforme («Plaça de personal tecnòleg…»)
        category = match["category"][:1].upper() + match["category"][1:]
        project = humane_caps(match["name"].strip())
        title = f"{category} · {match['code'] + ' ' if match['code'] else ''}{project}"
    else:
        category = row["concursos"][0] if len(row["concursos"]) == 1 else None
        title = _caps(literal[registry.end():] if registry else literal)
        title = title[:1].upper() + title[1:]
    return {"title": title, "category": category, "code": registry.group(1) if registry else None,
            "source_title": literal}


def parse_ficha(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h2.subTitle")
    if heading is None or not _clean(heading.get_text(" ")).startswith("Convocatòria:"):
        raise SourceLayoutError("UJI: ficha sin «Convocatòria: …»")
    body = heading.parent
    title = _clean(heading.get_text(" "))[:90]
    text = _clean(body.get_text(" "))
    # El de los concursos (todos el mismo) y, si está, el «Termini» de la resolución que convoca.
    periods = set(re.findall(rf"Inici de presentació de sol·licituds ({DAY}) Fi de presentació de sol·licituds ({DAY})",
                             text))
    for resolution in body.select("p.tao-ar-texto"):
        said = _clean(resolution.get_text(" "))
        head = resolution.find_previous_sibling("div")
        termini = re.search(rf"Termini ({DAY}) - ({DAY})", _clean(head.get_text(" "))) if head else None
        if termini and CONVENES.search(said):
            periods.add(termini.groups())
        if EXTENDS.search(said):
            raise SourceLayoutError(f"UJI: «{title}» tiene una resolución que amplía o cambia el plazo: {said[:160]!r}")
    if len(periods) != 1:
        raise SourceLayoutError(f"UJI: «{title}» no trae un plazo de solicitudes y solo uno ({sorted(periods)})")
    try:
        first, last = (numeric_date(day) for day in periods.pop())
    except ValueError as error:
        raise SourceLayoutError(f"UJI: fecha imposible en la ficha de «{title}» ({error})") from error
    if first > last:
        raise SourceLayoutError(f"UJI: plazo al revés en la ficha de «{title}» ({first} > {last})")
    published = [numeric_date(day) for day in re.findall(rf"Data de publicació ({DAY})", text)]
    dogv = re.search(rf"\bDOGV ({DAY})", text)
    heading.decompose()
    for a in body.select("a[href]"):  # relativos: `sanitize` solo deja los absolutos
        a["href"] = urljoin(INDEX, a["href"])
    return {
        "opens_on": first, "deadline": last,
        "published_on": min(published) if published else numeric_date(dogv.group(1)) if dogv else None,
        "html": sanitize(body.decode_contents()),
    }


class UjiSource(Source):
    id = "uji"
    name = COMPANY
    homepage = INDEX
    scope = "Comunitat Valenciana"
    text_lang = "ca"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_list(http.get(INDEX)):
            # La tarjeta enseña el plazo de la última resolución (también el de subsanación, con la etiqueta de
            # solicitudes): si ese ya pasó, el de solicitudes también. Si no, manda la ficha.
            if row["deadline"] is None or deadline_passed(row["deadline"], None, now):
                continue
            ficha = parse_ficha(http.get(row["url"]))
            if deadline_passed(ficha["deadline"], None, now):
                continue
            self._fichas[row["ref"]] = ficha
            found = labels(row)
            offers.append(ListedOffer(
                ref=row["ref"], title=found["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                kind=None, category=found["category"], code=found["code"], source_title=found["source_title"],
                published_on=ficha["published_on"], opens_on=ficha["opens_on"], deadline=ficha["deadline"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        return OfferDetail(location="Castelló de la Plana",
                           sections=[{"title": "La convocatoria", "level": 2, "html": ficha["html"],
                                      "lang": self.text_lang}])
