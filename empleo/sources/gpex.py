"""GPEX (Gestión Pública de Extremadura), portal Candidat@ en `candidato.gpex.es`.

Dos publicaciones distintas:

- «Procesos Abiertos»: tarjetas con «Plazo de la oferta: DD/MM/AAAA - DD/MM/AAAA», referencia y
  puesto (`BC26342 Personal Técnico Medio Ambiental`) y plazas, seis por página. La ficha repite
  el plazo («Desde el día … hasta el día …, ambos inclusive») y da emplazamiento, «Causa del
  contrato ofertado» (se guarda literal) y requisitos. Son ofertas.
- «Anuncios Ofertas de Empleo / Selección mediante gestión interna de bolsa»: GPEX avisa de que
  seleccionará un perfil entre quienes estén inscritos en su bolsa general 48 horas después de
  publicar el anuncio. No tienen plazo propio: van a procesos, como bolsa, con su fecha.

Las páginas mezclan codificaciones: la plantilla va en Latin-1 y los datos en UTF-8.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, today_madrid
from ..sanitize import sanitize
from ..text import mixed_decode as decode
from .base import Source

HOST = "https://candidato.gpex.es/"
OPEN = f"{HOST}index.php?modulo=ofertas_publico&pagina=index.php"
NOTICES = f"{HOST}index.php?modulo=anuncios"
COMPANY = "GPEX"
MAX_PAGES = 10
PAGE_SIZE = 6
OFFER_ID = re.compile(r"id_oferta=(\d+)")
NOTICE_ID = re.compile(r"id_noticia=(\d+)")
RANGE = re.compile(r"(\d\d/\d\d/\d{4})\s*-\s*(\d\d/\d\d/\d{4})")
DATE = re.compile(r"\d\d/\d\d/\d{4}")
SKIPPED_SECTIONS = {"PROCEDIMIENTO", "CONSIDERACIONES"}


def _text(node) -> str:
    return re.sub(r"\s+", " ", node.get_text(" ")).strip()


def _cards(html: str, what: str) -> list:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#contenido #ofertas")
    if container is None:
        # Sin nada publicado no hay lista, solo el aviso «No hay Anuncios de ofertas de empleo
        # disponibles actualmente».
        notice = soup.select_one("#contenido .informacion")
        if notice is not None and _text(notice).startswith("No hay "):
            return []
        raise SourceLayoutError(f"GPEX: no se encuentra la lista de {what}")
    return container.select("#dtos_oferta")


def parse_open(html: str) -> list[dict]:
    entries = []
    for card in _cards(html, "procesos abiertos"):
        link = card.find("a", href=OFFER_ID)
        dates = RANGE.search(_text(card.select_one(".fecha_oferta") or card))
        name = card.select_one(".texto_oferta")
        if not (link and dates and name):
            raise SourceLayoutError("GPEX: proceso sin enlace, plazo o puesto")
        seats = card.select_one(".numero")
        area = card.select_one(".titulo_oferta")
        entries.append({
            "ref": OFFER_ID.search(link["href"]).group(1),
            "title": _text(name),
            "url": f"{HOST}index.php?modulo=ofertas_publico&pagina=ver.php&id_oferta={OFFER_ID.search(link['href']).group(1)}",
            "opens_on": numeric_date(dates.group(1)),
            "deadline": numeric_date(dates.group(2)),
            "positions": int(_text(seats)) if seats and _text(seats).isdigit() else None,
            "area": _text(area) if area else None,
        })
    return entries


def parse_notices(html: str) -> list[Announcement]:
    notices = []
    for card in _cards(html, "anuncios"):
        link = card.find("a", href=NOTICE_ID)
        date = DATE.search(_text(card.select_one(".fecha_oferta") or card))
        title = card.select_one(".titulo_oferta")
        if not (link and date and title):
            raise SourceLayoutError("GPEX: anuncio sin enlace, fecha o título")
        url = f"{HOST}index.php?modulo=anuncios&pagina=ver.php&id_noticia={NOTICE_ID.search(link['href']).group(1)}"
        notices.append(Announcement(
            date=numeric_date(date.group(0)), process=_text(title), title=_text(title), url=url,
            via="bolsa", process_url=url,
        ))
    return notices


def parse_detail(html: str) -> OfferDetail | None:
    """Apartados de la ficha como listas de «etiqueta: valor»; el emplazamiento y el contrato aparte."""
    tables = BeautifulSoup(html, "html.parser").select("table.tabla_oferta")
    if not tables:
        return None
    sections, fields, current = [], {}, None
    for row in (tr for table in tables for tr in table.find_all("tr")):
        heading = row.select_one("td.titulo_apartado")
        if heading:
            current = {"title": _text(heading).capitalize(), "items": []}
            if _text(heading).upper() not in SKIPPED_SECTIONS:
                sections.append(current)
            continue
        cells = row.find_all("td", recursive=False)
        values = [c for c in cells if "txt_normal" in (c.get("class") or []) and "txt_normal_neg" not in c["class"]]
        labels = [c for c in cells if "txt_normal_neg" in (c.get("class") or [])]
        if not values or not _text(values[0]):
            continue
        label = _text(labels[0]) if labels else None
        if label:
            fields[label] = _text(values[0])
        if current is not None:
            current["items"].append((label, values[0].decode_contents()))
    rendered = []
    for section in sections:
        items = "".join(
            f"<li><strong>{escape(label)}:</strong> {body}</li>" if label else f"<li>{body}</li>"
            for label, body in section["items"]
        )
        if items:
            rendered.append({"title": section["title"], "level": 2, "html": sanitize(f"<ul>{items}</ul>")})
    return OfferDetail(
        sections=rendered,
        location=fields.get("Emplazamiento y/o puesto de trabajo"),
        contract=fields.get("Causa del contrato ofertado"),
    )


class GpexSource(Source):
    id = "gpex"
    name = "GPEX (Gestión Pública de Extremadura)"
    homepage = OPEN
    title_code = re.compile(r"(?P<code>[A-Z]{2}\d{5})\s+(?P<title>.+)")  # «BC26342 Personal Técnico…»
    scope = "Extremadura"
    apply_label = "Inscribirse en el Portal Candidat@"

    def __init__(self) -> None:
        self._areas: dict[str, str] = {}

    def _pages(self, http: Client, base: str, parse, key) -> list:
        """Páginas de seis en seis hasta una incompleta o que no añada nada."""
        found: dict = {}
        for page in range(MAX_PAGES):
            items = parse(decode(http.get_bytes(f"{base}&limite={page * PAGE_SIZE}")))
            new = {key(item): item for item in items if key(item) not in found}
            found.update(new)
            if len(items) < PAGE_SIZE or not new:
                return list(found.values())
        raise SourceLayoutError(f"GPEX: más de {MAX_PAGES} páginas en {base}")

    def list_offers(self, http: Client) -> list[ListedOffer]:
        today = today_madrid(datetime.now(timezone.utc))
        entries = [e for e in self._pages(http, OPEN, parse_open, lambda e: e["ref"]) if e["deadline"] >= today]
        self._areas = {e["ref"]: e["area"] for e in entries if e["area"]}
        return [
            ListedOffer(
                ref=entry["ref"], title=entry["title"], company=COMPANY, url=entry["url"], apply_url=entry["url"],
                kind=None, positions=entry["positions"], opens_on=entry["opens_on"], deadline=entry["deadline"],
            )
            for entry in entries
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return parse_detail(decode(http.get_bytes(offer.url)))

    def list_announcements(self, http: Client) -> list[Announcement]:
        return self._pages(http, NOTICES, parse_notices, lambda notice: notice.url)

    def enrich(self, http: Client) -> dict[str, dict]:
        # El área viene en el listado («GPEX / Área TIC»): no hace falta otra petición.
        return {ref: {"department": re.sub(r"^GPEX\s*/\s*", "", area)} for ref, area in self._areas.items()}
