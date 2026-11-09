"""IIS La Fe (Instituto de Investigación Sanitaria La Fe, Valencia).

`/es/talento/empleo/page/N`: diez tarjetas por página (`div.empleo-item`), de la referencia más
alta a la más baja (el plazo no sigue ese orden), con publicación (`<time datetime>`), título,
estado («Abierta», «Cerrada pendiente de evaluar»…), «Número de referencia», «Plazo de
presentación» (sin hora), documentos y, si está abierta, el botón de inscripción. El contrato
solo está en las bases (PDF): no se lee.

Es oferta la tarjeta cuyo plazo no ha pasado; el estado no se usa. Se lee la página 1 y, mientras
alguna tarjeta de la página siga en plazo, la siguiente (hasta MAX_PAGES). Solo se enlazan las
bases: entre los documentos hay baremaciones con nombres.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://www.iislafe.es"
PAGE = SITE + "/es/talento/empleo/page/{}"
MAX_PAGES = 3
REF = re.compile(r"Número de referencia:\s*(\d+/\d{4})")
TERM = re.compile(r"Plazo de presentación:\s*(\d\d/\d\d/\d{4})")


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def parse_page(html: str) -> list[dict]:
    cards = BeautifulSoup(html, "html.parser").select("div.empleo-item")
    if not cards:
        raise SourceLayoutError("IIS La Fe: no se encuentran las convocatorias")
    found = []
    for card in cards:
        text = _text(card)
        link, ref, term, published = card.select_one("h2 a[href]"), REF.search(text), TERM.search(text), card.find("time")
        if not (link and ref and term):
            raise SourceLayoutError(f"IIS La Fe: convocatoria sin título, referencia o plazo: {text[:80]}")
        bases = next((a["href"] for a in card.select("dd a[href]") if _text(a).lower() == "bases"), None)
        found.append({
            "ref": ref.group(1), "title": _text(link), "url": urljoin(SITE, link["href"]),
            "deadline": numeric_date(term.group(1)),
            "published_on": published.get("datetime") if published else None,
            "bases": bases,
        })
    return found


class LaFeSource(Source):
    id = "lafe"
    name = "IIS La Fe"
    homepage = PAGE.format(1)
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    scope = "Comunitat Valenciana"
    apply_label = "Ver la convocatoria e inscribirse"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._bases: dict[str, str | None] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        entries = []
        for number in range(1, MAX_PAGES + 1):
            page = parse_page(http.get(PAGE.format(number)))
            entries += page
            if all(deadline_passed(e["deadline"], None, now) for e in page):
                break
        open_ = [e for e in entries if not deadline_passed(e["deadline"], None, now)]
        self._bases = {e["ref"]: e["bases"] for e in open_}
        return [
            ListedOffer(
                ref=e["ref"], title=e["title"], company="Fundación para la Investigación del Hospital La Fe",
                url=e["url"], apply_url=e["url"] + "#inscripcion", kind=None, deadline=e["deadline"],
                published_on=e["published_on"],
            )
            for e in open_
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        bases = self._bases.get(offer.ref)
        sections = []
        if bases:
            sections.append({"title": "Documentos de la convocatoria", "level": 2,
                             "html": sanitize(f'<ul><li><a href="{escape(bases, quote=True)}">Bases</a></li></ul>')})
        return OfferDetail(sections=sections, location="Valencia")
