"""IBSAL (Instituto de Investigación Biomédica de Salamanca), contrata FIBSAL.

WordPress con el plugin WP Job Openings. La página `/convocatorias-de-empleo/` lista solo las
convocatorias vigentes (`.awsm-job-listings`); sin ninguna, muestra «Actualmente no tenemos
ofertas» (`.awsm-jobs-none-container`). Cada ficha trae la fecha de caducidad
(`.awsm-job-expiration-content`, «22 Oct 2026», sin hora) y «Tipo de contrato» literal
(art. 23 bis en muchas). Las ayudas de investigación están en otra sección y no se leen.

Se piden la página de vigentes y la ficha de cada una. Es oferta la que tiene fecha de caducidad
no vencida; sin fecha, la fuente se detiene. La tarjeta de una convocatoria vigente está sin ver
con datos reales (el 2026-11-08 no había ninguna): se toma cualquier enlace a una ficha dentro del
listado y, si el listado tiene contenido sin enlaces, la fuente se detiene.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import month_number
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://ibsal.es"
PAGE = f"{SITE}/convocatorias-de-empleo/"
COMPANY = "IBSAL"
EXPIRY = re.compile(r"(\d{1,2})\s+([A-Za-zé]{3,})\.?\s+(\d{4})")
POST = re.compile(r"[?&]p=(\d+)")
# El plugin escribe el mes abreviado; según el idioma de WordPress, en inglés o en español.
ENGLISH = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
           "sep": 9, "oct": 10, "nov": 11, "dec": 12}
SPANISH = {"ene": 1, "abr": 4, "ago": 8, "dic": 12, "sept": 9}


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def expiry_date(text: str) -> date | None:
    found = EXPIRY.search(text)
    if not found:
        return None
    word = found.group(2).lower()
    month = ENGLISH.get(word[:3]) or SPANISH.get(word) or SPANISH.get(word[:3]) or month_number(word)
    try:
        return date(int(found.group(3)), month, int(found.group(1))) if month else None
    except ValueError:
        return None


def parse_listing(html: str) -> list[str]:
    """Enlaces a las fichas de las convocatorias vigentes."""
    box = BeautifulSoup(html, "html.parser").select_one(".awsm-job-listings")
    if box is None:
        raise SourceLayoutError("IBSAL: no se encuentra el listado de convocatorias")
    if box.select_one(".awsm-jobs-none-container"):
        return []
    links = []
    for link in box.find_all("a", href=True):
        url = urljoin(PAGE, link["href"])
        if url.startswith(SITE) and url.rstrip("/") != PAGE.rstrip("/") and url not in links:
            links.append(url)
    if not links:
        raise SourceLayoutError("IBSAL: el listado tiene contenido pero ningún enlace a una ficha")
    return links


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    title, expiry = soup.find("h1"), soup.select_one(".awsm-job-expiration-content")
    canonical = soup.find("link", rel="canonical")
    post = POST.search(canonical["href"]) if canonical and canonical.get("href") else None
    deadline = expiry_date(_text(expiry)) if expiry else None
    if not (title and post and deadline):
        raise SourceLayoutError("IBSAL: ficha sin título, identificador o fecha de caducidad")
    contract = soup.select_one(".awsm-job-specification-tipo-de-contrato .awsm-job-specification-term")
    body = soup.select_one(".awsm-job-entry-content")
    return {
        "ref": post.group(1), "title": _text(title), "url": canonical["href"],
        "deadline": deadline.isoformat(), "contract": _text(contract) if contract else None,
        "html": sanitize(body.decode_contents()) if body else "",
    }


class IbsalSource(Source):
    id = "ibsal"
    name = "IBSAL (FIBSAL)"
    homepage = PAGE
    scope = "Castilla y León"
    apply_label = "Ver la convocatoria y presentar la candidatura"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._html: dict[str, str] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for url in parse_listing(http.get(PAGE)):
            job = parse_detail(http.get(url))
            if deadline_passed(job["deadline"], None, now):
                continue
            self._html[job["ref"]] = job["html"]
            offers.append(ListedOffer(
                ref=job["ref"], title=job["title"], company="FIBSAL", url=job["url"], apply_url=job["url"],
                kind=None, deadline=job["deadline"], contract=job["contract"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        html = self._html.get(offer.ref)
        sections = [{"title": "Convocatoria", "level": 2, "html": html}] if html else []
        return OfferDetail(sections=sections, location="Salamanca")
