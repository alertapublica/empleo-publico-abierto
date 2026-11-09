"""Enusa Industrias Avanzadas.

Bolsa de trabajo de Cegid (Talent), con sesión de invitado: una petición a la página de entrada
y un POST a `/servlet/login` con `_TYPE_LOGON=ANONYMOUS` devuelven una sola página con la lista
de procesos y, oculta, la descripción completa de cada uno.

Un proceso con plazo de inscripción es una oferta. Uno sin plazo, porque ya publica el resultado
de la revisión de requisitos, es un anuncio. De esas listas de candidaturas no se copia nada.
"""
from __future__ import annotations

import re
from datetime import date

from bs4 import BeautifulSoup

from ..dates import month_number
from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, selection_system
from ..sanitize import sanitize
from .base import Source

HOST = "https://engljobsite.pn.cegid.cloud"
LANDING = f"{HOST}/jobsite_g/espanol/generico_login.jsp?zjslanguser=es"
LOGIN = f"{HOST}/servlet/login"
PAGE = "https://www.enusa.es/trabaja-con-nosotros/"
GUEST = {
    "_TYPE_LOGON": "ANONYMOUS",
    "_URL": "/servlet/CheckSecurity/JSP/jobsite/js_proces_anonymous.jsp",
    "M4_ORGANIZATION": "ENGL",
    "_LANG": "3",
    "_PROC": "",
}
COMPANY = "Enusa"
COUNT = re.compile(r"N[úu]m\. de ofertas:\s*(\d+)")
DEADLINE = re.compile(
    r"hasta el pr[óo]ximo d[íi]a\s+(\d{1,2})\s+de\s+([a-záéíóú]+)(?:\s+de\s+(\d{4}))?", re.I)
PUBLISHED = re.compile(r"Fecha de publicaci[óo]n\s+(\d{2})/(\d{2})/(\d{4})")
NEXT_FIELD = r"(?=\s+(?:Horario|Jornada|Grupo|Salario|Contrato|R[ée]gimen)\b|[.;]|$)"
WORKPLACE = re.compile(r"U\s*bicaci[oó]n\s*:\s*Centro de trabajo de\s+(.+?)" + NEXT_FIELD)
WORKPLACE_INTRO = re.compile(r"centro (?:de trabajo )?de\s+([^.,;]+?)(?:\s+(?:dependiente|en la|como)\b|[.,;])", re.I)
ONE_POSITION = re.compile(r"necesita cubrir\s+(?:1|un|una)\s+(?:puesto|vacante)", re.I)
RESULT = "resultado de la revisión de requisitos"


def _clean(text: str) -> str:
    return re.sub(r"[\s​\xa0]+", " ", text).strip()


def _deadline(text: str, published: str | None) -> str | None:
    """Último día de inscripción. Si lo amplían, el aviso añade una fecha posterior: vale la mayor.

    Algunas ofertas omiten el año («hasta el próximo día 11 de noviembre»): se toma el de la
    publicación, o el siguiente si así la fecha quedara antes de publicarse."""
    start = date.fromisoformat(published) if published else None
    days = []
    for day, month, year in DEADLINE.findall(text):
        number = month_number(month)
        if number is None:
            continue
        if year:
            days.append(date(int(year), number, int(day)))
        elif start:
            found = date(start.year, number, int(day))
            days.append(found if found >= start else found.replace(year=start.year + 1))
    return max(days).isoformat() if days else None


def _kind(text: str) -> str:
    contract = re.search(r"Contrato\s*:\s*([^.]+)", text)
    return "indefinido" if contract and "indefinido" in contract.group(1).lower() else "temporal"


def _place(text: str) -> str | None:
    match = WORKPLACE.search(text) or WORKPLACE_INTRO.search(text)
    return re.sub(r"\s+de\s+ENUSA", "", _clean(match.group(1)), flags=re.I) if match else None


def parse_listing(html: str) -> list[dict]:
    """Un diccionario por proceso: datos de la fila y descripción completa."""
    soup = BeautifulSoup(html, "html.parser")
    counter = COUNT.search(_clean(soup.get_text(" ")))
    if counter is None:
        raise SourceLayoutError("Enusa: no aparece «Núm. de ofertas» en la bolsa de trabajo")
    links = soup.select("tr.fuentecampo a[onclick^=visible_procesos]")
    if int(counter.group(1)) and not links:
        raise SourceLayoutError("Enusa: la bolsa declara ofertas pero no se lee ninguna fila")
    processes = []
    for link in links:
        match = re.search(r"visible_procesos\((\d+)\)", link["onclick"])
        cells = [_clean(td.get_text(" ")) for td in link.find_parent("tr").find_all("td")]
        block = soup.find(id=f"CAPA{match.group(1)}") if match else None
        if match is None or len(cells) < 3 or block is None:
            raise SourceLayoutError("Enusa: fila de proceso sin su descripción")
        body = block.select_one("td.fuentevalor")
        text = _clean(body.get_text(" ")) if body else ""
        published = re.fullmatch(r"(\d{4})-(\d{2})-(\d{2})", cells[2])
        processes.append({
            "id": match.group(1),
            "title": re.sub(r"\s+MV-[\d-]+$", "", cells[0]),
            "code": cells[1],
            "published_on": cells[2] if published else None,
            "text": text,
            "html": body.decode_contents() if body else "",
        })
    return processes


def _published(text: str, fallback: str | None) -> str | None:
    match = PUBLISHED.search(text)
    return f"{match.group(3)}-{match.group(2)}-{match.group(1)}" if match else fallback


class EnusaSource(Source):
    id = "enusa"
    name = "Enusa"
    homepage = PAGE
    ref_code = re.compile(r".+")  # el ref es el código que publica el portal
    apply_label = "Ver cómo inscribirse"

    def __init__(self) -> None:
        self._processes: list[dict] = []

    def _read(self, http: Client) -> list[dict]:
        http.get(LANDING)
        return parse_listing(http.post(LOGIN, GUEST))

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._processes = self._read(http)
        offers = []
        for process in self._processes:
            deadline = _deadline(process["text"], process["published_on"])
            process["deadline"] = deadline
            if deadline is None:
                continue
            offers.append(ListedOffer(
                ref=process["code"], title=process["title"], company=COMPANY, url=PAGE, apply_url=PAGE,
                kind=_kind(process["text"]),
                positions=1 if ONE_POSITION.search(process["text"]) else None,
                deadline=deadline,
            ))
        return offers

    def list_announcements(self, http: Client) -> list[Announcement]:
        items = []
        for process in self._processes:
            if process["deadline"] is not None:
                continue
            day = _published(process["text"], process["published_on"])
            if not day:
                continue
            what = ("resultado de la revisión de requisitos mínimos"
                    if RESULT in process["text"].lower() else "comunicación del proceso")
            items.append(Announcement(
                date=day, process=f"{process['title']} ({process['code']})",
                title=what.capitalize(), url=PAGE, access="libre", contract=_kind(process["text"]),
                system=selection_system(process["text"]), process_url=PAGE,
            ))
        return items

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        process = next((p for p in self._processes if p["code"] == offer.ref), None)
        if process is None:
            return OfferDetail()
        body = sanitize(process["html"])
        sections = [{"title": "Descripción de la oferta", "level": 2, "html": body}] if body else []
        return OfferDetail(sections=sections, location=_place(process["text"]))

    def enrich(self, http: Client) -> dict[str, dict]:
        return {
            p["code"]: {"published_on": p["published_on"]}
            for p in self._processes if p["deadline"] is not None
        }
