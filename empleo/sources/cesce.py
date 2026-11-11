"""CESCE (Compañía Española de Seguros de Crédito a la Exportación).

`Trabaja en CESCE` (Liferay) lista las convocatorias en `.listado-convocatorias`, cada una en un
`.journal-content-article`: título literal («CONVOCATORIA DEL 10 DE NOVIEMBRE DE 2026 DE PROCESO DE
SELECCIÓN PARA CONTRATACIÓN INDEFINIDA DE UN PUESTO DE …»), fecha, estado («Abierta», «Proceso») y
sus documentos, cada uno con «(Fecha de publicación dd.mm.aaaa)». La misma página tiene otro listado
para agentes mediadores (tras `carreras.mediadores@cesce.es`): no son empleos y no se lee.

El plazo solo está en el PDF de la convocatoria («desde el día 10 de noviembre hasta el día 22 de
noviembre, ambos incluidos», sin año ni hora) y en las ampliaciones («hasta el 25 de octubre de
2026»). Sin año, vale el de la publicación del documento, o el siguiente si la fecha quedaría antes.
Entre la convocatoria y sus ampliaciones, vale la fecha mayor.

Como SEPI: es oferta la convocatoria «Abierta» con plazo legible y sin vencer; las demás son procesos
cuyos comunicados son sus documentos, con su fecha, salvo los anexos (perfil y modelo de solicitud).
Cada lectura pide el PDF de las convocatorias abiertas (hoy una) y de sus ampliaciones.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import MONTHS, latest, spanish_date
from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed, process_type
from ..pdftext import read_pdf
from ..sanitize import sanitize
from ..text import humane_caps
from .base import Source

PAGE = "https://www.cesce.es/es/corporativo/trabaja-en-cesce"
COMPANY = "CESCE"
PUBLISHED = re.compile(r"\s*\(Fecha de publicaci[óo]n (\d{2})\.(\d{2})\.(\d{4})\)\s*$", re.I)
# La frase del plazo: «plazo de admisión de solicitudes … hasta el [día] 22 de noviembre[ de 2026]».
APPLY = re.compile(
    r"plazo de (?:admisi[óo]n|presentaci[óo]n) de solicitudes\b[^.]*?hasta el (?:d[ií]a )?(\d{1,2}) de ("
    + "|".join(MONTHS) + r")(?: de (\d{4}))?", re.I)
JOB = re.compile(r"\bPUESTOS? (?:DE )?(.+?)\s*(?:\(|$)", re.I)
STATES = {"abierta": "abierto", "proceso": "curso"}
FINISHED = re.compile(r"finalizad|cerrad|resuelt|desiert|anulad", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _state(text: str) -> str:
    lowered = text.lower()
    if lowered in STATES:
        return STATES[lowered]
    if FINISHED.search(lowered):
        return "finalizado"
    raise SourceLayoutError(f"CESCE: estado desconocido «{text}»")


def _is_jobs_list(listing) -> bool:
    """El listado de empleo, no el de agentes mediadores: lo dice el correo que lo precede."""
    mail = listing.find_previous(string=re.compile(r"@cesce\.es"))
    return mail is None or "mediador" not in mail.lower()


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listings = [listing for listing in soup.select(".listado-convocatorias") if _is_jobs_list(listing)]
    if not listings:
        raise SourceLayoutError("CESCE: no se encuentra el listado de convocatorias")
    found = []
    for article in (a for listing in listings for a in listing.select(".journal-content-article")):
        question, state = article.select_one(".question"), article.select_one(".question .state")
        title = question.find(string=True, recursive=False) if question else None
        if not title or not _clean(title) or state is None:
            raise SourceLayoutError("CESCE: convocatoria sin título o sin estado")
        documents = []
        for link in article.select(".answer a[href]"):
            label = _clean(link.get_text(" "))
            published = PUBLISHED.search(label)
            if not published:
                raise SourceLayoutError(f"CESCE: documento sin fecha de publicación: «{label}»")
            day, month, year = published.groups()
            documents.append({"label": label[:published.start()].strip(), "date": f"{year}-{month}-{day}",
                              "url": urljoin(PAGE, link["href"])})
        if not documents:
            raise SourceLayoutError(f"CESCE: convocatoria sin documentos: «{_clean(title)}»")
        found.append({
            "ref": article.get("data-analytics-asset-id") or documents[0]["url"],
            "title": _clean(title), "state": _state(_clean(state.get_text(" "))), "documents": documents,
        })
    if not found:
        raise SourceLayoutError("CESCE: el listado no tiene convocatorias")
    return found


def deadlines_in(text: str, published: date) -> list[tuple[date, str | None]]:
    """Últimos días del plazo de solicitudes; sin año, el de la publicación (o el siguiente)."""
    found = []
    for day, month, year in APPLY.findall(text):
        when = spanish_date(day, month, year or published.year)
        if when and not year and when < published:
            when = spanish_date(day, month, published.year + 1)
        if when:
            found.append((when, None))
    return found


def sentences_of(text: str) -> list[str]:
    """Las frases literales del plazo de solicitudes, sin el encabezado en mayúsculas que las precede."""
    found = []
    for part in re.split(r"(?<=\.)\s+", text):
        if APPLY.search(part):
            start = re.search(r"\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]", part)
            found.append(part[start.start():] if start else part)
    return found


def _kind(title: str) -> str | None:
    lowered = title.lower()
    if "contratación indefinida" in lowered or "contratacion indefinida" in lowered:
        return "indefinido"
    if "temporal" in lowered:
        return "temporal"
    return None


def _job(title: str) -> str:
    match = JOB.search(title)
    return humane_caps(match.group(1) if match else title)


class CesceSource(Source):
    id = "cesce"
    name = "CESCE"
    homepage = PAGE
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._items: list[dict] | None = None  # el listado, leído en list_offers
        self._deadlines: dict[str, tuple[date | None, list[str]]] = {}  # ref → (último día, frases)

    def _read(self, http: Client) -> list[dict]:
        if self._items is None:
            self._items = parse_page(http.get(PAGE))
        return self._items

    def _deadline(self, http: Client, item: dict) -> date | None:
        """Plazo de una convocatoria abierta, del PDF de la convocatoria y de sus ampliaciones."""
        if item["ref"] not in self._deadlines:
            found, sentences = [], []
            for document in item["documents"]:
                label = document["label"].lower()
                if not (label.startswith("convocatoria") or label.startswith("ampliaci")):
                    continue
                text = read_pdf(http, document["url"], f"CESCE, {document['label']}")
                found += deadlines_in(text, date.fromisoformat(document["date"]))
                sentences += sentences_of(text)
            self._deadlines[item["ref"]] = (latest(found)[0], sentences)
        return self._deadlines[item["ref"]][0]

    def _is_offer(self, http: Client, item: dict) -> bool:
        if item["state"] != "abierto":
            return False
        deadline = self._deadline(http, item)
        return deadline is not None and not deadline_passed(deadline.isoformat(), None, self._now or datetime.now(timezone.utc))

    def list_offers(self, http: Client) -> list[ListedOffer]:
        return [
            ListedOffer(
                ref=item["ref"], title=_job(item["title"]), company=COMPANY, url=PAGE, apply_url=PAGE,
                kind=_kind(item["title"]), positions=1 if " UN PUESTO" in item["title"].upper() else None,
                deadline=self._deadline(http, item).isoformat(),
                published_on=item["documents"][0]["date"],
            )
            for item in self._read(http) if self._is_offer(http, item)
        ]

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        item = next((i for i in self._read(http) if i["ref"] == offer.ref), None)
        if item is None:
            return OfferDetail()
        sentences = self._deadlines.get(item["ref"], (None, []))[1]
        documents = "".join(
            f'<li><a href="{escape(d["url"], quote=True)}">{escape(d["label"])}</a> '
            f'(publicado el {date.fromisoformat(d["date"]).strftime("%d/%m/%Y")})</li>'
            for d in item["documents"])
        sections = [{"title": "Convocatoria", "level": 2, "html": sanitize(f"<p>{escape(item['title'])}</p>")}]
        if sentences:
            plazo = "".join(f"<p>{escape(s)}</p>" for s in dict.fromkeys(sentences))
            sections.append({"title": "Plazo", "level": 2, "html": sanitize(plazo)})
        sections.append({"title": "Documentos de la convocatoria", "level": 2,
                         "html": sanitize(f"<ul>{documents}</ul>")})
        return OfferDetail(sections=sections)

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Los documentos de las convocatorias que ya no son oferta, con su fecha; los anexos no."""
        items = []
        for item in self._read(http):
            if self._is_offer(http, item):
                continue
            state = item["state"]
            if state == "abierto" and self._deadline(http, item) is not None:
                state = "curso"  # la web aún dice «Abierta», pero el plazo ya venció
            for document in item["documents"]:
                if document["label"].lower().startswith("anexo"):
                    continue
                items.append(Announcement(
                    date=document["date"], process=item["title"], title=document["label"], url=document["url"],
                    via=process_type(item["title"]), contract=_kind(item["title"]), state=state,
                    process_url=PAGE,
                ))
        return items
