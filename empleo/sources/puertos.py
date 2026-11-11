"""Puertos del Estado.

Listado en Drupal con 12 entradas y una ficha por entrada. El listado no da el plazo y además
mezcla avisos («Resolución mes de agosto inhábil», «Iniciación Oferta Pública de Empleo»), así
que hay que leer las fichas: es oferta la que tiene fecha límite vigente.

Las convocatorias intraportuarias e intraadministrativas no están abiertas al público y no se
ofrecen. Las fichas publican relaciones de personas admitidas: de sus documentos solo se enlazan
los de la convocatoria.

Las ofertas de las autoridades portuarias (`offer_type=107`) no dan fecha: sus bases dicen «veinte
(20) días hábiles, a partir del día siguiente al de la publicación de esta convocatoria», sin decir
cuándo ni dónde se publica, y el listado conserva las antiguas sin añadirles nada. Por eso son
procesos sin plazo: el listado da puesto, autoridad portuaria y ficha, y el motor las pasa a «sin
novedades» a los 30 días de verlas (`stale_after_days`). Las autoridades con fuente propia (OWN_SOURCE)
no se leen aquí: su portal da plazo, oferta y seguimiento, y saldrían dos veces.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from ..sanitize import sanitize
from .base import Source

HOST = "https://www.puertos.es"
PAGE = f"{HOST}/institucional/recursos-humanos/ofertas-de-empleo"
LISTING = f"{PAGE}?offer_type=108"
AUTHORITIES = f"{PAGE}?offer_type=107"
# Autoridades portuarias que tienen fuente propia: apb.py lee el portal de selección de Barcelona.
OWN_SOURCE = {"Barcelona"}
COMPANY = "Puertos del Estado"
INTERNAL = re.compile(r"intra(portuaria|administrativa)", re.I)
DEADLINE = re.compile(r"Fecha l[ií]mite[^:]*:\s*(?:[a-záéíóú]+,?\s+)?(\d\d/\d\d/\d{4})", re.I)  # «Miércoles 17/06/2026»
SEATS = re.compile(r"^(\d+)\s+plazas?\b", re.I)
AGREEMENT = re.compile(r"^(dentro|fuera)\s+de\s+convenio$", re.I)
CALL_DOCUMENT = re.compile(r"bases|anexo|fe de publicaci|ampliaci|modificaci", re.I)
PERSONAL_DOCUMENT = re.compile(r"admitid|excluid|aspirantes|adjudic|calificaci|puntuaci|aprobad", re.I)


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def parse_list(html: str) -> list[dict]:
    articles = BeautifulSoup(html, "html.parser").select("article.node--type-job-offer")
    entries = []
    for article in articles:
        title, link = article.select_one("h2.offer__title"), article.select_one("a.offer__link--item")
        if not (title and link):
            raise SourceLayoutError("Puertos: entrada sin título o sin enlace")
        provider = article.select_one(".field--name-provider-entity")
        entries.append({"title": _text(title), "url": urljoin(HOST, link["href"]),
                        "provider": _text(provider) if provider else None})
    if not entries:
        raise SourceLayoutError("Puertos: no se encuentran las ofertas")
    return entries


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".field--name-body")
    facts = [_text(item) for item in body.find_all("li")] if body else []
    text = _text(body) if body else ""
    deadline = DEADLINE.search(text)
    seats = next((m for fact in facts if (m := SEATS.match(fact))), None)
    agreement = next((fact for fact in facts if AGREEMENT.match(fact)), None)
    places = [f for f in facts if not (SEATS.match(f) or AGREEMENT.match(f) or DEADLINE.search(f))]
    documents = [
        (_text(link), urljoin(HOST, link["href"]))
        for link in soup.select(".field--name-field-document-list a[href]")
        if CALL_DOCUMENT.search(_text(link)) and not PERSONAL_DOCUMENT.search(_text(link))
    ]
    return {
        "deadline": numeric_date(deadline.group(1)) if deadline else None,
        "positions": int(seats.group(1)) if seats else None,
        "agreement": agreement,
        "location": places[0] if len(places) == 1 else None,
        "documents": documents,
    }


def slug_of(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1]


def select_offers(entries: list[dict], today: str) -> list[dict]:
    """Entradas con ficha ya leída que admiten candidaturas hoy."""
    if not any(entry["deadline"] for entry in entries):
        raise SourceLayoutError("Puertos: ninguna ficha trae fecha límite")
    return [e for e in entries if e["deadline"] and e["deadline"] >= today and not INTERNAL.search(e["title"])]


class PuertosSource(Source):
    id = "puertos"
    name = COMPANY
    homepage = LISTING
    apply_label = "Ver las bases y cómo presentarse"
    stale_after_days = 30  # unos 20 días hábiles y algún festivo

    def __init__(self) -> None:
        self._entries: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        entries = [{**entry, **parse_detail(http.get(entry["url"]))} for entry in parse_list(http.get(LISTING))]
        chosen = select_offers(entries, today_madrid(datetime.now(timezone.utc)))
        self._entries = {slug_of(entry["url"]): entry for entry in chosen}
        return [
            ListedOffer(
                ref=ref, title=entry["title"], company=COMPANY, url=entry["url"], apply_url=entry["url"],
                kind=None, positions=entry["positions"], category=entry["agreement"],
                deadline=entry["deadline"],
            )
            for ref, entry in self._entries.items()
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        entry = self._entries.get(offer.ref)
        if entry is None:
            return OfferDetail()
        items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
                        for label, url in entry["documents"])
        sections = [{"title": "Documentos de la convocatoria", "level": 2,
                     "html": sanitize(f"<ul>{items}</ul>")}] if items else []
        return OfferDetail(sections=sections, location=entry["location"])

    def list_announcements(self, http: Client) -> list[Announcement]:
        entries = parse_list(http.get(AUTHORITIES))
        if any(entry["provider"] is None for entry in entries):
            raise SourceLayoutError("Puertos: oferta de autoridad portuaria sin autoridad")
        return [
            Announcement(
                date="", process=f"{entry['title']} (Autoridad Portuaria: {entry['provider']})",
                title="Aparece en el portal de Puertos del Estado", url=entry["url"],
                access="libre", process_url=entry["url"], location=entry["provider"],
            )
            for entry in entries if not INTERNAL.search(entry["title"]) and entry["provider"] not in OWN_SOURCE
        ]
