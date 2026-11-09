"""Utilidades de texto comunes a las fuentes."""
from __future__ import annotations

import re
import unicodedata


INITIALS = re.compile(r"\b([a-zñ])\.([a-zñ])\.")


def humane_caps(text: str) -> str:
    """Los lectores de pantalla deletrean las mayúsculas sostenidas. Respeta el código final."""
    match = re.fullmatch(r"(.*?)(\s*\([^()]*\))?", text, re.S)
    body, code = match.group(1), match.group(2) or ""
    letters = [c for c in body if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.7:
        return text
    lowered = body.lower()
    for word in ("tragsatec", "tragsa"):
        lowered = lowered.replace(word, word.capitalize())
    lowered = INITIALS.sub(lambda m: f"{m.group(1).upper()}.{m.group(2).upper()}.", lowered)
    return lowered[0].upper() + lowered[1:] + code


def slug(text: str) -> str:
    """«Técnico/a de Análisis» → «tecnico-a-de-analisis»: estable y apta para una URL."""
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", plain.lower()).strip("-")


def mixed_decode(data: bytes) -> str:
    """UTF-8 donde lo es; el resto de bytes, como Latin-1 (webs antiguas con datos en UTF-8)."""
    parts, start = [], 0
    while True:
        try:
            parts.append(data[start:].decode("utf-8"))
            return "".join(parts)
        except UnicodeDecodeError as error:
            parts.append(data[start:start + error.start].decode("utf-8"))
            parts.append(data[start + error.start:start + error.end].decode("latin-1"))
            start += error.end
