"""Universidade de Vigo: concursos públicos de méritos para contratar personal de investigación.

Taboleiro de convocatorias de la Secretaría (`secretaria.uvigo.gal`, sin robots.txt), categoría
«Investigar»: 20 tarjetas por página, primero las abiertas (por fin de plazo) y luego las cerradas.
Cada tarjeta (`.uvigo-card-box`) enlaza la ficha (`/show/<número>`) y trae el título, el tipo, el
organismo convocante y «Prazo: 05/11/2026 - 18/11/2026». Se lee solo la primera página: si su última
tarjeta sigue en plazo, puede haber más y la fuente se detiene.

Solo entran los «CONCURSO PÚBLICO DE MÉRITOS NN/26 PARA A CONTRATACIÓN DE PERSOAL DE INVESTIGACIÓN»
de la propia universidad (14 en 2026, uno cada tres semanas, abiertos dos). El resto de la categoría
son ayudas (FPI, Juan de la Cierva, movilidad), preselecciones internas (PTA, Ramón y Cajal) o
premios, no puestos a los que presentarse (decidido el 2026-11-15). El PTXAS de la UVigo no tiene
convocatorias abiertas que leer: la categoría «Emprego» es casi todo profesorado y funcionarios, y las
«ofertas de contratación» son llamamientos de las listas de espera.

Cada concurso agrupa unas 15 plazas («REFERENCIA DA OFERTA 1326-184549»), que solo vienen en los anexos
III y IV del PDF de bases (sin leer): se publica como una oferta, con su título literal, como CiQUS.
La ficha es una tabla (Código «14/26_CONC», «Data inicio/fin solicitudes», enlace a la sede para
solicitar, Descripción, Requisitos, Documentación, Observacións) y los documentos por fases. La hora
de cierre va en el texto («ata as 23:59 horas do 18 de novembro de 2026»), en «Documentacion» o en
«Observacións»: vale si su día es el de «Data fin solicitudes»; otro día detiene la fuente. Todo en
gallego. Sin municipio: hay plazas en Vigo, Ourense y Pontevedra.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://secretaria.uvigo.gal"
INDEX = SITE + "/uv/web/convocatoria/public/categoria/investigar"
COMPANY = "Universidade de Vigo"
SHOW = re.compile(r"/uv/web/convocatoria/public/show/(\d+)$")
CONCURSO = re.compile(r"CONCURSO PÚBLICO DE MÉRITOS \d+/\d+ PARA A CONTRATACIÓN DE PERSOAL DE INVESTIGACIÓN", re.I)
PERIOD = re.compile(r"Prazo:\s*(\d{2}/\d{2}/\d{4})\s*-\s*(\d{2}/\d{2}/\d{4})")
MESES = "xaneiro febreiro marzo abril maio xuño xullo agosto setembro outubro novembro decembro".split()
CLOSING = re.compile(r"ata as (\d{1,2})[:.](\d{2}) horas do (\d{1,2}) de ([a-zñ]+) de (\d{4})", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_list(html: str) -> list[dict]:
    cards = BeautifulSoup(html, "html.parser").select(".uvigo-card-box")
    if not cards:
        raise SourceLayoutError("Universidade de Vigo: el taboleiro «Investigar» está vacío")
    found = []
    for card in cards:
        link, title = card.select_one("a[href]"), card.select_one(".uvigo-card-link")
        path = SHOW.search(link["href"]) if link else None
        summary = _clean(card.select_one(".uvigo-card-summary").get_text(" ")) if card.select_one(".uvigo-card-summary") else ""
        if not (path and title and _clean(title.get_text(" "))):
            raise SourceLayoutError(f"Universidade de Vigo: tarjeta sin ficha o sin título ({_clean(card.get_text(' '))[:120]!r})")
        period = PERIOD.search(summary)
        found.append({
            "ref": path.group(1), "url": SITE + path.group(0), "title": _clean(title.get_text(" ")),
            "own": "Organismo convocante: Universidade de Vigo" in summary,
            "opens_on": numeric_date(period.group(1)) if period else None,
            "deadline": numeric_date(period.group(2)) if period else None,
        })
    return found


def _closing_hour(text: str, deadline: str) -> str | None:
    """Hora de «ata as 23:59 horas do 18 de novembro de 2026», si es la del último día."""
    hours = set()
    for hour, minute, day, month, year in CLOSING.findall(_clean(text)):
        if month.lower() not in MESES:
            raise SourceLayoutError(f"Universidade de Vigo: mes desconocido en el cierre ({month!r})")
        if date(int(year), MESES.index(month.lower()) + 1, int(day)).isoformat() != deadline:
            raise SourceLayoutError(f"Universidade de Vigo: el texto cierra el {day} de {month} de {year} y la "
                                    f"ficha, el {deadline}")
        hours.add(f"{int(hour):02d}:{minute}")
    if len(hours) > 1:
        raise SourceLayoutError(f"Universidade de Vigo: varias horas de cierre ({sorted(hours)})")
    return hours.pop() if hours else None


def parse_ficha(html: str, base: str) -> dict:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one('#uvigomp-contido table[title="Detalle convocatoria"]')
    if table is None:
        raise SourceLayoutError("Universidade de Vigo: ficha sin «Detalle convocatoria»")
    fields = {}
    for row in table.select("tr"):
        label, value = row.select_one("td.uvigo-table2c-col1"), row.select_one("td.uvigo-table2c-col2")
        if label and value:
            fields[_clean(label.get_text(" ")).rstrip(":")] = value
    try:
        opens_on = numeric_date(_clean(fields["Data inicio solicitudes"].get_text()))
        deadline = numeric_date(_clean(fields["Data fin solicitudes"].get_text()))
    except (KeyError, ValueError) as error:
        raise SourceLayoutError(f"Universidade de Vigo: ficha sin «Data inicio/fin solicitudes» ({error})") from error
    form = fields.get("Enderezo formulario para solicitude online")
    form = form.select_one("a[href]") if form else None
    documents = [(_clean(a.get_text(" ")), urljoin(base, a["href"]))
                 for a in soup.select('#uvigomp-contido table[title="Fase convocatoria"] a.filename[href]')]
    return {
        "code": _clean(fields["Código"].get_text()) if "Código" in fields else None,
        "opens_on": opens_on, "deadline": deadline,
        "deadline_time": _closing_hour(table.get_text(" "), deadline),
        "apply_url": form["href"] if form else None,
        "sections": [(title, sanitize(fields[label].decode_contents()))
                     for title, label in (("Descripción", "Descripción"), ("Requisitos", "Requisitos"),
                                          ("Documentación", "Documentacion"), ("Observaciones", "Observacións"))
                     if label in fields and _clean(fields[label].get_text(" "))],
        "documents": documents,
    }


class UvigoSource(Source):
    id = "uvigo"
    name = "Universidade de Vigo"
    homepage = INDEX
    scope = "Galicia"
    text_lang = "gl"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        rows = parse_list(http.get(INDEX))
        if rows[-1]["deadline"] and not deadline_passed(rows[-1]["deadline"], None, now):
            raise SourceLayoutError("Universidade de Vigo: la última tarjeta de la primera página sigue en plazo")
        offers = []
        for row in rows:
            if not (row["own"] and CONCURSO.fullmatch(row["title"]) and row["deadline"]):
                continue
            if deadline_passed(row["deadline"], None, now):
                continue
            ficha = self._fichas[row["ref"]] = parse_ficha(http.get(row["url"]), row["url"])
            if (ficha["opens_on"], ficha["deadline"]) != (row["opens_on"], row["deadline"]):
                raise SourceLayoutError(f"Universidade de Vigo: el plazo de la tarjeta {row['ref']} no es el de "
                                        f"su ficha ({row['opens_on']}–{row['deadline']} / "
                                        f"{ficha['opens_on']}–{ficha['deadline']})")
            if deadline_passed(ficha["deadline"], ficha["deadline_time"], now):
                continue
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=COMPANY, url=row["url"],
                apply_url=ficha["apply_url"] or row["url"], kind=None, opens_on=ficha["opens_on"],
                deadline=ficha["deadline"], deadline_time=ficha["deadline_time"], code=ficha["code"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url), offer.url)
        sections = [{"title": title, "level": 2, "html": html, "lang": self.text_lang} for title, html in ficha["sections"]]
        if ficha["documents"]:
            items = "".join(f'<li><a href="{escape(url, quote=True)}">{escape(label)}</a></li>'
                            for label, url in ficha["documents"])
            sections.append({"title": "Documentos", "level": 2, "html": sanitize(f"<ul>{items}</ul>"),
                             "lang": self.text_lang})
        return OfferDetail(sections=sections)
