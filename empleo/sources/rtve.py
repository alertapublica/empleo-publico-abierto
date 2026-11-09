"""Corporación RTVE.

La web de convocatorias es una aplicación que lee una API JSON pública y sin sesión:
  - `convocatoria/getConvocatorias`: la convocatoria de personal fijo (1/2022) y el banco de datos.
  - `puestosOfertados/getPuestosOfertados?idConvocatoria=N`: ocupaciones con sus puestos, proceso,
    plazas, fechas de inscripción y los documentos publicados (listados, bolsas, adjudicaciones…).

Un puesto con la inscripción abierta es una oferta. Cada documento reciente es un anuncio: solo
se guarda su título, fecha y enlace, nunca el contenido de los listados de personas.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta
from html import escape
from urllib.parse import quote

from ..http import Client
from ..model import MADRID, Announcement, ListedOffer, OfferDetail, SourceLayoutError, selection_system
from ..sanitize import sanitize
from .base import Source

SITE = "https://convocatorias.rtve.es"
API = f"{SITE}/PLACOPUBLIC/api"
COMPANY = "Corporación RTVE"
RECENT_DAYS = 180  # los listados de hace años no son noticia
BANK = "BD"
SYSTEM_BY_PROCESS = {"proceso sólo méritos": "concurso", "proceso méritos y prueba": "concurso-oposicion"}


def _day(value) -> str | None:
    """Fecha de la API: ISO con o sin hora, o dd/mm/aaaa. Si llega algo distinto, es un cambio de formato."""
    if value in (None, ""):
        return None
    text = str(value).strip()
    iso = re.match(r"(\d{4})-(\d{2})-(\d{2})", text)
    spanish = re.match(r"(\d{2})/(\d{2})/(\d{4})", text)
    if iso:
        return f"{iso.group(1)}-{iso.group(2)}-{iso.group(3)}"
    if spanish:
        return f"{spanish.group(3)}-{spanish.group(2)}-{spanish.group(1)}"
    raise SourceLayoutError(f"RTVE: fecha con formato desconocido: {text!r}")


def _name(text: str | None) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text[:1].upper() + text[1:].lower() if text else ""


def _occupation(entry: dict) -> str:
    parts = [_name(entry.get("desOcupacionTipo")), _name(entry.get("especialidad"))]
    return " – ".join(part for part in parts if part)


def _json(raw: str, what: str) -> list:
    try:
        data = json.loads(raw)
    except ValueError as error:
        raise SourceLayoutError(f"RTVE: {what} no es JSON") from error
    if not isinstance(data, list):
        raise SourceLayoutError(f"RTVE: {what} no es una lista")
    return data


def parse_positions(raw: str, convocatoria: dict) -> list[dict]:
    """Un diccionario por puesto, con los datos de su ocupación y convocatoria."""
    positions = []
    for entry in _json(raw, "puestos ofertados"):
        for post in entry.get("puestos") or []:
            if "idPuesto" not in post or "proceso" not in post:
                raise SourceLayoutError("RTVE: puesto sin identificador o sin proceso")
            plazas = post.get("numPlazas")
            positions.append({
                "convocatoria": convocatoria["idConvocatoria"],
                "convocatoria_name": convocatoria["nombre"],
                "bank": convocatoria.get("tipoConvocatoria") == BANK,
                "id": post["idPuesto"],
                "occupation": _occupation(entry),
                "process": post["proceso"].get("desProceso") or "",
                "positions": plazas if isinstance(plazas, int) and plazas > 0 else None,
                "start": _day(post.get("fechaInicioInscripcion")),
                "end": _day(post.get("fechaFinInscripcion")),
                "bases": [b["fichero"] for b in entry.get("basesEspecificas") or [] if b.get("fichero")],
                "documents": [
                    {"date": _day(d.get("fechaPublicacion")),
                     "title": (d.get("tipoDocPuesto") or {}).get("desDocumento") or "",
                     "file": d.get("docPublico")}
                    for d in post.get("docsPuesto") or []
                ],
            })
    return positions


def _system(post: dict) -> str | None:
    """El nombre del proceso lo dice a veces; si no, sus documentos: méritos y prueba práctica."""
    known = SYSTEM_BY_PROCESS.get(post["process"].lower())
    if known:
        return known
    titles = " ".join(d["title"].lower() for d in post["documents"])
    if "prueba" in titles and "mérito" in titles:
        return "concurso-oposicion"
    return selection_system(titles)


def _documents_url(position: dict, file: str) -> str:
    return f"{SITE}/Documentos/convocatoria-{position['convocatoria']}/listados/{quote(file)}"


class RtveSource(Source):
    id = "rtve"
    name = "Corporación RTVE"
    homepage = f"{SITE}/"
    apply_label = "Inscribirse en la web de convocatorias de RTVE"

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._positions: list[dict] = []

    def _load(self, http: Client) -> list[dict]:
        found = []
        for convocatoria in _json(http.get(f"{API}/convocatoria/getConvocatorias"), "convocatorias"):
            if convocatoria.get("ocultarConvocatoria") or "idConvocatoria" not in convocatoria:
                continue
            raw = http.get(f"{API}/puestosOfertados/getPuestosOfertados?idConvocatoria={convocatoria['idConvocatoria']}")
            found.extend(parse_positions(raw, convocatoria))
        return found

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._positions = self._load(http)
        today = (self._today or datetime.now(MADRID).date()).isoformat()
        offers = []
        for post in self._positions:
            # Abierta: ya empezó la inscripción y todavía no ha terminado. Sin fechas no hay oferta.
            if not post["end"] or post["end"] < today or (post["start"] and post["start"] > today):
                continue
            offers.append(ListedOffer(
                ref=f"{post['convocatoria']}-{post['id']}", title=post["occupation"], company=COMPANY,
                url=self.homepage, apply_url=self.homepage,
                kind="bolsa" if post["bank"] else "indefinido",
                positions=post["positions"], category=post["process"] or None, deadline=post["end"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        post = next((p for p in self._positions if f"{p['convocatoria']}-{p['id']}" == offer.ref), None)
        if post is None:
            return OfferDetail()
        lines = [f"<li><strong>Convocatoria:</strong> {escape(post['convocatoria_name'])}</li>"]
        if post["process"]:
            lines.append(f"<li><strong>Proceso:</strong> {escape(post['process'])}</li>")
        if post["start"] and post["end"]:
            first, last = (date.fromisoformat(post[k]).strftime("%d/%m/%Y") for k in ("start", "end"))
            lines.append(f"<li><strong>Inscripción:</strong> del {first} al {last}</li>")
        sections = [{"title": "Datos del puesto", "level": 2, "html": sanitize(f"<ul>{''.join(lines)}</ul>")}]
        if post["bases"]:
            base = f"{SITE}/Documentos/convocatoria-{post['convocatoria']}/bases-especificas/"
            items = "".join(f'<li><a href="{escape(base + quote(b), quote=True)}">Bases específicas</a></li>'
                            for b in post["bases"])
            sections.append({"title": "Documentos de la convocatoria", "level": 2, "html": sanitize(f"<ul>{items}</ul>")})
        return OfferDetail(sections=sections)

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Documentos publicados en los últimos meses: solo título, fecha y enlace."""
        limit = ((self._today or datetime.now(MADRID).date()) - timedelta(days=RECENT_DAYS)).isoformat()
        items = []
        for post in self._positions:
            name = post["convocatoria_name"]
            name = name if name.lower().startswith("convocatoria") else f"Convocatoria {name}"
            process = f"{name} · {post['occupation']} · {post['process']}"
            for document in post["documents"]:
                if document["date"] and document["date"] >= limit and document["file"] and document["title"]:
                    items.append(Announcement(
                        date=document["date"], process=process.strip(" ·"),
                        title=document["title"], url=_documents_url(post, document["file"]),
                        via="bolsa" if post["bank"] else "otro",
                        access="libre" if "libre" in post["process"].lower() else None,
                        contract=None if post["bank"] else "indefinido", system=_system(post),
                        process_url=self.homepage,
                    ))
        return items
