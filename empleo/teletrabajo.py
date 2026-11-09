"""Si el texto oficial de una oferta menciona el teletrabajo, y con qué frase.

No es una clasificación nuestra: se busca en la ficha guardada una expresión que solo se usa para
el trabajo a distancia y se enseña la frase tal cual, para que cada persona lea qué ofrece
(«posibilidad de hasta un 50 % de la jornada», «algunos días»...). Las palabras sueltas no
bastan: «entornos cloud o híbridos», «soporte en remoto», «atención presencial».

Tres resultados posibles:
- la frase literal: la ficha lo menciona;
- False: la ficha tiene texto suficiente y no dice que haya teletrabajo (no lo nombra, o lo niega);
- None: no se sabe, porque la ficha no trae las condiciones (solo enlaza a las bases en PDF,
  por ejemplo). Nunca se presenta como «no lo menciona».
"""
from __future__ import annotations

import html
import re

# Por debajo de esto la ficha no describe el puesto: suele ser solo «Bases de la convocatoria».
MIN_WORDS = 80
MAX_CHARS = 240

MENTION = re.compile(
    r"tele-?trabaj|tele-?work|teletreball|teletraball|telelan"
    r"|trabaj\w* (?:a|en) (?:distancia|remoto)|trabaj\w* de forma (?:remota|no presencial)"
    r"|treball\w* a dist[aà]ncia|traball\w* a distancia"
    r"|remote(?:ly)? work|work\w* remotely|hybrid work|trabajo h[ií]brido|modalidad h[ií]brida",
    re.I,
)
# «Sin teletrabajo», «no se contempla el teletrabajo», «no remote work».
NEGATION = re.compile(r"\b(?:no|sin|not|without|sense|non|ez)\b[^.;:]{0,40}$", re.I)
BLOCK = re.compile(r"<(?:br|/p|/li|/div|/h\d|/tr|/dd|/dt)\b[^>]*>", re.I)
TAGS = re.compile(r"<[^>]+>")
SENTENCE = re.compile(r"(?<=[.;!?])\s+(?=[-–•¿¡\"«(]?[A-ZÁÉÍÓÚÑÀÈÒÇ])")


def lines(offer: dict) -> list[str]:
    """Frases de la ficha, respetando párrafos y elementos de lista."""
    result = []
    for section in offer.get("sections") or []:
        text = html.unescape(TAGS.sub(" ", BLOCK.sub("\n", section.get("html") or "")))
        for line in text.split("\n"):
            result += [" ".join(s.split()).lstrip("-–•· ") for s in SENTENCE.split(line) if s.strip()]
    return result


def shorten(sentence: str, start: int) -> str:
    """Recorta frases muy largas alrededor de la mención, sin cortar palabras."""
    if len(sentence) <= MAX_CHARS:
        return sentence
    begin = max(0, start - MAX_CHARS // 3)
    begin = sentence.rfind(" ", 0, begin) + 1 if begin else 0
    end = sentence.find(" ", begin + MAX_CHARS)
    piece = sentence[begin:end if end != -1 else None]
    return ("…" if begin else "") + piece + ("…" if end != -1 else "")


def mention(offer: dict) -> str | bool | None:
    sentences = lines(offer)
    for sentence in sentences:
        for match in MENTION.finditer(sentence):
            if not NEGATION.search(sentence[:match.start()]):
                return shorten(sentence, match.start())
    if sum(len(s.split()) for s in sentences) < MIN_WORDS:
        return None
    return False
