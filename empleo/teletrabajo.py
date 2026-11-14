"""Si el texto oficial de una oferta menciona el teletrabajo, y con qué frase.

No es una clasificación nuestra: se busca en la ficha guardada una expresión que solo se usa para
el trabajo a distancia y se enseña la frase tal cual, para que cada persona lea qué ofrece
(«posibilidad de hasta un 50 % de la jornada», «algunos días»...). Las palabras sueltas no
bastan: «entornos cloud o híbridos», «soporte en remoto», «atención presencial».

Cuatro estados (`read`):
- «menciona»: con la frase literal y, si la frase lo dice, cuánto («hasta el 50 %», «1 día a la
  semana», «algunos días»). Sin cifra no se supone ninguna;
- «sin»: la ficha lo niega con sus palabras («100% presencial», «sin teletrabajo»). Es una
  afirmación nuestra sobre el puesto: ante la duda, no se hace;
- «no_menciona»: la ficha tiene texto y no lo nombra. El silencio no se lee como «no hay»;
- «no_consta»: no se sabe, porque la ficha apenas tiene texto (solo enlaza a las bases en PDF,
  por ejemplo). Es un umbral de palabras, no una prueba de que falten las condiciones. Nunca se
  presenta como «no lo menciona».

`mention` da lo mismo en la forma que publica la API desde el principio: la frase, False o None.
"""
from __future__ import annotations

import html
import re
from typing import NamedTuple

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
# Para afirmar «sin teletrabajo» la negación tiene que ir pegada a la mención: «No es necesario viajar
# y se ofrece teletrabajo» no la niega.
DENIAL = re.compile(r"\b(?:no|sin|not|without|sense|non|ez)\b(?:\s+\S+){0,3}\s*$", re.I)
# Presencialidad total dicha del puesto, no de un curso o de una prueba («examen 100 % presencial»).
ONSITE = re.compile(r"100\s?%\s?(?:presencial|on-?site)|fully on-?site"
                    r"|(?:totalmente|totalment|exclusivamente|exclusivament|íntegramente) presencial", re.I)
NOT_THE_JOB = re.compile(r"\b(?:curs|cursos?|formaci[oó]n?|m[aà]ster|training|course|pruebas?|prov(?:a|es)|ex[aà]men(?:es|s)?"
                         r"|entrevistas?|selecci[oó]n?|test)\b", re.I)
# Apartados que solo enlazan documentos o repiten el plazo: no describen el puesto.
DOCUMENTS = re.compile(r"^(?:documentos|bases de la convocat|c[oó]mo presentar|convocatoria y bases|plazo$)", re.I)
# Cuánto, si la frase lo dice de la mención y no de otra cosa (jornada, viajes, días presenciales).
NEAR = 80
ADJACENT = 15
PERCENT = re.compile(r"(?:(hasta|fins a|up to)\s+(?:un |una |el |al |a )?)?(\d{1,3})\s?%", re.I)
OTHER_PERCENT = re.compile(r"(?:viaj\w*|travel\w*|despla[zç]\w*|presencial\w*|jornada)(?:\s+\S+){0,3}\s*$", re.I)
NUMBERS = {"un": 1, "una": 1, "uno": 1, "one": 1, "dos": 2, "two": 2, "tres": 3, "three": 3,
           "cuatro": 4, "quatre": 4, "four": 4}
DAYS = re.compile(r"\b(\d|" + "|".join(NUMBERS) + r")\s+(?:d[ií]as?|dies|days?)\b[^.;]{0,25}?(?:semana|setmana|week)", re.I)
OTHER_DAYS = re.compile(r"^\W*(?:\S+\s+){0,2}(?:presencial|on-?site|en la oficina|a l.oficina|in the office)", re.I)
SOME_DAYS = re.compile(r"algun[oa]s d[ií]as|alguns dies|some days", re.I)

MENTIONS, WITHOUT, SILENT, UNKNOWN = "menciona", "sin", "no_menciona", "no_consta"


class Remote(NamedTuple):
    state: str  # MENTIONS, WITHOUT, SILENT o UNKNOWN
    phrase: str | None = None  # frase literal de la ficha, en «menciona» y «sin»
    detail: str | None = None  # cuánto, en «menciona», si la frase lo dice
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


def detail(sentence: str, start: int, end: int) -> str | None:
    """Cuánto teletrabajo dice la frase, solo con lo que tiene al lado de la mención."""
    low, near = max(0, start - NEAR), sentence[max(0, start - NEAR):end + NEAR]
    for percent in PERCENT.finditer(near):
        # Un tope («hasta el 50 %») o una cifra pegada a la mención; no la de la jornada o los viajes.
        gap = min(abs(low + percent.start() - end), abs(start - (low + percent.end())))
        if (percent.group(1) or gap <= ADJACENT) and not OTHER_PERCENT.search(near[:percent.start()]):
            return f"{'hasta el ' if percent.group(1) else ''}{percent.group(2)} %"
    for days in DAYS.finditer(near):
        if not OTHER_DAYS.search(near[days.end():]):
            count = int(NUMBERS.get(days.group(1).lower(), days.group(1)))
            return "1 día a la semana" if count == 1 else f"{count} días a la semana"
    return "algunos días" if SOME_DAYS.search(near) else None


def read(offer: dict) -> Remote:
    sentences = lines(offer)
    denied = None
    for sentence in sentences:
        for match in MENTION.finditer(sentence):
            before = sentence[:match.start()]
            if not NEGATION.search(before):
                return Remote(MENTIONS, shorten(sentence, match.start()), detail(sentence, *match.span()))
            if DENIAL.search(before):
                denied = denied or shorten(sentence, match.start())
    for sentence in sentences:
        onsite = ONSITE.search(sentence)
        if onsite and not NOT_THE_JOB.search(sentence) and not NEGATION.search(sentence[:onsite.start()]):
            return Remote(WITHOUT, shorten(sentence, onsite.start()))
    if denied:
        return Remote(WITHOUT, denied)
    described = lines({"sections": [section for section in offer.get("sections") or []
                                    if not DOCUMENTS.search(section.get("title") or "")]})
    return Remote(UNKNOWN if sum(len(s.split()) for s in described) < MIN_WORDS else SILENT)


def mention(offer: dict) -> str | bool | None:
    remote = read(offer)
    if remote.state == MENTIONS:
        return remote.phrase
    return None if remote.state == UNKNOWN else False
