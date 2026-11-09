"""Fechas escritas en español, como las publican las empresas («17 de Noviembre de 2026»)."""
from __future__ import annotations

import re
from datetime import date

MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()


def month_number(name: str) -> int | None:
    name = name.strip().lower().rstrip(".")
    return MONTHS.index(name) + 1 if name in MONTHS else None


def spanish_date(day: str | int, month: str, year: str | int) -> date | None:
    number = month_number(month)
    if number is None:
        return None
    try:
        return date(int(year), number, int(day))
    except ValueError:
        return None


FULL_DATE = re.compile(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.I)


CLOCK = re.compile(r"\b([01]?\d|2[0-3])[:.]([0-5]\d)\b")


def clock(text: str | None) -> str | None:
    """Primera hora del texto como HH:MM («14:00», «12.00 h» → «12:00»)."""
    found = CLOCK.search(text or "")
    return f"{int(found.group(1)):02d}:{found.group(2)}" if found else None


DAY_AT_HOUR = re.compile(r"(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4}),?\s+(?:a\s+)?las\s+(\d{1,2}[:.]\d{2})", re.I)


def hour_on(text: str, day: date) -> str | None:
    """Hora de cierre que el texto da para ese día («11 de noviembre de 2026 a las 15.00 horas»).

    Solo si todas las menciones del día dan la misma hora: otro día u otra hora no valen.
    """
    hours = {clock(hour) for d, month, year, hour in DAY_AT_HOUR.findall(text) if spanish_date(d, month, year) == day}
    return hours.pop() if len(hours) == 1 else None


def latest(found: list[tuple[date, str | None]]) -> tuple[date | None, str | None]:
    """El último día de plazo y su hora, si alguna mención de ese día la da."""
    if not found:
        return None, None
    day = max(d for d, _ in found)
    hours = [h for d, h in found if d == day and h]
    return day, max(hours) if hours else None


def numeric_date(text: str) -> str:
    """«26/11/2026» → «2026-11-26»."""
    day, month, year = text.split("/")
    return f"{year}-{month}-{day}"


def first_date(text: str) -> date | None:
    """Primera fecha «D de mes de AAAA» del texto."""
    for day, month, year in FULL_DATE.findall(text):
        found = spanish_date(day, month, year)
        if found:
            return found
    return None
