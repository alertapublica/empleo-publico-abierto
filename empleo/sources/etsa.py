"""ETSA (Etsa Global Logistics, grupo Enusa).

La página «Trabaja con nosotros» lista las entradas con fecha, referencia y título. Cada una
tiene su ficha: si admite candidaturas lleva el plazo («antes del 11 de noviembre de 2026 a las
15.00 horas»; la hora solo se guarda si la ficha la da para ese día), las
bases y el correo al que enviarlas; si el proceso avanzó, solo enlaza el listado o resultado.

Una entrada con plazo es una oferta; las demás, un anuncio por documento publicado.
"""
from __future__ import annotations

import re
from datetime import datetime
from html import escape

from bs4 import BeautifulSoup, Comment

from ..dates import first_date, hour_on
from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, selection_system
from ..sanitize import sanitize
from .base import Source

PAGE = "https://www.etsa.es/trabaja-con-nosotros/"
COMPANY = "ETSA"
REFERENCE = re.compile(r"Referencia:\s*(\S+)")
DEADLINE = re.compile(r"antes del\s+(\d{1,2}\s+de\s+[a-záéíóú]+\s+de\s+\d{4})", re.I)


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def parse_listing(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    posts = soup.select("div.post")
    if not posts and "no hay" not in soup.get_text(" ").lower():
        raise SourceLayoutError("ETSA: no se encuentra la lista de entradas")
    for post in posts:
        day = post.select_one("p.date")
        reference = post.select_one("p.cat")
        link = post.select_one("a[href]")
        title = post.select_one("h3")
        match = REFERENCE.search(reference.get_text(" ")) if reference else None
        stamp = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", _clean(day.get_text())) if day else None
        if not (stamp and match and link and title):
            raise SourceLayoutError("ETSA: entrada sin fecha, referencia, enlace o título")
        entries.append({
            "ref": match.group(1), "title": _clean(title.get_text(" ")), "url": link["href"],
            "date": f"{stamp.group(3)}-{stamp.group(2)}-{stamp.group(1)}",
        })
    return entries


def parse_ficha(html: str) -> dict:
    """Plazo, documentos y texto de una ficha."""
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one(".section_content_single_")
    if body is None:
        raise SourceLayoutError("ETSA: la ficha no tiene contenido")
    for comment in body.find_all(string=lambda text: isinstance(text, Comment)):
        comment.extract()
    for node in body.find_all(["script", "style"]):
        node.decompose()
    documents = []
    for anchor in body.find_all("a", href=True):
        label = _clean(anchor.get_text(" ")).lstrip("->").strip()
        label = re.sub(r"^Ver\s+", "", label, flags=re.I)
        if "politica-privacidad" in anchor["href"] or not label:
            continue
        documents.append((label[:1].upper() + label[1:], anchor["href"]))
    text = _clean(body.get_text(" "))
    match = DEADLINE.search(text)
    found = first_date(match.group(1)) if match else None
    return {"deadline": found.isoformat() if found else None,
            "deadline_time": hour_on(text, found) if found else None, "documents": documents,
            "html": sanitize(body.decode_contents())}


def _kind(entry: dict, ficha: dict) -> str:
    if "temporal" in entry["title"].lower():
        return "temporal"
    return "indefinido" if any("indef" in url.lower() for _, url in ficha["documents"]) else "temporal"


class EtsaSource(Source):
    id = "etsa"
    name = "ETSA"
    homepage = PAGE
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self) -> None:
        self._entries: list[dict] = []

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._entries = parse_listing(http.get(PAGE))
        offers = []
        for entry in self._entries:
            entry["ficha"] = parse_ficha(http.get(entry["url"]))
            if entry["ficha"]["deadline"]:
                offers.append(ListedOffer(
                    ref=entry["ref"], title=entry["title"], company=COMPANY, url=entry["url"],
                    apply_url=entry["url"], kind=_kind(entry, entry["ficha"]),
                    deadline=entry["ficha"]["deadline"], deadline_time=entry["ficha"]["deadline_time"],
                ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        entry = next((e for e in self._entries if e["ref"] == offer.ref), None)
        if entry is None:
            return OfferDetail()
        return OfferDetail(sections=[{"title": "Cómo presentar la candidatura", "level": 2,
                                      "html": entry["ficha"]["html"]}])

    def enrich(self, http: Client) -> dict[str, dict]:
        return {e["ref"]: {"published_on": e["date"]} for e in self._entries}

    def list_announcements(self, http: Client) -> list[Announcement]:
        items = []
        for entry in self._entries:
            if entry["ficha"]["deadline"]:
                continue
            ficha = entry["ficha"]
            system = selection_system(" ".join([ficha["html"], *(label for label, _ in ficha["documents"])]))
            for label, url in ficha["documents"]:
                items.append(Announcement(
                    date=entry["date"], process=f"{entry['title']} ({entry['ref']})", title=label,
                    url=url, access="libre", contract=_kind(entry, ficha), system=system,
                    process_url=entry["url"],
                ))
        return items
