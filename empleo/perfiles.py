"""Perfil de cada oferta de investigación: clasificación orientativa nuestra, solo para filtrar.

En los centros de investigación casi todo es «Investigación y laboratorio», así que el área no
distingue. El perfil dice quién busca el puesto: predoctoral, investigador/a, técnico/a de
laboratorio o apoyo, ensayos clínicos, datos y bioinformática, sanitario, gestión. Se deduce del
título con reglas deterministas (sin servicios externos): gana la primera regla de PERFILES que
case, así que el orden importa. Antes que ellas va ARRANQUE: un título que empieza por «Técnico/a de
laboratorio» o «de apoyo» es de técnico aunque el resto nombre la gestión o al investigador (salvo
«de apoyo a la gestión», que sigue las reglas). Sin regla, la oferta queda sin perfil.
Los casos revisados están en perfiles_referencia.csv (fuente, título, perfil): los tests exigen que
sigan saliendo igual; añadir allí una oferta es darla por revisada. `python -m empleo.perfiles
informe` lista las ofertas abiertas sin revisar que quedan sin perfil o en las que casan reglas de
más de un perfil (las dudosas): la publicación abre o actualiza un issue con ellas.
"""
from __future__ import annotations

import csv
import re
import sys
import unicodedata
from pathlib import Path

PERFILES = (
    ("predoctoral", "Predoctoral y en formación", r"predoc|pre-doc|\br1\b|phd (call|student|position)|en practicas|investigador\w* en formaci|doctoral student"),
    ("investigador", "Investigador/a (postdoctoral y sénior)",
     r"postdoc|posdoc|\br[234]a?\b|investigador|researcher|research fellow|\bdoctor\b|doctoral degree"),
    ("ensayos", "Ensayos clínicos",
     r"ensayos? (clinic|(en |de )?fase)|assaigs? (clinic|(en |de )?fase)|clinical trial|study (coordinator|nurse)|\bcra\b|\bcta\b"
     r"|\bmonitor(a|s|es|as)?\b|clinical research assistant"),
    ("sanitario", "Enfermería y sanitario",
     r"enfermer|infermer|nurse|auxiliar (clinic|sanitari)|farmaceutic|facultativ"),
    ("datos", "Datos y bioinformática",
     r"bioinformatic|bioestadist|biostatistic|data (manager|entry|scientist|analyst)|gestor(a)? de datos|software|platform engineer"),
    ("gestion", "Gestión y administración",
     r"\bgestio|gestor|manager|administrativ|administratiu|administrative|\badministra[ct]io|director|head of|recursos humanos|rrhh"
     r"|\bfinan(z|cier|cer|ceir)|\bfinanc(e|ial)\b|ethics|fundraising"
     r"|health and safety|tecnico de proyecto"),
    ("tecnico", "Técnico/a de laboratorio y apoyo",
     r"tecnic|technician|laborator|suport recerca|apoyo a la investigacion|research (assistant|support)|auxiliary|titulad[oa]"),
)
NAMES = {key: name for key, name, _ in PERFILES}
ARRANQUE = ("tecnico", r"^(?:un |una )?(?:personal )?tecnic\w* (?:de |d')?"
                       r"(?:laborator|(?:apoyo|suport)\b(?! (?:(?:a|en|de|para|per a)(?: la | l'| ))?(?:gestio|administra)))")
RULES = [(key, re.compile(rx)) for key, rx in (ARRANQUE, *((key, rx) for key, _, rx in PERFILES))]
BY_NAME = sorted(NAMES.items(), key=lambda kv: kv[1])
NONE = "sin-perfil"
REFERENCE = Path(__file__).with_name("perfiles_referencia.csv")


GENDER = re.compile(r"(?<=\w)\s?/\s?(?:a|as|o|os|ora|ra|na)\b")


def normalize(text: str) -> str:
    """Minúsculas, sin tildes y sin «/a»; conserva las cifras (R1, R2A), que aquí son perfil."""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c)).lower()
    return GENDER.sub("", text)


def matches(title: str) -> list[str]:
    """Perfiles con alguna regla que case, en el orden de las reglas: el primero es el que gana."""
    text = normalize(title)
    return list(dict.fromkeys(key for key, rule in RULES if rule.search(text)))


def classify(title: str) -> str:
    """Clave del perfil, o «» si el título no lo dice."""
    return next(iter(matches(title)), "")


def reference(path: Path = REFERENCE) -> list[dict]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def report(offers: list[dict], reviewed: set | None = None) -> str:
    """Markdown con las ofertas abiertas de investigación que no estén ya revisadas (en
    perfiles_referencia.csv) y quedan sin perfil o casan con reglas de más de un perfil; vacío si no
    queda ninguna."""
    if reviewed is None:
        reviewed = {(row["fuente"], row["titulo"]) for row in reference()}
    missing, doubtful = [], []
    for offer in sorted(offers, key=lambda o: (o["source"], o.get("title") or "")):
        if (offer["source"], offer.get("title")) in reviewed:
            continue
        found = matches(offer.get("title") or "")
        if not found:
            missing.append((offer, ""))
        elif len(found) > 1:
            others = ", ".join(NAMES[key] for key in found[1:])
            doubtful.append((offer, f" → {NAMES[found[0]]} (también casa: {others})"))

    def line(offer: dict, note: str) -> str:
        title = (offer.get("title") or "").replace("|", "/").replace("\n", " ")
        link = f"[{title}]({offer['url']})" if offer.get("url") else title
        return f"- `{offer['source']}` {link}{note}"

    if not missing and not doubtful:
        return ""
    out = [
        "Ofertas abiertas de investigación en las que el clasificador de perfiles (`empleo/perfiles.py`) "
        "no encuentra perfil en el título o encuentra más de uno. Para cada una: si el perfil está mal "
        "o el título lo dice y no sale, añade o corrige una regla; después, añádela a "
        "`empleo/perfiles_referencia.csv` con su perfil correcto (o vacío, si el título no lo dice) y "
        "deja de salir aquí.",
        "",
        "Este issue se actualiza solo en cada publicación y se cierra cuando la lista queda vacía.",
    ]
    if doubtful:
        out += ["", f"## Con más de un perfil posible ({len(doubtful)})", "",
                "Gana la primera regla. Comprueba que el perfil asignado es el del puesto.", ""]
        out += [line(o, note) for o, note in doubtful]
    if missing:
        out += ["", f"## Sin perfil ({len(missing)})", "", "Solo aparecen con «Todos» o «Sin perfil».", ""]
        out += [line(o, note) for o, note in missing]
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    from . import site  # importación tardía: site importa este módulo
    from .sources import ACTIVE

    if argv[:1] != ["informe"]:
        print("Uso: python -m empleo.perfiles informe [salida.md]", file=sys.stderr)
        return 2
    offers, _, _ = site.load_all(Path("data"))
    research = {s.id for s in ACTIVE if s.group in site.RESEARCH_GROUPS}
    text = report([o for o in offers.values() if o["status"] == "open" and o["source"] in research])
    if len(argv) > 1:
        Path(argv[1]).write_text(text, encoding="utf-8")
    else:
        sys.stdout.write(text)
    pending = sum(line.startswith("- `") for line in text.splitlines())
    print(f"Ofertas por revisar: {pending}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
