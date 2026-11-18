"""Universidade de Santiago de Compostela: convocatorias públicas de contratación de personal de investigación.

Listado `/es/investigar-en-la-usc/convocatorias` (Drupal, 12 tarjetas por página, `?page=N`; títulos y fichas en
gallego también en la versión en castellano). Cada tarjeta (`article.ml-notice`) trae el título, que enlaza la
ficha, y «Plazo de presentación de la solicitud» (una fecha, «----» o «---» en la próxima convocatoria anunciada o
«Proceso cancelado»). La etiqueta «Convocatoria abierta» sigue con el plazo vencido: no se usa. El listado no va
por fecha (la 02/2026 sale en la segunda página, entre las de 2025): se leen al menos `MIN_PAGES` páginas y se
sigue mientras alguna tarjeta traiga una fecha de los últimos `HORIZON_DAYS` días, hasta `MAX_PAGES`. Otra cosa que
una fecha, «----», «---» o «Proceso cancelado» en la tarjeta detiene la fuente.

Son tandas («Convocatoria Pública Ordinaria 13/2026 de contratración de persoal para colaborar nas actividades e
proxectos de investigación», 13 ordinarias y varias urgentes en 2026; la errata es del original): unas 13 plazas por
tanda, que solo vienen en el anexo del PDF (sin leer). Se publica una oferta por tanda, con su título literal, como
CiQUS y CiMUS (centros de la USC con series propias, que no se solapan con estas).

El plazo no se toma de la tarjeta ni del campo «Prazo de presentación da solicitude» de la ficha: en la urgente
12/2026 dice 10/09/2026 y la convocatoria, publicada el 09/09, da tres días hábiles, «ata o 14/09/2026». Manda la
etiqueta del documento de la convocatoria: «Convocatoria ordinaria. Data publicación: 19/10/2026. O prazo de
presentación de solicitudes dende o 20/10/2026 ata o 26/10/2026» (sin hora; en las urgentes, sin «dende»). Sin esa
etiqueta, con el campo fuera de [publicación, fin], con el inicio después del fin o con otra mención del fin del
plazo que no coincide (una corrección que lo amplía), la fuente se detiene. Una tarjeta es candidata si su fecha es de
los últimos `CANDIDATE_DAYS` días (el campo puede ser el inicio y no el fin): solo se abre su ficha.

Sin municipio (hay plazas en Santiago y en Lugo). Muestras del 2026-11-15 bajadas por el usuario con
`sondeo/manual.py`.
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
from .base import Source

SITE = "https://www.usc.gal"
INDEX = SITE + "/es/investigar-en-la-usc/convocatorias"
COMPANY = "Universidade de Santiago de Compostela"
HORIZON_DAYS = 60
CANDIDATE_DAYS = 30
MIN_PAGES = 2
MAX_PAGES = 4
PATH = re.compile(r"^/(?:gl|es)/investiga[a-z-]+/convocatorias/([a-z0-9-]+)$")
DAY = re.compile(r"^\d{2}/\d{2}/\d{4}$")
PERIOD = re.compile(r"Data publicación:\s*(\d{2}/\d{2}/\d{4})\.\s*O prazo de presentación de solicitudes\s+"
                    r"(?:dende o (\d{2}/\d{2}/\d{4})\s+)?ata o (\d{2}/\d{2}/\d{4})")
# Cualquier mención del fin del plazo de solicitudes en los documentos de la convocatoria (una corrección
# que lo amplía, otra redacción): todas deben dar el mismo día que la etiqueta de la convocatoria.
ANY_END = re.compile(r"prazo de presentación de solicitudes.*?\bata o (?:día )?(\d{2}/\d{2}/\d{4})", re.I)
NO_DATE = {"----", "---", "Proceso cancelado"}  # «---» en la próxima 15/2026 (2026-11-18)
SIZE = re.compile(r"\s*\[(?:pdf|docx?|odt)\s*-\s*[\d.,]+\s*[KM]B\]$", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_list(html: str) -> list[dict]:
    cards = BeautifulSoup(html, "html.parser").select("article.ml-notice")
    if not cards:
        raise SourceLayoutError("USC: el listado de convocatorias está vacío")
    found = []
    for card in cards:
        link, value = card.select_one(".at-title a[href]"), card.select_one("dd")
        path = PATH.match(link["href"]) if link else None
        if not (path and _clean(link.get_text(" ")) and value):
            raise SourceLayoutError(f"USC: tarjeta sin ficha, título o plazo ({_clean(card.get_text(' '))[:120]!r})")
        text = _clean(value.get_text(" "))
        if not DAY.match(text) and text not in NO_DATE:
            raise SourceLayoutError(f"USC: plazo de tarjeta desconocido ({text!r})")
        found.append({"ref": path.group(1), "url": SITE + link["href"], "title": _clean(link.get_text(" ")),
                      "date": numeric_date(text) if DAY.match(text) else None})
    return found


def next_page(html: str, url: str) -> str | None:
    link = BeautifulSoup(html, "html.parser").select_one('a[rel="next"][href]')
    return urljoin(url, link["href"]) if link else None


def parse_ficha(html: str) -> dict:
    main = BeautifulSoup(html, "html.parser").select_one("main")
    title = main.select_one("h1") if main else None
    fields = main.select_one("dl.at-desc-list") if main else None
    if not (title and fields):
        raise SourceLayoutError("USC: ficha sin título o sin datos de la convocatoria")
    values = dict(zip((_clean(dt.get_text(" ")) for dt in fields.select("dt")),
                      (_clean(dd.get_text(" ")) for dd in fields.select("dd"))))
    call = next((item for item in main.select("usc-accordion-item")
                 if (header := item.select_one("template")) and _clean(header.get_text(" ")) == "Convocatoria"), None)
    links = [(_clean(a.get_text(" ")), urljoin(SITE, a["href"]), a.get("class") or []) for a in call.select("a[href]")] if call else []
    periods = {match.groups() for label, _, _ in links if (match := PERIOD.search(label))}
    if len(periods) != 1:
        raise SourceLayoutError(f"USC: la ficha no trae un único «Data publicación… prazo… ata o…» ({len(periods)})")
    published, first, last = (numeric_date(day) if day else None for day in periods.pop())
    ends = {numeric_date(day) for label, _, _ in links for day in ANY_END.findall(label)}
    if ends != {last} or (first and first > last):
        raise SourceLayoutError(f"USC: plazos que no cuadran en los documentos (inicio {first}, fin {last}, "
                                f"menciones {sorted(ends)})")
    field = values.get("Prazo de presentación da solicitude", "")
    if not DAY.match(field) or not published <= numeric_date(field) <= last:
        raise SourceLayoutError(f"USC: el campo «Prazo» ({field!r}) no cae entre la publicación ({published}) y el fin "
                                f"del plazo ({last})")
    lead = main.select_one(".at-lead-text")
    return {
        "title": _clean(title.get_text(" ")), "published_on": published, "opens_on": first, "deadline": last,
        "apply_url": next((url for label, url, _ in links if label == "Presentación de solicitude"), None),
        "lead": sanitize(lead.decode_contents()) if lead and _clean(lead.get_text(" ")) else None,
        # Solo la convocatoria y sus correcciones: las listas de admitidos llevan nombres.
        "documents": [(SIZE.sub("", label), url) for label, url, classes in links
                      if "at-icon-paperclip" in classes and not re.match(r"(?i)listas?\b", label)],
    }


class UscSource(Source):
    id = "usc"
    name = "Universidade de Santiago de Compostela"
    homepage = INDEX
    scope = "Galicia"
    text_lang = "gl"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def _candidates(self, http: Client, now: datetime) -> list[dict]:
        today = now.astimezone(MADRID).date()
        horizon, recent = (today - timedelta(days=HORIZON_DAYS)).isoformat(), (today - timedelta(days=CANDIDATE_DAYS)).isoformat()
        found, url = [], INDEX
        for page in range(MAX_PAGES):
            html = http.get(url)
            rows = parse_list(html)
            found += [row for row in rows if row["date"] and row["date"] >= recent]
            url = next_page(html, url)
            # Al menos MIN_PAGES: el orden no es de fecha y una página entera puede ser antigua.
            if url is None or (page + 1 >= MIN_PAGES and not any(row["date"] and row["date"] >= horizon for row in rows)):
                return found
        raise SourceLayoutError(f"USC: más de {MAX_PAGES} páginas con convocatorias de los últimos {HORIZON_DAYS} días")

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in self._candidates(http, now):
            ficha = self._fichas[row["ref"]] = parse_ficha(http.get(row["url"]))
            if deadline_passed(ficha["deadline"], None, now):
                continue
            offers.append(ListedOffer(
                ref=row["ref"], title=ficha["title"], company=COMPANY, url=row["url"],
                apply_url=ficha["apply_url"] or row["url"], kind=None, published_on=ficha["published_on"],
                opens_on=ficha["opens_on"], deadline=ficha["deadline"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        sections = []
        if ficha["lead"]:
            sections.append({"title": "La convocatoria", "level": 2, "html": ficha["lead"], "lang": self.text_lang})
        if ficha["documents"]:
            items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
                            for label, url in ficha["documents"])
            sections.append({"title": "Documentos", "level": 2, "html": sanitize(f"<ul>{items}</ul>"),
                             "lang": self.text_lang})
        return OfferDetail(sections=sections)
