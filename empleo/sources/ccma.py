"""3Cat (Corporació Catalana de Mitjans Audiovisuals): «Espai de selecció».

Aplicación JSF. La portada (`/seleccio/index.jsf`) lista los «Processos de selecció oberts»: una
tarjeta (`div.cardConvo`) por proceso con el «Període d'inscripció: DD/MM/AAAA al DD/MM/AAAA», el
título enlazado a `convocatoria.jsf?idConv=N`, el «Àmbit» y la «Empresa». Los procesos en curso,
resueltos e históricos solo se ven reenviando el formulario JSF: no se leen. La ficha tiene la
convocatoria entera en `div.descripcioConvocatoria`, en catalán; el último día suele llevar hora
(«finalitza el dia 15 de novembre de 2026 a les 23:59h»).

Es oferta el proceso con el fin del periodo sin vencer y con un ámbito abierto al público («Concurs
públic», también «Concurs públic / promoció interna»); los de solo promoción interna no se leen y un
ámbito ausente o desconocido detiene la fuente. La hora solo vale si la ficha da la misma fecha
completa (también «d'octubre», con apóstrofo). Sin
tarjetas, la lista tiene que estar vacía de verdad: si no, la fuente se detiene. Las bases se
descargan con el formulario JSF: solo se enlaza la ficha.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from ..dates import clock
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://seleccio.3cat.cat"
PAGE = SITE + "/seleccio/index.jsf"
PUBLIC = re.compile(r"públic|extern", re.I)
INTERNAL = re.compile(r"(?:promoció\s+)?intern[ao]?", re.I)
MONTHS = "gener febrer març abril maig juny juliol agost setembre octubre novembre desembre".split()
DMY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
LAST_DAY = re.compile(
    r"finalitza\s+el\s+dia\s+(\d{1,2})\s+d(?:e\s+|['’]\s*)(\w+)\s+de\s+(\d{4})\s+a\s+les\s+(\d{1,2}[:.]\d{2})", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _field(card, label: str) -> str | None:
    """Valor de «Àmbit: …» o «Empresa: …» en la tarjeta."""
    for strong in card.find_all("strong"):
        if _clean(strong.get_text()).rstrip(":").strip() == label:
            return _clean(strong.parent.get_text(" ")).split(":", 1)[1].strip() or None
    return None


def parse_list(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    listing = soup.find(id="formLlistatVigents:llistaConvocatories")
    if soup.select_one("[data-testid=seccio-processos]") is None or listing is None:
        raise SourceLayoutError("3Cat: no se encuentra la lista de processos de selecció oberts")
    cards = listing.select("div.cardConvo")
    if not cards and listing.find(["h3", "a"]):
        raise SourceLayoutError("3Cat: la lista tiene procesos que no se reconocen")
    found = []
    for card in cards:
        link = card.find("a", href=re.compile(r"convocatoria\.jsf\?idConv=\d+"))
        heading = card.find("h3")
        dates = DMY.findall(_clean(card.get_text(" ")))
        if link is None or heading is None or len(dates) < 2:
            raise SourceLayoutError("3Cat: proceso sin enlace, sin título o sin periodo de inscripció")
        opens, closes = ("-".join(reversed(d)) for d in dates[:2])
        found.append({
            "ref": re.search(r"idConv=(\d+)", link["href"]).group(1), "url": SITE + link["href"],
            "title": _clean(heading.get_text(" ")), "opens_on": opens, "deadline": closes,
            "scope": _field(card, "Àmbit"), "company": _field(card, "Empresa"),
        })
    return found


def parse_ficha(html: str, deadline: str) -> dict:
    content = BeautifulSoup(html, "html.parser").select_one("div.descripcioConvocatoria")
    if content is None:
        raise SourceLayoutError("3Cat: ficha sin convocatòria")
    hour = None
    last = LAST_DAY.search(_clean(content.get_text(" ")))
    month = MONTHS.index(last.group(2).lower()) + 1 if last and last.group(2).lower() in MONTHS else None
    if month and f"{last.group(3)}-{month:02d}-{int(last.group(1)):02d}" == deadline:
        hour = clock(last.group(4))
    # El editor envuelve la convocatoria en un `<p>`: fuera, para que queden sus bloques.
    for wrapper in content.find_all("p"):
        if wrapper.find(["p", "h2", "h3", "h4", "ul", "ol"]):
            wrapper.unwrap()
    sections, title, chunk = [], "Convocatoria", []

    def close() -> None:
        html = sanitize("".join(chunk))
        if html:
            sections.append({"title": title, "level": 2, "html": html})

    for node in content.children:
        if getattr(node, "name", None) == "h2":
            continue  # el título de la convocatoria, ya en la ficha
        if getattr(node, "name", None) in ("h3", "h4"):
            close()
            title, chunk = _clean(node.get_text(" ")), []
        else:
            chunk.append(str(node))
    close()
    return {"deadline_time": hour, "sections": sections}


class CcmaSource(Source):
    id = "ccma"
    name = "3Cat (Corporació Catalana de Mitjans Audiovisuals)"
    homepage = PAGE
    scope = "Cataluña"
    text_lang = "ca"
    apply_label = "Ver el proceso y cómo inscribirse"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._sections: dict[str, list[dict]] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_list(http.get(PAGE)):
            if not row["scope"]:
                raise SourceLayoutError(f"3Cat: «{row['title']}» sin «Àmbit»")
            if not PUBLIC.search(row["scope"]):
                if INTERNAL.fullmatch(row["scope"]):
                    continue
                raise SourceLayoutError(f"3Cat: ámbito desconocido «{row['scope']}» en «{row['title']}»")
            if deadline_passed(row["deadline"], None, now):
                continue
            ficha = parse_ficha(http.get(row["url"]), row["deadline"])
            if deadline_passed(row["deadline"], ficha["deadline_time"], now):
                continue
            self._sections[row["ref"]] = ficha["sections"]
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=row["company"] or "CCMA",
                url=row["url"], apply_url=row["url"], kind=None, opens_on=row["opens_on"],
                deadline=row["deadline"], deadline_time=ficha["deadline_time"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        sections = self._sections.get(offer.ref)
        if sections is None:
            sections = parse_ficha(http.get(offer.url), offer.deadline)["sections"]
        return OfferDetail(sections=sections)
