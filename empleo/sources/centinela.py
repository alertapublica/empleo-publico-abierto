"""Fuente centinela: vigila una página vacía sin saber aún cómo será con ofertas.

ADIF y Renfe no tienen hoy ninguna convocatoria abierta, así que su analizador no se puede
escribir ni probar. Mientras siga el texto oficial de «no hay ofertas», la empresa aparece sin
ofertas. Cuando desaparece, la ingesta de esa fuente falla a propósito: es el aviso de que hay
algo que leer y de que ya existe el HTML real con el que escribir el analizador.
"""
from __future__ import annotations

import re

from ..http import Client
from ..model import ListedOffer, SourceLayoutError
from .base import Source


class SentinelSource(Source):
    def __init__(self, id: str, name: str, homepage: str, page: str, empty_text: str) -> None:
        self.id = id
        self.name = name
        self.homepage = homepage
        self.page = page
        self.empty_text = empty_text

    def list_offers(self, http: Client) -> list[ListedOffer]:
        if self.empty_text not in re.sub(r"\s+", " ", http.get(self.page)):
            raise SourceLayoutError(
                f"{self.name}: ya no dice «{self.empty_text}». "
                f"Puede haber una convocatoria abierta en {self.page}: hay que escribir su analizador."
            )
        return []
