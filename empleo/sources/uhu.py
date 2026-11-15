"""Universidad de Huelva: plazas de Personal Técnico de Apoyo a la Investigación (contratos de proyecto).

El índice de convocatorias (`/personal-tecnico-apoyo/convocatorias`, Drupal, filtrado por «Propia»:
«Externa» estaba vacío el 2026-11-15) lista por fecha de publicación, de la más nueva a la más antigua,
10 por página («Cargar más», `rel="next"`). Cada tarjeta (`article.view-calls`, atributo
`about` = ruta de la ficha) trae la fecha de publicación («04/11/2026»), un estado que dice «Abierta»
también con el plazo vencido (mandan las fechas, como en IFAPA), el título literal (en mayúsculas o
no según quién lo escriba, y recortado con «...» en origen) y los documentos: «Convocatoria» (PDF en
tablon.uhu.es), «Solicitud (del 05/11/2026 al 18/11/2026)» (el plazo, sin hora), «Application» y
«Job offer Euraxess». El orden no es el del plazo: se sigue «Cargar más» mientras la última tarjeta se
haya publicado en los últimos `HORIZON_DAYS` días (decidido con el usuario el 2026-11-15; el plazo dura
unas dos semanas) y, si quedan más de `MAX_PAGES` páginas, se detiene. El 2026-11-15, 6 en plazo en la
primera. Tarjeta sin plazo legible: no se publica (plazo no fiable); dos plazos distintos o al revés:
se detiene.

La ficha trae «Tipo de convocatoria: Plazas Personal Técnico de Apoyo a la Investigación / Técnico Grado
Medio» (el último es la categoría), «Unidad Responsable» (la de personal, no el departamento) y la
«Descripción»: el texto literal de la resolución, que se copia entero. Cerrado el plazo, la UHU
sustituye ese texto por la resolución siguiente (admitidos y excluidos): las abiertas no lo tienen.
Contrato, plazas y centro solo vienen en el PDF de la convocatoria (sin leer).

Título (decisión del 2026-11-15): la categoría y el proyecto, separados por « · », como en IFAPA. El
proyecto sale de «…PARA EL DESARROLLO DEL PROYECTO “…”» en la descripción (completo; en la tarjeta
viene recortado), sin su código, y con `humane_caps` si viene en mayúsculas; el código («DGP_PIDI_2024_
01054», «EPIT1162023», «0369_ITACA_5_E»: delante del nombre o al final entre paréntesis; al menos
cuatro cifras, para no confundirlo con una sigla como «MBIOF4BEES») va a `code` y el título de la
tarjeta, a `source_title`. Si la descripción no tiene exactamente un proyecto así (una comilla sin
cerrar, la frase dos veces, algo delante de la comilla que no es un código, dos códigos distintos), se
publica con el título de la tarjeta y la ficha deja un aviso.

Identificador: el último tramo de la ruta (no hay número de nodo visible). Si la UHU edita el título,
Drupal puede cambiar la ruta y la oferta saldría como nueva. Sin municipio: la ficha no da el centro
(mismo criterio que la UA). Sondeo y HTML de muestra del 2026-11-15 (Codex, encargo 40).
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from ..text import humane_caps
from .base import Source

SITE = "https://www.uhu.es"
INDEX = SITE + "/personal-tecnico-apoyo/convocatorias?title=&field_propia_externa_value=1&field_call_status_value=All"
COMPANY = "Universidad de Huelva"
HORIZON_DAYS = 60
MAX_PAGES = 8
PATH = re.compile(r"^/personal-tecnico-apoyo/convocatorias/([a-z0-9-]+)$")
DAY = re.compile(r"\d{2}/\d{2}/\d{4}")
PERIOD = re.compile(r"^Solicitud \(del (\d{2}/\d{2}/\d{4}) al (\d{2}/\d{2}/\d{4})\)$")
# «…PARA EL DESARROLLO DEL PROYECTO “X”» (con o sin código delante de la comilla) o sin comillas hasta
# la coma o el paréntesis del investigador principal.
MENTION = re.compile(r"(?i:para el desarrollo del proyecto)")
PROJECT = re.compile(
    MENTION.pattern + r"\s+"
    r"(?:(?:(?P<pre>[^\s“”\"]+)\s+)?[“\"](?P<quoted>[^“”\"]+)[”\"]"
    r"|(?P<bare>[^“”\",]+?)\s*(?=,|\((?i:investigador|ip:)))")
CODE = r"[^\W_][\w./-]*"
LEADING_CODE = re.compile(rf"^({CODE})\s+")
TRAILING_CODE = re.compile(rf"\s*\((?:REF\.:\s*)?({CODE})\)$")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _is_code(token: str | None) -> bool:
    """«EPIT1162023», «0369_ITACA_5_E»: cuatro cifras o más y alguna letra («MBIOF4BEES» es una sigla)."""
    return bool(token) and sum(c.isdigit() for c in token) >= 4 and any(c.isalpha() for c in token)


def _documents(node) -> list[tuple[str, str]]:
    return [(_clean(a.get_text(" ")), urljoin(SITE, a["href"])) for a in node.select("a[href]") if _clean(a.get_text(" "))]


def parse_list(html: str) -> list[dict]:
    cards = BeautifulSoup(html, "html.parser").select("article.view-calls[about]")
    if not cards:
        raise SourceLayoutError("Universidad de Huelva: el índice de convocatorias está vacío")
    found = []
    for card in cards:
        path, day = PATH.match(card["about"]), card.select_one(".o-icon-txt span")
        title = card.select_one(".field--name-field-title")
        published = DAY.fullmatch(_clean(day.get_text(" "))) if day else None
        if not (path and published and title and _clean(title.get_text(" "))):
            raise SourceLayoutError(f"Universidad de Huelva: tarjeta sin ruta, fecha o título "
                                    f"({_clean(card.get_text(' '))[:120]!r})")
        docs = card.select_one(".field--name-field-outstanding-docs")
        documents = _documents(docs) if docs else []
        periods = {(numeric_date(m.group(1)), numeric_date(m.group(2)))
                   for m in (PERIOD.match(label) for label, _ in documents) if m}
        if len(periods) > 1 or any(first > last for first, last in periods):
            raise SourceLayoutError(f"Universidad de Huelva: plazos contradictorios en {path.group(1)}: {sorted(periods)}")
        first, last = next(iter(periods), (None, None))
        found.append({
            "ref": path.group(1), "url": SITE + card["about"], "title": _clean(title.get_text(" ")),
            "published_on": numeric_date(published.group(0)), "opens_on": first, "deadline": last,
        })
    if not any(row["deadline"] for row in found):
        raise SourceLayoutError("Universidad de Huelva: ninguna tarjeta trae «Solicitud (del … al …)»")
    return found


def next_page(html: str, url: str) -> str | None:
    """Dirección del «Cargar más» (`rel="next"`), o None en la última página."""
    link = BeautifulSoup(html, "html.parser").select_one('a[rel="next"][href]')
    return urljoin(url, link["href"]) if link else None


def project_of(text: str) -> tuple[str, str | None] | None:
    """Nombre del proyecto y su código, del único «para el desarrollo del proyecto…» de la resolución."""
    text = _clean(text)
    match = PROJECT.search(text) if len(MENTION.findall(text)) == 1 else None
    if match is None or (match["pre"] and not _is_code(match["pre"])):
        return None
    name, codes = (match["quoted"] or match["bare"]).strip(" ."), {match["pre"]} - {None}
    if (lead := LEADING_CODE.match(name)) and _is_code(lead.group(1)):
        codes.add(lead.group(1))
        name = name[lead.end():]
    if (trail := TRAILING_CODE.search(name)) and _is_code(trail.group(1)):
        codes.add(trail.group(1))
        name = name[:trail.start()]
    if len(codes) > 1:
        return None
    code = next(iter(codes), None)
    name = name.strip(" .,")
    if not name or re.search(r"(?i)\bfinanciad[oa]\b|\bcon cargo\b", name):
        return None
    return humane_caps(name), code


def parse_ficha(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    node = soup.select_one("article.node--type-call")
    body = node.select_one(".field--name-body") if node else None
    if body is None:
        raise SourceLayoutError("Universidad de Huelva: ficha sin «Descripción»")
    types = [_clean(item.get_text(" ")) for item in node.select(".field--name-field-call-type .field__item")]
    docs = node.select_one("#edit-group-documentos") or node.select_one(".field--name-field-outstanding-docs")
    return {
        "category": types[-1] if len(types) > 1 else None,
        "project": project_of(body.get_text(" ")),
        "body": sanitize(body.decode_contents()),
        "documents": _documents(docs) if docs else [],
    }


class UhuSource(Source):
    id = "uhu"
    name = "Universidad de Huelva"
    homepage = SITE + "/personal-tecnico-apoyo/oferta-de-empleo"
    scope = "Andalucía"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def _open_rows(self, http: Client) -> list[dict]:
        now = self._now or datetime.now(timezone.utc)
        oldest = (now.astimezone(MADRID).date() - timedelta(days=HORIZON_DAYS)).isoformat()
        found, url = [], INDEX
        for _ in range(MAX_PAGES):
            html = http.get(url)
            rows = parse_list(html)
            found += [row for row in rows if row["deadline"] and not deadline_passed(row["deadline"], None, now)]
            url = next_page(html, url)
            if url is None or rows[-1]["published_on"] < oldest:
                return found
        raise SourceLayoutError(f"Universidad de Huelva: más de {MAX_PAGES} páginas publicadas en los últimos "
                                f"{HORIZON_DAYS} días")

    def list_offers(self, http: Client) -> list[ListedOffer]:
        offers = []
        for row in self._open_rows(http):
            ficha = self._fichas[row["ref"]] = parse_ficha(http.get(row["url"]))
            name, code = ficha["project"] or (None, None)
            title = f"{ficha['category']} · {name}" if name and ficha["category"] else None
            offers.append(ListedOffer(
                ref=row["ref"], title=title or row["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                kind=None, category=ficha["category"], deadline=row["deadline"], opens_on=row["opens_on"],
                published_on=row["published_on"], code=code if title else None,
                source_title=row["title"] if title else None,
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        # Aquí y no en el listado: la oferta sale con el título de la tarjeta y la ficha avisa y se relee.
        if ficha["project"] is None or ficha["category"] is None:
            raise SourceLayoutError("Universidad de Huelva: ficha sin categoría o sin un único "
                                    "«para el desarrollo del proyecto…» legible")
        sections = [{"title": "La convocatoria", "level": 2, "html": ficha["body"]}]
        if ficha["documents"]:
            items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
                            for label, url in ficha["documents"])
            sections.append({"title": "Documentos", "level": 2, "html": sanitize(f"<ul>{items}</ul>")})
        return OfferDetail(sections=sections)
