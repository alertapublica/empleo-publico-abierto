"""Mercasturias (Mercados Centrales de Abastecimiento de Asturias).

`ofertas_empleo.htm` es una página estática con un solo panel, «OFERTAS DISPONIBLES»: una lista de
documentos en PDF, del más reciente al más antiguo, cada uno con su fecha debajo («4 de noviembre
2026»). No hay bloques por proceso: cada proceso empieza con sus bases, que la web titula con el
puesto («Cobertura de puesto de trabajo Operario/a de limpieza, jardinería y conservación»), y los
documentos posteriores (ampliaciones de plazo, relaciones de admitidos, puntuaciones) son suyos hasta
las bases siguientes. Sin ofertas, el panel queda vacío.

El plazo solo está en el PDF de las bases y en las ampliaciones («hasta las 23:59 horas del 11 de
octubre de 2026»); vale la fecha mayor. Es oferta un proceso cuyo último plazo no ha vencido y que no
tiene más documentos que las bases y sus ampliaciones; los demás son procesos, con sus documentos como
comunicados. La web no marca los procesos terminados: siguen «en curso».
Solo se piden los PDF de los procesos que pueden ser oferta (hoy, ninguno).
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone
from html import escape
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import MONTHS, latest, spanish_date
from ..http import Client
from ..model import Announcement, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed, selection_system
from ..pdftext import deadlines_at, read_pdf
from ..sanitize import sanitize
from .base import Source

PAGE = "https://www.mercasturias.com/ofertas_empleo.htm"
COMPANY = "Mercasturias"
BASES = re.compile(r"^Cobertura de puestos? de trabajo\s+(.+)$", re.I)
EXTENSION = re.compile(r"ampliaci[óo]n.*plazo", re.I)
DAY = re.compile(r"(\d{1,2}) de (" + "|".join(MONTHS) + r")(?: de)? (\d{4})", re.I)
CONTRACT = re.compile(r"Tipo de Contrato:\s*Contrato\s+(Indefinido|Temporal)", re.I)
WORKPLACE = re.compile(r"Centro de trabajo:[^•]*?[–-]\s*([^•()–-]+?)\s*\(", re.I)


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def parse_page(html: str) -> list[dict]:
    """Los procesos, del más antiguo al más reciente, cada uno con sus documentos en orden de fecha."""
    soup = BeautifulSoup(html, "html.parser")
    tab = soup.find(string=re.compile(r"OFERTAS DISPONIBLES"))
    panel = tab.find_parent(class_="CollapsiblePanel") if tab else None
    content = panel.select_one(".CollapsiblePanelContent") if panel else None
    if content is None:
        raise SourceLayoutError("Mercasturias: no se encuentra el panel de ofertas disponibles")
    documents = []
    for link in content.find_all("a", href=True):
        label = _clean(link.get_text(" "))
        following = link.find_next_sibling(string=lambda s: s and s.strip())
        found = DAY.search(following or "")
        day = spanish_date(*found.groups()) if found else None
        if not label or day is None:
            raise SourceLayoutError(f"Mercasturias: documento sin título o sin fecha: «{label}»")
        documents.append({"label": label, "date": day.isoformat(), "url": urljoin(PAGE, link["href"])})
    processes: list[dict] = []
    for document in reversed(documents):  # del más antiguo al más reciente
        bases = BASES.match(document["label"])
        if bases:
            processes.append({"title": document["label"], "job": bases.group(1), "ref": document["url"],
                              "documents": [document]})
        elif processes:
            processes[-1]["documents"].append(document)
        else:
            raise SourceLayoutError(f"Mercasturias: documento anterior a cualquier bases: «{document['label']}»")
    return processes


def _is_candidate(process: dict) -> bool:
    """Solo bases y ampliaciones: aún no hay relaciones de admitidos ni otras fases."""
    return all(EXTENSION.search(d["label"]) for d in process["documents"][1:])


class MercasturiasSource(Source):
    id = "mercasturias"
    name = "Mercasturias"
    homepage = PAGE
    apply_label = "Ver las bases y cómo presentar la candidatura"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._processes: list[dict] | None = None
        self._open: dict[str, dict] = {}  # ref → plazo y datos de las bases, de las que son oferta

    def _read(self, http: Client) -> list[dict]:
        if self._processes is None:
            self._processes = parse_page(http.get(PAGE))
            now = self._now or datetime.now(timezone.utc)
            for process in self._processes:
                if not _is_candidate(process):
                    continue
                texts = [read_pdf(http, d["url"], f"Mercasturias, {d['label']}") for d in process["documents"]]
                day, hour = latest([found for text in texts for found in deadlines_at(text)])
                if day is None or deadline_passed(day.isoformat(), hour, now):
                    continue
                contract, workplace = CONTRACT.search(texts[0]), WORKPLACE.search(texts[0])
                self._open[process["ref"]] = {
                    "deadline": day.isoformat(), "deadline_time": hour,
                    "kind": contract.group(1).lower() if contract else None,
                    "location": _clean(workplace.group(1)) if workplace else None,
                    "system": selection_system(texts[0]),
                }
        return self._processes

    def list_offers(self, http: Client) -> list[ListedOffer]:
        offers = []
        for process in self._read(http):
            data = self._open.get(process["ref"])
            if data is None:
                continue
            offers.append(ListedOffer(
                ref=process["ref"], title=process["job"], company=COMPANY, url=process["ref"],
                apply_url=process["ref"], kind=data["kind"], deadline=data["deadline"],
                deadline_time=data["deadline_time"], published_on=process["documents"][0]["date"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        process = next((p for p in self._read(http) if p["ref"] == offer.ref), None)
        if process is None:
            return OfferDetail()
        items = "".join(f'<li><a href="{escape(d["url"], quote=True)}">{escape(d["label"])}</a> (publicado el {date.fromisoformat(d["date"]).strftime("%d/%m/%Y")})</li>'
                        for d in process["documents"])
        return OfferDetail(location=self._open[offer.ref]["location"], sections=[
            {"title": "Documentos de la convocatoria", "level": 2, "html": sanitize(f"<ul>{items}</ul>")},
            {"title": "Cómo presentar la candidatura", "level": 2,
             "html": "<p>Las bases, en la web oficial, explican cómo presentar la candidatura (por correo "
                     "electrónico) y qué documentación acompañar.</p>"},
        ])

    def list_announcements(self, http: Client) -> list[Announcement]:
        """Los documentos de los procesos que no son oferta, con su fecha."""
        return [
            Announcement(date=d["date"], process=process["title"], title=d["label"], url=d["url"],
                         via="otro", process_url=PAGE)
            for process in self._read(http) if process["ref"] not in self._open
            for d in process["documents"]
        ]
