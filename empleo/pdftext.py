"""Texto y plazos de las bases en PDF.

Varias empresas del Grupo SEPI publican el plazo solo dentro de las bases de cada proceso.
Aquí se lee ese texto y se busca la fecha de fin de plazo («hasta las 12:00 h del 29 de octubre
de 2026», «finalizará el 16 de noviembre de 2026»).

Los anexos con forma de formulario (casillas y columnas, como los de las tasas de reposición de Ineco)
se leen por posición: `fragments` da cada trozo de texto con sus coordenadas y `text_in`, lo que cae en
un recuadro. Cada fuente sabe dónde está cada casilla en su plantilla.
"""
from __future__ import annotations

import io
import re
from datetime import date
from typing import NamedTuple

from pypdf import PdfReader
from pypdf.errors import PyPdfError

from .dates import MONTHS, clock, spanish_date
from .http import Client
from .model import SourceLayoutError

DEADLINE = re.compile(
    r"(?:finalizar[áa]|hasta)\s+(?:el\s+(?:pr[óo]ximo\s+)?(?:d[ií]a\s+)?|las?\s+(\d{1,2}[:.]\s?\d{2})\s*(?:h|horas)\.?\s+del?\s+(?:d[ií]a\s+)?)"
    r"(\d{1,2})\s+de\s+(" + "|".join(MONTHS) + r")\s+de\s+(\d{4})", re.I)


def page_texts(data: bytes, what: str) -> list[str]:
    """El texto de cada página, tal como sale (puede estar vacío: página escaneada)."""
    try:
        return [page.extract_text() or "" for page in PdfReader(io.BytesIO(data)).pages]
    except (PyPdfError, ValueError, OSError) as error:
        raise SourceLayoutError(f"{what}: el PDF no se puede leer ({error})") from error


def pdf_text(data: bytes, what: str) -> str:
    """Texto de todas las páginas, con los espacios normalizados."""
    text = re.sub(r"\s+", " ", " ".join(page_texts(data, what))).strip()
    if not text:
        raise SourceLayoutError(f"{what}: el PDF no tiene texto")
    return text


def read_pdf(http: Client, url: str, what: str) -> str:
    return pdf_text(http.get_bytes(url), what)


class Fragment(NamedTuple):
    """Un trozo de texto del PDF y dónde empieza (puntos, origen abajo a la izquierda)."""

    page: int
    x: float
    y: float
    text: str


def fragments(data: bytes, what: str) -> list[Fragment]:
    """Los trozos de texto con su posición, para las plantillas de formulario (casillas, columnas), en las
    que el orden del texto extraído no sigue la maquetación. Un PDF sin texto (escaneado) es un error: aquí
    no hay OCR."""
    found: list[Fragment] = []
    try:
        for number, page in enumerate(PdfReader(io.BytesIO(data)).pages):
            def visit(text, cm, tm, font, size, number=number):
                if text.strip():
                    # Posición en la página: la del texto (tm) transformada por la de la página (cm).
                    x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
                    y = tm[4] * cm[1] + tm[5] * cm[3] + cm[5]
                    found.append(Fragment(number, x, y, " ".join(text.split())))
            page.extract_text(visitor_text=visit)
    except (PyPdfError, ValueError, OSError) as error:
        raise SourceLayoutError(f"{what}: el PDF no se puede leer ({error})") from error
    if not found:
        raise SourceLayoutError(f"{what}: el PDF no tiene texto")
    return found


def text_in(found: list[Fragment], page: int, left: float, right: float, top: float, bottom: float) -> str:
    """El texto de un recuadro (x de `left` a `right`, y de `bottom` a `top`, sin los bordes), por líneas de
    arriba abajo y, en cada línea, de izquierda a derecha."""
    inside = sorted((f for f in found if f.page == page and left <= f.x < right and bottom < f.y < top),
                    key=lambda f: (-round(f.y), f.x))
    return " ".join(f.text for f in inside).strip()


def deadlines_at(text: str) -> list[tuple[date, str | None]]:
    """Fechas de fin de plazo que menciona el texto, con su hora si va delante («hasta las 12:00 h del…»)."""
    # La extracción del PDF parte a veces la hora («23: 59», Mercasturias).
    found = ((spanish_date(day, month, year), clock(hour.replace(" ", "")))
             for hour, day, month, year in DEADLINE.findall(text))
    return [(day, hour) for day, hour in found if day]


def deadlines(text: str) -> list[date]:
    """Fechas de fin de plazo que menciona el texto, en el orden en que aparecen."""
    return [day for day, _ in deadlines_at(text)]
