"""Portal «ofertastrabajo» de dos fundaciones sanitarias gallegas: IDIS (Santiago) y Galicia Sur (Vigo).

Las dos usan la misma aplicación: `/ofertastrabajo/publicadas` lista todas las convocatorias,
abiertas y cerradas, y cada una enlaza a `/ofertastrabajo/inscripciones/N`, que es a la vez la ficha
y el formulario de inscripción (solo se enlaza, nunca se rellena). Cambia la plantilla del listado:

- IDIS: un `div.oferta_section` por convocatoria con el puesto (`h3`, a veces con «2 PLAZAS de»
  delante), la titulación (`h1`), el proyecto (`h5`) y «Número de referencia», «Fecha apertura» y
  «Fecha cierre» en un párrafo. Es una sola página con todo el histórico desde 2018 (más de 900
  convocatorias, unos 2,4 MB), de la más reciente a la más antigua.
- Galicia Sur: un `div.list-item…` por convocatoria con «Plazo: DD/MM/AAAA - DD/MM/AAAA» (solo las
  que tienen plazo; las demás dicen «Convocatoria resuelta») y el título con «(REF: 25/26)» al final.

Es oferta la que tiene la fecha de cierre sin vencer (sin hora). Clave: el número de la ficha; el
código público es la referencia. La ficha tiene cuadros numerados («Oferta de empleo»,
«Condiciones/Duración», «Fecha límite») y recuadros con título («Requisitos imprescindibles»,
«Méritos», «Más información»). De los documentos solo se enlazan las bases: «Tribunal» y «Baremo
provisional» son listas de personas. Sin procesos.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape

from bs4 import BeautifulSoup, Tag

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

DMY = re.compile(r"(\d{2})/(\d{2})/(\d{4})")
FICHA = re.compile(r"/ofertastrabajo/inscripciones/(\d+)")
PLAZAS = re.compile(r"(\d+)\s+PLAZAS\s+de\s+", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _iso(text: str) -> str | None:
    found = DMY.search(text)
    if found is None:
        return None
    day, month, year = found.groups()
    return date(int(year), int(month), int(day)).isoformat()


def parse_idis(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for block in soup.select("div.oferta_section"):
        heading, facts = block.select_one("h3"), block.select_one("p.text_theme")
        link = block.find("a", href=FICHA)
        if heading is None or facts is None or link is None:
            raise SourceLayoutError("IDIS: convocatoria sin puesto, sin fechas o sin ficha")
        text = _clean(facts.get_text(" "))
        ref = re.search(r"Número de referencia:\s*(.+?)\s*Fecha apertura", text)
        opens, closes = re.search(r"Fecha apertura:\s*(\S+)", text), re.search(r"Fecha cierre:\s*(\S+)", text)
        title = _clean(heading.get_text(" "))
        plazas = PLAZAS.match(title)
        found.append({
            "ref": FICHA.search(link["href"]).group(1), "url": link["href"], "title": title,
            "code": ref.group(1) if ref else None, "positions": int(plazas.group(1)) if plazas else None,
            "opens_on": _iso(opens.group(1)) if opens else None,
            "deadline": _iso(closes.group(1)) if closes else None,
        })
    if not found:
        raise SourceLayoutError("IDIS: la página no tiene convocatorias")
    return found


def parse_galiciasur(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = soup.select("div.list-wrapper div[class^='list-item']")
    if not items:
        raise SourceLayoutError("Galicia Sur: la página no tiene convocatorias")
    found = []
    for item in items:
        heading, link = item.select_one("div.titulo"), item.find("a", href=FICHA)
        if heading is None or link is None:
            raise SourceLayoutError("Galicia Sur: convocatoria sin título o sin ficha")
        period = item.select_one("div[class^='plazo']")
        dates = DMY.findall(period.get_text()) if period else []
        if len(dates) != 2:
            continue  # «Convocatoria resuelta»: sin plazo
        opens, closes = ("-".join(reversed(d)) for d in dates)
        found.append({
            "ref": FICHA.search(link["href"]).group(1), "url": link["href"],
            "title": _clean(heading.get_text(" ")), "code": None, "positions": None,
            "opens_on": opens, "deadline": closes,
        })
    return found


def _box(content: Tag) -> str:
    """HTML de un cuadro: un párrafo por línea, tanto en los `pre` sin etiquetas como entre `<br>`."""
    for pre in content.find_all("pre"):
        if pre.find(True) is None:
            lines = [line.strip() for line in pre.get_text().splitlines() if line.strip()]
            pre.replace_with(BeautifulSoup("".join(f"<p>{escape(line)}</p>" for line in lines), "html.parser"))
    html = content.decode_contents()
    if content.find("br") and not content.find(["p", "div", "ul", "ol"]):
        html = "".join(f"<p>{_clean(part)}</p>" for part in re.split(r"<br\s*/?>", html) if part.strip())
    return sanitize(html)


def parse_ficha(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    boxes = soup.select("div.cuadro")
    if not boxes:
        raise SourceLayoutError("ofertastrabajo: ficha sin cuadros")
    sections = []
    for box in boxes:
        heading, content = box.find("h3"), box.select_one("div.detalle")
        if heading is None or content is None:
            continue
        title = _clean(heading.get_text(" "))
        if title == "Fecha límite":  # ya está en el listado
            continue
        sections.append({"title": title, "level": 2, "html": _box(content)})
    for callout in soup.select("div.bs-callout"):
        heading = callout.find("h3")
        if heading is None:
            continue
        heading.extract()
        for note in callout.select("small"):
            note.wrap(soup.new_tag("p"))
        html_box = _box(callout)
        if html_box:
            sections.append({"title": _clean(heading.get_text(" ")), "level": 2, "html": html_box})
    bases = [a for a in soup.select("a[href]") if _clean(a.get_text(" ")) == "Bases de la oferta"]
    if bases:
        link = f'<p><a href="{escape(bases[0]["href"], quote=True)}">Bases de la oferta</a></p>'
        sections.append({"title": "Documentación", "level": 2, "html": sanitize(link)})
    return sections


class OfertasTrabajoSource(Source):
    scope = "Galicia"
    apply_label = "Ver la convocatoria y cómo inscribirse"
    company: str
    page: str

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def parse(self, html: str) -> list[dict]:
        raise NotImplementedError

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for entry in self.parse(http.get(self.page)):
            if not entry["deadline"] or deadline_passed(entry["deadline"], None, now):
                continue
            offers.append(ListedOffer(
                ref=entry["ref"], **self.labels(entry["title"], entry["ref"], entry["code"]),
                company=self.company, url=entry["url"], apply_url=entry["url"], kind=None,
                positions=entry["positions"], opens_on=entry["opens_on"], deadline=entry["deadline"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(sections=parse_ficha(http.get(offer.url)))


class IdisSource(OfertasTrabajoSource):
    id = "idis"
    name = "IDIS (Instituto de Investigación Sanitaria de Santiago)"
    homepage = "https://empleo.idisantiago.es/ofertastrabajo/publicadas"
    page = homepage
    company = "Fundación Instituto de Investigación Sanitaria de Santiago de Compostela"

    def parse(self, html: str) -> list[dict]:
        return parse_idis(html)


class GaliciaSurSource(OfertasTrabajoSource):
    id = "galiciasur"
    name = "IIS Galicia Sur (Fundación Biomédica Galicia Sur)"
    homepage = "https://www.iisgaliciasur.es/es/fundacion-biomedica/recursos-humanos/empleo/"
    page = "https://empleo.fundacionbiomedica.es/ofertastrabajo/publicadas"
    company = "Fundación Pública Galega de Investigación Biomédica Galicia Sur"
    title_code = re.compile(r"(?P<title>.+?)\s*\(REF:\s*(?P<code>[^)]+)\)")

    def parse(self, html: str) -> list[dict]:
        return parse_galiciasur(html)
