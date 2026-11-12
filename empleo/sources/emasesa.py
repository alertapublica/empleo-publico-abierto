"""EMASESA (Empresa Metropolitana de Abastecimiento y Saneamiento de Aguas de Sevilla): centinela.

El «Canal de empleo» tiene dos páginas. «Concursos públicos» es una tabla con todos los concursos,
también los cerrados: «Proceso», «Fecha fin solicitudes» (DD/MM/AAAA), «Nº de plazas», plazas para
personas con discapacidad, categoría y coste de la inscripción. No hay ficha por concurso: las bases y
la inscripción van por un formulario (POST) y `robots.txt` prohíbe las URL con parámetros y los PDF.
«Procesos selección» dice hoy «No hay procesos de selección». Publica pocos concursos (tres en
septiembre y octubre de 2026).

Hasta ver uno abierto, es un centinela: no da ofertas y se detiene, para escribir el analizador con la
página real, si algún concurso tiene la fecha fin sin vencer o si «Procesos selección» deja de decir
que no hay ninguno.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, SourceLayoutError, deadline_passed
from .base import Source

SITE = "https://www.emasesa.com"
CONCURSOS = SITE + "/canal-empleo-concursos-publicos/"
PROCESOS = SITE + "/canal-empleo-procesos-seleccion/"
EMPTY = "No hay procesos de selección"


def parse_concursos(html: str) -> list[dict]:
    table = BeautifulSoup(html, "html.parser").select_one("table[summary='Lista de concursos públicos']")
    if table is None or "Fecha fin solicitudes" not in table.get_text():
        raise SourceLayoutError("EMASESA: no se encuentra la tabla de concursos públicos")
    found = []
    for row in table.find_all("tr"):
        cells = row.find_all("td")
        if not cells:
            continue
        end = re.search(r"(\d{2})/(\d{2})/(\d{4})", cells[2].get_text() if len(cells) > 2 else "")
        if len(cells) < 3 or end is None:
            raise SourceLayoutError("EMASESA: concurso sin fecha fin de solicitudes")
        day, month, year = end.groups()
        found.append({"title": " ".join(cells[1].get_text(" ").split()),
                      "deadline": date(int(year), int(month), int(day)).isoformat()})
    return found


class EmasesaSource(Source):
    id = "emasesa"
    name = "EMASESA (Aguas de Sevilla)"
    homepage = CONCURSOS
    scope = "Andalucía"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        for row in parse_concursos(http.get(CONCURSOS)):
            if not deadline_passed(row["deadline"], None, now):
                raise SourceLayoutError(
                    f"EMASESA: «{row['title']}» tiene la fecha fin sin vencer ({row['deadline']}). "
                    f"Hay un concurso abierto en {CONCURSOS}: hay que escribir su analizador."
                )
        if EMPTY not in " ".join(http.get(PROCESOS).split()):
            raise SourceLayoutError(
                f"EMASESA: ya no dice «{EMPTY}». Puede haber un proceso abierto en {PROCESOS}."
            )
        return []
