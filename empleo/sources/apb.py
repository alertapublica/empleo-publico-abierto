"""Autoridad Portuaria de Barcelona (Port de Barcelona).

Portal de selección propio (`seleccio.portdebarcelona.cat`, Liferay). El listado («Ofertas», 7 el
2026-11-11) da título, enlace a la ficha y «Última modificación»; nada del plazo. Algunas fichas se
enlazan en catalán (`/ca/web/`): se leen en castellano (`/es/web/`).

La ficha (`.entry-content`) tiene apartados con `h3` («Misión del puesto de trabajo», «Qué
ofrecemos», «Requisitos mínimos», «Fases del proceso de selección») y, cuando el proceso avanza,
«Seguimiento del proceso de selección»: una lista de párrafos del más reciente al más antiguo («Os
hacemos llegar la lista definitiva de personas admitidas y excluidas…»), con el documento enlazado y
sin fecha de publicación. Los documentos van aparte («Bases de la convocatoria», «Calendario
orientativo…»).

El plazo está en las bases en PDF («finalizará el 23 de noviembre de 2026, a las 13:00 horas») y, si
se amplía, en un párrafo de la ficha («fijando como fecha de finalización el día 20 de noviembre de
2026 a las 12:00 horas»); vale la fecha mayor. Es oferta la ficha sin seguimiento con el plazo sin
vencer; las que tienen seguimiento son procesos, cuyos comunicados son esos párrafos, literales y sin
fecha. «Resultado final» da el proceso por terminado.
Peticiones: el listado, cada ficha (hoy 7) y las bases de las fichas sin seguimiento (hoy 4).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import MONTHS, clock, hour_on, latest, spanish_date
from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..pdftext import deadlines_at, read_pdf
from ..sanitize import sanitize
from .base import Source

SITE = "https://seleccio.portdebarcelona.cat"
PAGE = SITE + "/es/web/seleccio/llistat-ofertes"
COMPANY = "Autoridad Portuaria de Barcelona"
FOLLOW_UP = re.compile(r"Seguimiento del proceso de selecci[óo]n|Seguiment del proc[ée]s de selecci[óo]", re.I)
EXTENDED = re.compile(r"fecha de finalizaci[óo]n el d[ií]a (\d{1,2}) de (" + "|".join(MONTHS)
                      + r") de (\d{4})(?:,)? a las (\d{1,2}[:.]\d{2})", re.I)
FINAL = re.compile(r"resultado final|resultat final", re.I)
SECTIONS = ("Misión del puesto de trabajo", "Qué ofrecemos", "Requisitos mínimos", "Fases del proceso de selección")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_page(html: str) -> list[dict]:
    found = []
    for item in BeautifulSoup(html, "html.parser").select("li"):
        link, title = item.find("a", href=True), item.find("h5")
        if link is None or title is None:
            continue
        url = urljoin(SITE, link["href"]).replace("/ca/web/", "/es/web/")
        found.append({"title": _clean(title.get_text(" ")), "url": url, "ref": url.rstrip("/").rsplit("/", 1)[-1]})
    if not found:
        raise SourceLayoutError("Autoridad Portuaria de Barcelona: el listado no tiene ofertas")
    return found


def parse_detail(html: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    contents = soup.select(".entry-content")
    if not contents:
        raise SourceLayoutError("Autoridad Portuaria de Barcelona: ficha sin contenido")
    notices, sections = [], []
    for content in contents:
        for heading in content.find_all("h3"):
            name = _clean(heading.get_text(" "))
            if FOLLOW_UP.fullmatch(name):
                listing = heading.find_next_sibling("ul")
                for item in listing.find_all("li") if listing else []:
                    link = item.find("a", href=True)
                    notices.append({"title": _clean(item.get_text(" ")), "url": urljoin(SITE, link["href"]) if link else None})
            elif name in SECTIONS:
                parts = []
                for sibling in heading.find_next_siblings():
                    if sibling.name == "h3":
                        break
                    parts.append(str(sibling))
                sections.append({"title": name, "level": 2, "html": sanitize("".join(parts))})
    text = _clean(" ".join(c.get_text(" ") for c in contents))
    extended = [(spanish_date(d, m, y), clock(h)) for d, m, y, h in EXTENDED.findall(_clean(soup.get_text(" ")))]
    documents = [(_clean(a.get_text(" ")), urljoin(SITE, a["href"])) for a in soup.select("a[href*='/documents/']")]
    return {
        "notices": notices, "sections": sections, "extended": [e for e in extended if e[0]],
        "bases": next((url for label, url in documents if label.lower().startswith(("bases de la convocat",))), None),
        "kind": "indefinido" if re.search(r"contrataci[óo]n indefinida|contrato indefinido", text, re.I) else None,
    }


class ApbSource(Source):
    id = "apb"
    name = "Autoridad Portuaria de Barcelona"
    homepage = PAGE
    apply_label = "Ver la convocatoria e inscribirse en el portal de selección"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._read_done = False
        self._offers: list[ListedOffer] = []
        self._details: dict[str, dict] = {}
        self._processes: list[tuple[dict, dict]] = []

    def _read(self, http: Client) -> None:
        if self._read_done:
            return
        now = self._now or datetime.now(timezone.utc)
        for row in parse_page(http.get(PAGE)):
            detail = parse_detail(http.get(row["url"]))
            if detail["notices"]:
                self._processes.append((row, detail))
                continue
            found = list(detail["extended"])
            if detail["bases"]:
                text = read_pdf(http, detail["bases"], f"APB, bases de {row['title']}")
                found += [(day, hour or hour_on(text, day)) for day, hour in deadlines_at(text)]
            day, hour = latest(found)
            if day is None or deadline_passed(day.isoformat(), hour, now):
                continue
            self._details[row["ref"]] = detail
            self._offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"], apply_url=row["url"],
                kind=detail["kind"], deadline=day.isoformat(), deadline_time=hour,
            ))
        self._read_done = True

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._read(http)
        return self._offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        detail = self._details.get(offer.ref)
        return OfferDetail(location="Barcelona", sections=detail["sections"] if detail else [])

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Los párrafos de seguimiento de cada proceso, sin fecha, del más reciente al más antiguo."""
        self._read(http)
        items = []
        for row, detail in self._processes:
            state = "finalizado" if any(FINAL.search(n["title"]) for n in detail["notices"]) else "curso"
            items += [Announcement(date="", process=row["title"], title=n["title"], url=n["url"] or row["url"],
                                   contract=detail["kind"], state=state, process_url=row["url"])
                      for n in detail["notices"]]
        return items
