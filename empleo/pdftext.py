"""Texto y plazos de las bases en PDF.

Varias empresas del Grupo SEPI publican el plazo solo dentro de las bases de cada proceso.
Aquí se lee ese texto y se busca la fecha de fin de plazo («hasta las 12:00 h del 29 de octubre
de 2026», «finalizará el 16 de noviembre de 2026»).
"""
from __future__ import annotations

import io
import re
from datetime import date

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .dates import MONTHS, clock, spanish_date
from .http import Client
from .model import SourceLayoutError

DEADLINE = re.compile(
    r"(?:finalizar[áa]|hasta)\s+(?:el\s+(?:d[ií]a\s+)?|las?\s+(\d{1,2}[:.]\s?\d{2})\s*(?:h|horas)\.?\s+del?\s+(?:d[ií]a\s+)?)"
    r"(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")\s+de\s+(\d{4})", re.I)


def pdf_text(data: bytes, what: str) -> str:
    """Texto de todas las páginas, con los espacios normalizados."""
    try:
        pages = PdfReader(io.BytesIO(data)).pages
        text = " ".join(page.extract_text() or "" for page in pages)
    except (PyPdfError, ValueError, OSError) as error:
        raise SourceLayoutError(f"{what}: el PDF no se puede leer ({error})") from error
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise SourceLayoutError(f"{what}: el PDF no tiene texto")
    return text


def read_pdf(http: Client, url: str, what: str) -> str:
    return pdf_text(http.get_bytes(url), what)


def deadlines_at(text: str) -> list[tuple[date, str | None]]:
    """Fechas de fin de plazo que menciona el texto, con su hora si va delante («hasta las 12:00 h del…»)."""
    # La extracción del PDF parte a veces la hora («23: 59», Mercasturias).
    found = ((spanish_date(day, month, year), clock(hour.replace(" ", "")))
             for hour, day, month, year in DEADLINE.findall(text))
    return [(day, hour) for day, hour in found if day]


def deadlines(text: str) -> list[date]:
    """Fechas de fin de plazo que menciona el texto, en el orden en que aparecen."""
    return [day for day, _ in deadlines_at(text)]
