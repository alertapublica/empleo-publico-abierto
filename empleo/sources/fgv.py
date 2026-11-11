"""FGV (Ferrocarrils de la Generalitat Valenciana).

WordPress con la API REST desactivada. «Convocatorias en proceso» muestra, en el árbol de páginas
(`li.current_page_item > ul.children`), una página por convocatoria con su título literal en
mayúsculas y, debajo, una subpágina por comunicado («Listado provisional de méritos», «Fecha examen
…»). Ni las subpáginas ni el árbol tienen fecha: los comunicados van sin ella, ordenados por el id de
la página (`page-item-41426`), que crece con cada alta. Una convocatoria anulada lleva «ANULADA:»
delante del título: se da por terminada.

El plazo está en la subpágina «Apertura plazo y formulario de inscripción …» (o «Nuevo plazo …»,
«Ampliación del plazo …»): «Inicio: miércoles 21 de octubre de 2026 a las 12:00 horas» y «Fin:
viernes 30 de octubre de 2026 a las 11:59 horas». Es oferta una convocatoria con plazo sin vencer y
sin listados ni otras fases después; las demás son procesos. Se piden las subpáginas de plazo solo de
las convocatorias sin esas fases (hoy, dos).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from html import escape

from bs4 import BeautifulSoup

from ..dates import MONTHS, latest, spanish_date
from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed, process_type, \
    selection_system
from ..sanitize import sanitize
from ..text import humane_caps
from .base import Source

PAGE = "https://www.fgv.es/la-empresa/trabaja-con-nosotros/convocatorias/convocatorias-en-proceso-fgv/"
COMPANY = "FGV"
DEADLINE_PAGE = re.compile(r"plazo", re.I)
# Fases que solo existen cuando la inscripción ya terminó.
AFTER_REGISTRATION = re.compile(
    r"listado|resultado|examen|prueba|cuaderno|puntuaci|asignaci|admitid|aspirantes|bolsa|devoluci|m[ée]ritos", re.I)
WHEN = r"(?:\w+\s+)?(\d{1,2}) de (" + "|".join(MONTHS) + r") de (\d{4})(?:\s+a las (\d{1,2}[:.]\d{2}))?"
START = re.compile(r"Inicio:\s*" + WHEN, re.I)
END = re.compile(r"Fin:\s*" + WHEN, re.I)
JOB = re.compile(r"PARA (?:LA )?COBERTURA DE (?:LOS |DETERMINADOS )?(?:PUESTOS DE TRABAJO (?:DE )?|PUESTOS DE )?(.+?)"
                 r"(?: CORRESPONDIENTES?\b| DE LAS OFERTAS\b| EN LAS\b| QUE\b|[.,]|$)", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _page_id(li) -> int:
    for name in li.get("class", []):
        if name.startswith("page-item-") and name[10:].isdigit():
            return int(name[10:])
    raise SourceLayoutError("FGV: página sin id en el árbol")


def parse_page(html: str) -> list[dict]:
    """Las convocatorias en el orden de la web; sus comunicados, del más reciente al más antiguo."""
    current = BeautifulSoup(html, "html.parser").select_one("li.current_page_item")
    if current is None:
        raise SourceLayoutError("FGV: no se encuentra el árbol de convocatorias en proceso")
    found = []
    for li in current.select(":scope > ul.children > li"):
        link = li.find("a", href=True)
        title = _clean(link.get_text(" ")) if link else ""
        if not title:
            raise SourceLayoutError("FGV: convocatoria sin título")
        notices = []
        for child in li.select(":scope > ul.children > li"):
            child_link = child.find("a", href=True)
            if child_link is None or not _clean(child_link.get_text(" ")):
                raise SourceLayoutError(f"FGV: comunicado sin título en «{title}»")
            notices.append({"id": _page_id(child), "title": _clean(child_link.get_text(" ")),
                            "url": child_link["href"]})
        notices.sort(key=lambda n: n["id"], reverse=True)
        found.append({"ref": str(_page_id(li)), "title": title, "url": link["href"], "notices": notices,
                      "cancelled": title.upper().startswith("ANULADA")})
    if not found:
        raise SourceLayoutError("FGV: no hay convocatorias en proceso")
    return found


def _when(match) -> tuple:
    day, month, year, hour = match.groups()
    return spanish_date(day, month, year), hour.replace(".", ":") if hour else None


def deadline_page(html: str) -> dict:
    """Inicio y fin del plazo de una subpágina de plazo, y su texto literal."""
    article = BeautifulSoup(html, "html.parser").select_one("article")
    if article is None:
        raise SourceLayoutError("FGV: subpágina de plazo sin contenido")
    text = article.get_text("\n")
    ends = [_when(m) for m in END.finditer(text)]
    starts = [_when(m) for m in START.finditer(text)]
    lines = [_clean(line) for line in text.splitlines() if re.match(r"\s*(Inicio|Fin):", line)]
    return {"end": [e for e in ends if e[0]], "start": [s for s in starts if s[0]], "lines": lines}


def _is_candidate(item: dict) -> bool:
    return (not item["cancelled"] and any(DEADLINE_PAGE.search(n["title"]) for n in item["notices"])
            and not any(AFTER_REGISTRATION.search(n["title"]) for n in item["notices"]))


def _job(title: str) -> str:
    match = JOB.search(title)
    return humane_caps(match.group(1) if match else title)


class FgvSource(Source):
    id = "fgv"
    name = "FGV (Ferrocarrils de la Generalitat Valenciana)"
    homepage = PAGE
    scope = "Comunitat Valenciana"
    apply_label = "Ver el plazo y el formulario de inscripción"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._items: list[dict] | None = None
        self._open: dict[str, dict] = {}  # ref → plazo, de las convocatorias que son oferta

    def _read(self, http: Client) -> list[dict]:
        if self._items is None:
            self._items = parse_page(http.get(PAGE))
            now = self._now or datetime.now(timezone.utc)
            for item in filter(_is_candidate, self._items):
                pages = [(n, deadline_page(http.get(n["url"]))) for n in item["notices"] if DEADLINE_PAGE.search(n["title"])]
                day, hour = latest([end for _, page in pages for end in page["end"]])
                if day is None or deadline_passed(day.isoformat(), hour, now):
                    continue
                newest = pages[0]  # la subpágina de plazo más reciente
                starts = newest[1]["start"]
                self._open[item["ref"]] = {
                    "deadline": day.isoformat(), "deadline_time": hour, "apply_url": newest[0]["url"],
                    "opens_on": starts[0][0].isoformat() if starts else None,
                    "lines": [line for _, page in pages for line in page["lines"]],
                }
        return self._items

    def list_offers(self, http: Client) -> list[ListedOffer]:
        offers = []
        for item in self._read(http):
            data = self._open.get(item["ref"])
            if data is None:
                continue
            offers.append(ListedOffer(
                ref=item["ref"], title=_job(item["title"]), company=COMPANY, url=item["url"],
                apply_url=data["apply_url"], kind=None, deadline=data["deadline"],
                deadline_time=data["deadline_time"], opens_on=data["opens_on"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        item = next((i for i in self._read(http) if i["ref"] == offer.ref), None)
        if item is None or item["ref"] not in self._open:
            return OfferDetail()
        lines = "".join(f"<li>{escape(line)}</li>" for line in dict.fromkeys(self._open[item["ref"]]["lines"]))
        pages = "".join(f'<li><a href="{escape(n["url"], quote=True)}">{escape(n["title"])}</a></li>'
                        for n in item["notices"])
        sections = [{"title": "Convocatoria", "level": 2, "html": sanitize(f"<p>{escape(item['title'])}</p>")}]
        if lines:
            sections.append({"title": "Plazo de presentación de solicitudes", "level": 2,
                             "html": sanitize(f"<ul>{lines}</ul>")})
        if pages:
            sections.append({"title": "Información publicada", "level": 2, "html": sanitize(f"<ul>{pages}</ul>")})
        return OfferDetail(sections=sections)

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Las subpáginas de las convocatorias que no son oferta, sin fecha, y la propia convocatoria."""
        items = []
        for item in self._read(http):
            if item["ref"] in self._open:
                continue
            via = "oep" if re.search(r"ofertas? de empleo p[úu]blico", item["title"], re.I) else process_type(item["title"])
            notices = item["notices"] + [{"title": item["title"], "url": item["url"]}]
            items += [Announcement(
                date="", process=item["title"], title=n["title"], url=n["url"], via=via,
                system=selection_system(item["title"]), state="finalizado" if item["cancelled"] else "curso",
                process_url=item["url"],
            ) for n in notices]
        return items
