"""Universitat Pompeu Fabra: convocatorias laborales del PTGAS (nuevo ingreso y «altres ofertes»).

`Convocatòries per al Personal Tècnic, de Gestió i d'Administració i Serveis` (Liferay, en catalán) es
un único listado de todas las convocatorias del PTGAS, 100 por página, ordenado por el plazo, del más
lejano al más cercano. Cada fila (`div.oferta a.viewLink`, enlazada a la ficha) trae el código
(«LNI02/2026», «UPF26-TSTICMT2-SI»; «Fundació UPF» cuando contrata la Fundación), el título literal, el
tipo («PTGAS laboral - concurs de nou ingrés»), la adscripción, las plazas, el «Termini de sol·licituds»
(sin hora) y un estado que dice «Obert» también con el plazo vencido: mandan las fechas.

Entran solo los tipos laborales abiertos a cualquiera (decidido con el usuario el 2026-11-16, opción C):
`LABORAL`. Fuera, por regla: traslado y promoción interna, provisión, bolsas y todo lo funcionarial
(`EXCLUDED`). Un tipo desconocido en una fila en plazo detiene la fuente, para decidir qué hacer con él.
Basta la primera página: si su última fila sigue en plazo, se detiene (podría haber más en la segunda).

La ficha (`div.fitxa-seleccio`) repite el código, el tipo y la adscripción y añade el régimen, el grupo y
la jornada; después, las fases fechadas («Convocatòria LNI02/2026 · 03 nov. 2026», con el enlace a la
plataforma de solicitudes o a la oferta en PDF). La fecha de la primera fase es la de publicación. Se
copian los datos y las fases tal cual, con `lang="ca"`. Identificador: el tramo de la ruta de la ficha
(cambia si editan el título). Municipio: Barcelona (todos los campus y la Fundación están allí).
Sondeo y HTML de muestra del 2026-11-15 (Codex, encargo 40, inventario9).
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

SITE = "https://www.upf.edu"
PAGE = SITE + "/web/personal/ofertes-pas"
COMPANY = "Universitat Pompeu Fabra"
FOUNDATION = "Fundació UPF"  # en la columna del código cuando contrata la Fundación
FOUNDATION_NAME = "Fundació Universitat Pompeu Fabra"
LABORAL = ("PTGAS laboral - concurs de nou ingrés", "PTGAS laboral - altres ofertes")
EXCLUDED = (
    "PTGAS laboral - concurs de trasllat i promoció interna", "PTGAS laboral - temporals personal laboral interna",
    "PTGAS funcionari - accés", "PTGAS funcionari - convocatòria de provisió", "PTGAS funcionari - altres ofertes",
    "PTGAS funcionari - borsa de treball", "PTGAS funcionari - temporals personal funcionari interna",
    "PTGAS - altres ofertes",  # sin decir si es laboral o funcionarial: fuera hasta verla
)
SLUG = re.compile(r"/content/([^/]+)/\d+/maximized$")
DAY = re.compile(r"\d{2}/\d{2}/\d{4}")
PLACES = re.compile(r"^Places:\s*(\d+)$")
# «03 nov. 2026»: abreviaturas catalanas de Liferay.
MONTHS = {"gen": 1, "febr": 2, "feb": 2, "març": 3, "mar": 3, "abr": 4, "maig": 5, "juny": 6, "jul": 7,
          "ag": 8, "set": 9, "oct": 10, "nov": 11, "des": 12}


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _lines(node) -> list[str]:
    return [line for line in (_clean(s) for s in node.get_text("\n").split("\n")) if line]


def parse_list(html: str) -> list[dict]:
    links = BeautifulSoup(html, "html.parser").select("div.oferta a.viewLink[href]")
    if not links:
        raise SourceLayoutError("Universitat Pompeu Fabra: el listado de convocatorias del PTGAS está vacío")
    found = []
    for link in links:
        cols = link.select(".row > div")
        slug = SLUG.search(link["href"])
        strong = cols[1].select_one("strong") if len(cols) >= 4 else None
        deadline = DAY.fullmatch(_clean(cols[3].select_one("strong").get_text(" "))) \
            if strong and cols[3].select_one("strong") else None
        if not (slug and strong and deadline):
            raise SourceLayoutError(f"Universitat Pompeu Fabra: fila sin ficha, título o plazo "
                                    f"({_clean(link.get_text(' '))[:120]!r})")
        info = _lines(cols[1])  # título, tipo y, si la hay, «Adscripció: …»
        places = PLACES.match(_clean(cols[2].get_text(" ")))
        found.append({
            "ref": slug.group(1), "url": urljoin(PAGE, link["href"]), "code": _clean(cols[0].get_text(" ")),
            "title": _clean(strong.get_text(" ")), "type": info[1] if len(info) > 1 else "",
            "positions": int(places.group(1)) if places else None, "deadline": numeric_date(deadline.group(0)),
        })
    return found


def _phase_day(node) -> str | None:
    """«03» + «nov. 2026» → «2026-11-03»; None si no hay fecha o el mes no es una abreviatura conocida."""
    day, rest = node.select_one(".cnt"), node.select_one(".rgt")
    if day is None or rest is None:
        return None
    parts = _clean(rest.get_text(" ")).split()
    month = MONTHS.get(parts[0].rstrip(".").lower()) if len(parts) == 2 else None
    try:
        return date(int(parts[1]), month, int(_clean(day.get_text()))).isoformat() if month else None
    except ValueError:
        return None


def parse_ficha(html: str) -> dict:
    node = BeautifulSoup(html, "html.parser").select_one("div.fitxa-seleccio")
    data = node.select_one(".serveisdades .col-sm-10") if node else None
    if data is None:
        raise SourceLayoutError("Universitat Pompeu Fabra: ficha sin «fitxa-seleccio»")
    for script in node.select("script"):
        script.decompose()
    for link in node.select("a[href]"):  # la oferta de la Fundación va con ruta relativa
        link["href"] = urljoin(SITE, link["href"])
    phases = []
    for row in node.select(".fases-seleccio > .row"):
        cols = row.find_all("div", recursive=False)
        if len(cols) < 3:
            continue
        info = cols[2].select_one(".info-proces")
        phases.append({"label": _clean(cols[0].get_text(" ")), "day": _phase_day(cols[1]),
                       "day_text": _clean(cols[1].get_text(" ")),
                       "html": sanitize(info.decode_contents()) if info else ""})
    return {"data": sanitize(data.decode_contents()), "phases": phases,
            "published_on": phases[0]["day"] if phases else None}


class UpfSource(Source):
    id = "upf"
    name = "Universitat Pompeu Fabra"
    homepage = PAGE
    scope = "Cataluña"
    text_lang = "ca"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._fichas: dict[str, dict] = {}

    def _open_rows(self, http: Client) -> list[dict]:
        now = self._now or datetime.now(timezone.utc)
        rows = parse_list(http.get(PAGE))
        if not deadline_passed(rows[-1]["deadline"], None, now):
            raise SourceLayoutError("Universitat Pompeu Fabra: la última fila de la primera página sigue en plazo")
        found = []
        for row in rows:
            if deadline_passed(row["deadline"], None, now) or row["type"] in EXCLUDED:
                continue
            if row["type"] not in LABORAL:
                raise SourceLayoutError(f"Universitat Pompeu Fabra: tipo de convocatoria desconocido en plazo: "
                                        f"{row['type']!r} ({row['code']})")
            found.append(row)
        return found

    def list_offers(self, http: Client) -> list[ListedOffer]:
        offers = []
        for row in self._open_rows(http):
            ficha = self._fichas[row["ref"]] = parse_ficha(http.get(row["url"]))
            foundation = row["code"] == FOUNDATION
            offers.append(ListedOffer(
                ref=row["ref"], title=row["title"], company=FOUNDATION_NAME if foundation else COMPANY,
                url=row["url"], apply_url=row["url"], kind=None, positions=row["positions"],
                deadline=row["deadline"], published_on=ficha["published_on"],
                code=None if foundation or not row["code"] else row["code"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        ficha = self._fichas.get(offer.ref) or parse_ficha(http.get(offer.url))
        sections = [{"title": "La convocatoria", "level": 2, "html": ficha["data"], "lang": self.text_lang}]
        if ficha["phases"]:
            items = "".join(
                f"<li><p><strong>{escape(p['label'])}</strong>{': ' + escape(p['day_text']) if p['day_text'] else ''}"
                f"</p>{p['html']}</li>" for p in ficha["phases"])
            sections.append({"title": "Fases", "level": 2, "html": sanitize(f"<ul>{items}</ul>"),
                             "lang": self.text_lang})
        return OfferDetail(location="Barcelona", sections=sections)
