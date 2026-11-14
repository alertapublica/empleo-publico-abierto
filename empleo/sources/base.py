"""Contrato de una fuente. Para añadir una empresa basta con implementarlo."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod

from ..http import DEFAULT_DELAY, Client
from ..model import Announcement, ListedOffer, OfferDetail


class Source(ABC):
    id: str  # corto y estable: forma parte de las URL
    name: str
    homepage: str
    group: str = ""  # clave de GROUPS: la pone el catálogo de `sources/__init__.py`
    scope: str = "Estatal"  # ámbito: «Estatal» o la comunidad autónoma (nombre de REGIONS)
    delay: float = DEFAULT_DELAY  # pausa entre peticiones: más si el portal la pide (Crawl-delay)
    # Procesos que la fuente nunca da por terminados: pasan a «sin novedades» a los N días de verlos,
    # y los que ya estaban en la primera lectura, desde el principio. Sin fecha, vale la de entonces.
    stale_after_days: int | None = None
    apply_label = "Inscribirse en la web oficial"  # texto del botón de la ficha
    # Idioma de los textos de la fuente si no es el castellano («en»): `lang` del título y del texto
    # oficial de la ficha, para que el lector de pantalla los pronuncie bien. Se fija por fuente.
    text_lang: str | None = None
    # Súbela al cambiar lo que `fetch_detail` saca de la ficha: el motor relee la de las abiertas.
    detail_version: int = 1
    # Código que el portal pega al título («OE 25/26 - Analista»): grupos `title`, `code` y, si hace
    # falta, otros que se añaden al código. Si el título no encaja entero, se deja como está.
    title_code: re.Pattern | None = None
    # Los `ref` que encajan son el código que el portal publica con la oferta; el resto (ids de URL,
    # hashes, slugs) son internos y no se enseñan.
    ref_code: re.Pattern | None = None
    # Marcado JobPosting (site.jobposting). Apartados sin los que la ficha no describe el puesto, en
    # fuentes de plantilla fija que a veces los omiten: si falta uno, la ficha no lleva marcado.
    required_sections: tuple[str, ...] = ()
    # Frases con las que la fuente dice que la ficha no es un puesto concreto (bolsa sin vacante actual,
    # varios perfiles en una ficha): se publica igual, pero sin marcado.
    not_a_post: re.Pattern | None = None

    def labels(self, title: str, ref: str, code: str | None = None) -> dict:
        """Título limpio, código público y título literal (solo si cambia)."""
        if self.ref_code and self.ref_code.fullmatch(ref):
            code = code or ref
        match = self.title_code.fullmatch(title) if self.title_code else None
        if match is None:
            return {"title": title, "code": code, "source_title": None}
        found = " ".join(value for key, value in match.groupdict().items() if key != "title" and value)
        return {"title": match["title"], "code": found, "source_title": title}

    @abstractmethod
    def list_offers(self, http: Client) -> list[ListedOffer]:
        """Todas las ofertas abiertas. Debe lanzar SourceLayoutError si la página cambia."""

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        """Detalle de una oferta, o None si ya no existe."""
        return OfferDetail()

    def enrich(self, http: Client) -> dict[str, dict]:
        """Datos extra por `ref` (published_on, location, family, department)."""
        return {}

    def list_announcements(self, http: Client) -> list[Announcement]:
        return []
