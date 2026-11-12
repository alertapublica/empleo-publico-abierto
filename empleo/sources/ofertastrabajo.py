"""Portal «ofertastrabajo» de dos fundaciones sanitarias gallegas: IDIS (Santiago) y Galicia Sur (Vigo).

Las dos usan la misma aplicación: `/ofertastrabajo/publicadas` lista todas las convocatorias,
abiertas y cerradas, y cada una enlaza a `/ofertastrabajo/inscripciones/N`, que es a la vez la ficha
y el formulario de inscripción (solo se enlaza, nunca se rellena). Cambia la plantilla del listado:

- IDIS: un `div.oferta_section` por convocatoria con el puesto (`h3`, a veces con «2 PLAZAS de»
  delante), la titulación (`h1`), el proyecto (`h5`) y «Número de referencia», «Fecha apertura» y
  «Fecha cierre» en un párrafo. Es una sola página con todo el histórico desde 2018 (más de 900
  convocatorias, unos 2,4 MB), de la más reciente a la más antigua.
- Galicia Sur: un `div.list-item…` por convocatoria con «Plazo: DD/MM/AAAA - DD/MM/AAAA» (solo las
  que tienen plazo; las demás dicen «Convocatoria resuelta»), el puesto con «(REF: 25/26)» al final y
  un párrafo con el proyecto y la titulación.

El puesto lleva delante la categoría del convenio («1.2 3 Titulado/a Graduado/a I», «1.2.4 …») y se
repite en muchas convocatorias. El título publicado es el puesto sin esa categoría ni «N PLAZAS de»
(las plazas van aparte) y, si el portal rotula el proyecto o la línea de investigación («Proyecto de
investigación:», «PROYECTO:», «Línea de Investigación:»), « · » y ese texto, sin el rótulo ni la
titulación que le sigue. El literal del puesto queda en `source_title`.

Es oferta la que tiene la fecha de cierre sin vencer (sin hora). Sin fechas solo se aceptan los
estados conocidos («Pendiente de publicación en DOGA» en IDIS, «Convocatoria resuelta» en Galicia
Sur); cualquier otro detiene la fuente, para no dar por cerradas ofertas vigentes. Clave: el número de la ficha; el
código público es la referencia. La ficha tiene cuadros numerados («Oferta de empleo»,
«Condiciones/Duración», «Fecha límite») y recuadros con título («Requisitos imprescindibles»,
«Méritos», «Más información»; el que no lo tiene, con la financiación y la ubicación del puesto, va
como «Otros datos»). De los documentos solo se enlazan las bases: «Tribunal» y «Baremo
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
PLAZAS = re.compile(r"(\d+)\s+PLAZAS\s+(?:de\s+)?", re.I)
# Categoría del convenio delante del puesto: «1.2 3», «1.2.4», «1.2.2.», «1.1. 4», «1 1.3», «1..2 1», «.2.3».
LEVEL = re.compile(r"(?:\.?\d+(?:\.+\d+)+\.?(?:\s+\d+(?:\.\d+)*\.?)?|\d+\s+\d+(?:\.\d+)+\.?)\s+(?=\D)")
PROJECT = re.compile(r"(?:Proyecto(?:\s+de\s+investigaci[oó]n)?|L[ií]nea\s+de\s+investigaci[oó]n)\s*:?\s*(.+)", re.I)
NO_DATES_IDIS = "Pendiente de publicación"
NO_DATES_GALICIASUR = "Convocatoria resuelta"
REF = re.compile(r"\s*\(REF:\s*([^)]+)\)\s*$")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _iso(text: str) -> str | None:
    found = DMY.search(text)
    if found is None:
        return None
    day, month, year = found.groups()
    return date(int(year), int(month), int(day)).isoformat()


def job_title(position: str, project: str | None) -> dict:
    """Título publicado: el puesto sin categoría ni plazas y, si está rotulado, el proyecto."""
    title = LEVEL.sub("", PLAZAS.sub("", position, count=1), count=1).strip() or position
    named = PROJECT.match(project or "")
    if named:
        name = re.split(r"\s*TITULACI[OÓ]N\s+REQUERIDA", named.group(1), maxsplit=1, flags=re.I)[0].strip()
        if name:
            title = f"{title} · {name}"
    return {"title": title, "source_title": position if title != position else None}


def parse_idis(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    found = []
    for block in soup.select("div.oferta_section"):
        heading, facts = block.select_one("h3"), block.select_one("p.text_theme")
        link = block.find("a", href=FICHA)
        if heading is None or facts is None or link is None:
            raise SourceLayoutError("IDIS: convocatoria sin puesto, sin fechas o sin ficha")
        text = _clean(facts.get_text(" "))
        ref = re.search(r"Número de referencia:\s*(.+?)\s*(?:Fecha apertura|$)", text)
        opens, closes = re.search(r"Fecha apertura:\s*(\S+)", text), re.search(r"Fecha cierre:\s*(\S+)", text)
        if closes is None or _iso(closes.group(1)) is None:
            if NO_DATES_IDIS in text:
                continue
            raise SourceLayoutError(f"IDIS: convocatoria sin fecha de cierre reconocible: «{text}»")
        position = _clean(heading.get_text(" "))
        project = block.select_one("h5")
        plazas = PLAZAS.match(position)
        found.append({
            "ref": FICHA.search(link["href"]).group(1), "url": link["href"],
            **job_title(position, _clean(project.get_text(" ")) if project else None),
            "code": ref.group(1) if ref else None, "positions": int(plazas.group(1)) if plazas else None,
            "opens_on": _iso(opens.group(1)) if opens else None,
            "deadline": _iso(closes.group(1)),
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
        state = _clean(period.get_text(" ")) if period else ""
        dates = DMY.findall(state)
        if len(dates) != 2:
            if state == NO_DATES_GALICIASUR:
                continue
            raise SourceLayoutError(f"Galicia Sur: convocatoria sin plazo reconocible: «{state}»")
        opens, closes = ("-".join(reversed(d)) for d in dates)
        literal = _clean(heading.get_text(" "))
        ref = REF.search(literal)
        position = REF.sub("", literal) if ref else literal
        summary = item.find("p")
        entry = job_title(position, _clean(summary.get_text(" ")) if summary else None)
        found.append({
            "ref": FICHA.search(link["href"]).group(1), "url": link["href"], "title": entry["title"],
            "source_title": literal if entry["title"] != literal else None,
            "code": ref.group(1).strip() if ref else None, "positions": None,
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
        title = _clean(heading.extract().get_text(" ")) if heading else "Otros datos"
        for note in callout.select("small"):
            note.wrap(soup.new_tag("p"))
        html_box = _box(callout)
        if html_box:
            sections.append({"title": title, "level": 2, "html": html_box})
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
                ref=entry["ref"], title=entry["title"], code=entry["code"], source_title=entry["source_title"],
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

    def parse(self, html: str) -> list[dict]:
        return parse_galiciasur(html)
