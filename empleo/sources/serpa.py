"""SERPA (Sociedad de Servicios del Principado de Asturias).

`/empleo/ofertas.htm` es un tablón de novedades: cada bloque enlaza a la ficha de una oferta
(`{año}/{código}_{puesto}/….htm`) o a un acta en PDF de ese proceso. Las fichas (HTML antiguo en
Latin-1) traen el puesto, la fecha de publicación, «Tipo de contrato» y el plazo con hora:
«Hasta las 08:00 horas del 30 de abril de 2026». Ese día solo se puede presentar hasta esa hora.

Se leen las fichas enlazadas y se ofrecen las de plazo no vencido que no digan «anulado». Una
ficha sin fecha completa (alguna antigua da «del próximo lunes 7 de abril», sin año) no se
ofrece; si es del año en curso, la lectura falla para revisarla.

Las actas no se leen todavía: los bloques del tablón no tienen un orden fijo (fecha, puesto y
aviso cambian de párrafo) y habría que adivinar qué es cada cosa.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import FULL_DATE, MONTHS, first_date, spanish_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from ..sanitize import sanitize
from ..text import mixed_decode
from .base import Source

PAGE = "https://www.serpasa.es/empleo/ofertas.htm"
COMPANY = "SERPA"
FICHA = re.compile(r"^(\d{4})/(SP[^/]+)/[^/]+\.htm$", re.I)
CLOSING = re.compile(r"hasta\s+las\s+(\d{1,2})[:.](\d\d)\s*(?:h|horas)?\s+del?\s+(?:d[ií]a\s+)?"
                     r"(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")\s+de\s+(\d{4})", re.I)
CONTRACT = re.compile(r"Tipo de contrato:\s*([^.•]+)", re.I)
SEATS = re.compile(r"\((\d+)\)")
CANCELLED = re.compile(r"anulad[oa]", re.I)
KIND = {"indefinido": "indefinido", "temporal": "temporal"}


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).replace("\xa0", " ").strip()


def parse_board(html: str) -> list[dict]:
    """Fichas de oferta enlazadas desde el tablón, sin repetir."""
    soup = BeautifulSoup(html, "html.parser")
    blocks = soup.select("div.news-block")
    if not blocks:
        raise SourceLayoutError("SERPA: no se encuentra el tablón de ofertas")
    found: dict[str, dict] = {}
    for link in (a for block in blocks for a in block.find_all("a", href=True)):
        match = FICHA.match(link["href"])
        if match and match.group(2) not in found:
            found[match.group(2)] = {"ref": match.group(2), "year": int(match.group(1)),
                                     "url": urljoin(PAGE, link["href"])}
    return list(found.values())


def parse_ficha(html: str) -> dict | None:
    body = BeautifulSoup(html, "html.parser").select_one("#cuerpoderecha")
    title = body.select_one(".textolineacontrata") if body else None
    if title is None:
        return None
    text = _text(body)
    closing = CLOSING.search(text)
    day = spanish_date(*closing.group(3, 4, 5)) if closing else None
    published = next((p for p in body.select("p.textocontrata") if FULL_DATE.search(_text(p))), None)
    contract = CONTRACT.search(text)
    seats_line = next((p for p in body.select("p.textocontrata") if SEATS.search(_text(p))
                       and "puestos" in _text(p.find_previous("p")).lower()), None)
    literal = contract.group(1).strip() if contract else None
    paragraphs = [str(p) for p in body.select("p.textocontrata")]
    documents = [
        f'<li><a href="{escape(urljoin(PAGE, a["href"]), quote=True)}">{escape(_text(a))}</a></li>'
        for a in body.select("a.enlacedescarga[href]") if "bases" in _text(a).lower()
    ]
    return {
        "title": _text(title),
        "published_on": first_date(_text(published)).isoformat() if published else None,
        "deadline": day.isoformat() if day else None,
        "deadline_time": f"{int(closing.group(1)):02d}:{closing.group(2)}" if closing else None,
        "cancelled": bool(CANCELLED.search(text)),
        "contract": literal,
        "kind": KIND.get(literal.split()[0].lower()) if literal else None,
        "positions": int(SEATS.search(_text(seats_line)).group(1)) if seats_line else None,
        "description": sanitize("".join(paragraphs)),
        "documents": sanitize(f"<ul>{''.join(documents)}</ul>") if documents else None,
    }


class SerpaSource(Source):
    id = "serpa"
    name = "SERPA"
    homepage = PAGE
    scope = "Asturias"
    apply_label = "Ver las bases y cómo presentarse"

    def __init__(self) -> None:
        self._fichas: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = datetime.now(timezone.utc)
        today = today_madrid(now)
        self._fichas = {}
        for entry in parse_board(mixed_decode(http.get_bytes(PAGE))):
            ficha = parse_ficha(mixed_decode(http.get_bytes(entry["url"])))
            if ficha is None:
                raise SourceLayoutError(f"SERPA: la ficha {entry['ref']} ha cambiado de forma")
            if ficha["deadline"] is None and not ficha["cancelled"] and entry["year"] >= int(today[:4]):
                raise SourceLayoutError(f"SERPA: la ficha {entry['ref']} no trae un plazo legible")
            if ficha["deadline"] and ficha["deadline"] >= today and not ficha["cancelled"]:
                self._fichas[entry["ref"]] = {**ficha, "url": entry["url"]}
        return [
            ListedOffer(
                ref=ref, title=f["title"], company=COMPANY, url=f["url"], apply_url=f["url"], kind=f["kind"],
                positions=f["positions"], deadline=f["deadline"], deadline_time=f["deadline_time"],
                published_on=f["published_on"], contract=f["contract"],
            )
            for ref, f in self._fichas.items()
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref)
        if ficha is None:
            return OfferDetail()
        sections = [{"title": "Descripción de la oferta", "level": 2, "html": ficha["description"]}]
        if ficha["documents"]:
            sections.append({"title": "Documentos de la convocatoria", "level": 2, "html": ficha["documents"]})
        return OfferDetail(sections=sections)
