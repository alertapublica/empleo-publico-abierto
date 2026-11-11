"""IdISBa (Institut d'Investigació Sanitària Illes Balears).

`Ofertas de trabajo` pagina de cinco en cinco (`/page/N`), de la publicación más reciente a la más
antigua. Cada convocatoria es un `div.flow--m` con el título (enlace a la ficha) y una lista `dl`:
«Número de referencia» (`2026-50-RLTIDISBA`), «Publicación al BOIB» (número, fecha y enlace),
«Plazo de presentación» (`<time datetime>` de inicio y de fin, sin hora) y «Documentación» (bases,
anexos y, cuando avanza, listas de admitidos, a veces con la fecha delante: «20261104_lista_…»).

El orden es el de publicación, no el del plazo: una convocatoria antigua puede seguir abierta. Se lee
la página siguiente mientras alguna de la actual siga en plazo (hasta MAX_PAGES). Es oferta la que
tiene el fin del plazo sin vencer. Sin procesos: al pasar a la página siguiente dejarían de verse y
el motor los daría por retirados.
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

SITE = "https://www.idisba.es"
PAGE = SITE + "/es/trabajo/ofertas-de-trabajo/"
PAGED = SITE + "/es/trabajo/ofertas-de-trabajo/page/{}"
COMPANY = "IdISBa"
MAX_PAGES = 3
SIZE = re.compile(r"\s*\(PDF[^)]*\)\s*$|\s*\(ZIP[^)]*\)\s*$", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for block in soup.select("div.flow--m"):
        heading, terms = block.select_one("h2 a[href]"), block.find("dl")
        if heading is None or terms is None:
            continue
        fields = {_clean(d.find("dt").get_text(" ")): d.find("dd") for d in terms.find_all("div", recursive=False) if d.find("dt")}
        ref, period = fields.get("Número de referencia"), fields.get("Plazo de presentación")
        times = [t.get("datetime", "") for t in period.find_all("time")] if period else []
        if ref is None or len(times) != 2 or not all(re.fullmatch(r"\d{4}-\d{2}-\d{2}", t) for t in times):
            raise SourceLayoutError(f"IdISBa: convocatoria sin referencia o sin plazo: «{_clean(heading.get_text(' '))}»")
        bulletin = fields.get("Publicación al BOIB")
        bulletin_link = bulletin.find("a", href=True) if bulletin else None
        documents = []
        for link in (fields.get("Documentación") or terms).select("a[href]"):
            if link is bulletin_link:
                continue
            documents.append((SIZE.sub("", _clean(link.get_text(" "))), urljoin(SITE, link["href"])))
        found.append({
            "title": _clean(heading.get_text(" ")), "url": urljoin(SITE, heading["href"]), "ref": _clean(ref.get_text(" ")),
            "opens_on": times[0], "deadline": times[1], "period": _clean(period.get_text(" ")),
            "bulletin": _clean(bulletin.get_text(" ")).replace("Publicación oficial", "").strip() if bulletin else None,
            "bulletin_url": bulletin_link["href"] if bulletin_link else None, "documents": documents,
        })
    if not found:
        raise SourceLayoutError("IdISBa: la página no tiene convocatorias")
    return found


class IdisbaSource(Source):
    id = "idisba"
    name = "IdISBa (Institut d'Investigació Sanitària Illes Balears)"
    homepage = PAGE
    scope = "Illes Balears"
    apply_label = "Ver la convocatoria y cómo presentarse"
    ref_code = re.compile(r"[0-9A-Z][0-9A-Z-]+")  # «2026-50-RLTIDISBA» o «L03130017»: las dos son públicas

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._found: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        entries = []
        for number in range(1, MAX_PAGES + 1):
            page = parse_page(http.get(PAGE if number == 1 else PAGED.format(number)))
            entries += page
            if all(deadline_passed(e["deadline"], None, now) for e in page):
                break
        offers = []
        for entry in entries:
            if deadline_passed(entry["deadline"], None, now) or entry["ref"] in self._found:
                continue
            self._found[entry["ref"]] = entry
            offers.append(ListedOffer(
                ref=entry["ref"], title=entry["title"], company=COMPANY, url=entry["url"], apply_url=entry["url"],
                kind=None, deadline=entry["deadline"], opens_on=entry["opens_on"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        entry = self._found.get(offer.ref)
        if entry is None:
            return OfferDetail(location="Palma")
        sections = [{"title": "Plazo de presentación", "level": 2, "html": sanitize(f"<p>{escape(entry['period'])}</p>")}]
        if entry["bulletin"]:
            link = (f' <a href="{escape(entry["bulletin_url"], quote=True)}">Publicación oficial</a>'
                    if entry["bulletin_url"] else "")
            sections.append({"title": "Publicación en el BOIB", "level": 2,
                             "html": sanitize(f"<p>{escape(entry['bulletin'])}.{link}</p>")})
        if entry["documents"]:
            items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
                            for label, url in entry["documents"])
            sections.append({"title": "Documentación", "level": 2, "html": sanitize(f"<ul>{items}</ul>")})
        return OfferDetail(location="Palma", sections=sections)
