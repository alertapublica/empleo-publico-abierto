"""Lector de bases en PDF: qué dicen las bases de las ofertas cuya ficha apenas tiene texto.

Exploración, no producción: no toca `data/` ni la web. Lee los PDF que enlazan las fichas de las ofertas
abiertas (por defecto, solo las que no tienen texto bastante para saber si mencionan el teletrabajo;
`teletrabajo.UNKNOWN`) y, si se le da, una lista de URL de bases de organismos que aún no se leen. De cada
PDF saca, con la frase literal y su página, lo que diga sobre teletrabajo, titulación, jornada,
retribución y plazo. Con el informe se decide qué merece pasar a la ingesta.

Se lanza desde GitHub Actions (workflow «Bases»), que guarda el informe como artefacto:

    python -m empleo.bases [--todas] [--max N] [--urls fichero] [fuente ...]

Todo es determinista (expresiones regulares): nada de modelos de lenguaje.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from html import unescape
from pathlib import Path
from urllib.parse import urljoin

from . import store, teletrabajo
from .http import Client
from .pdftext import deadlines, page_texts

DATA = Path("data")
OUT = Path("bases")
DELAY = 2.0
MAX_PDFS = 60  # por ejecución
PDFS_PER_OFFER = 2  # las bases suelen ser el primer documento
MAX_BYTES = 10_000_000
MAX_PHRASES = 3  # por campo y PDF
MAX_CHARS = 240

HREF = re.compile(r'href="([^"]+)"', re.I)
SENTENCE = re.compile(r"(?<=[.;])\s+(?=[-–•¿¡\"«(]?[A-ZÁÉÍÓÚÑÀÈÒÇ0-9])")
# Qué se busca en las bases, por campo. Cada uno da frases literales; el informe no clasifica nada.
FIELDS = {
    "teletrabajo": teletrabajo.MENTION,
    "presencial": teletrabajo.ONSITE,
    "titulacion": re.compile(
        r"titulaci[oó]n|estar en posesi[oó]n del? t[ií]tulo|t[ií]tulo (?:universitario|oficial|de (?:grado|m[aá]ster|"
        r"licenciad|diplomad|ingenier|t[eé]cnic|bachiller|graduad|doctor))|ciclo formativo|formaci[oó]n profesional", re.I),
    "jornada": re.compile(r"jornada (?:completa|parcial|laboral|de trabajo|continua|partida|ordinaria)|horas semanales"
                          r"|\d+\s*h(?:oras)?\s*(?:/|a la|por)\s*semana", re.I),
    "retribucion": re.compile(r"retribuci[oó]n|salario|sueldo|bruto anual|brutos? anuales|€|euros", re.I),
}


def is_pdf(url: str) -> bool:
    return url.lower().split("?")[0].split("#")[0].endswith(".pdf")


def pdf_links(offer: dict) -> list[str]:
    """Los PDF de la oferta: su propia URL si es un PDF y los que enlaza su ficha, sin repetir y en orden."""
    found = [offer["url"]] if is_pdf(offer.get("url") or "") else []
    for section in offer.get("sections") or []:
        found += [urljoin(offer["url"], unescape(href)) for href in HREF.findall(section.get("html") or "")
                  if is_pdf(unescape(href))]
    return list(dict.fromkeys(found))


def sentences(text: str) -> list[str]:
    return [" ".join(s.split()) for s in SENTENCE.split(text) if s.strip()]


def detect(pages: list[str]) -> dict:
    """Por campo, las primeras frases que lo mencionan, con su página (1, 2…); y las fechas de fin de plazo."""
    found: dict[str, list[dict]] = {name: [] for name in FIELDS}
    for number, text in enumerate(pages, start=1):
        for sentence in sentences(text):
            for name, pattern in FIELDS.items():
                if len(found[name]) < MAX_PHRASES and pattern.search(sentence):
                    phrase = sentence if len(sentence) <= MAX_CHARS else sentence[:MAX_CHARS - 1] + "…"
                    found[name].append({"pagina": number, "frase": phrase})
    found["plazo"] = [day.isoformat() for day in deadlines(" ".join(pages))][:MAX_PHRASES]
    return found


def read(http: Client, url: str) -> dict:
    """Un PDF: si se lee, cuántas páginas tiene y qué dice; si no, por qué."""
    try:
        data = http.get_bytes(url)
        if len(data) > MAX_BYTES:
            return {"url": url, "legible": False, "motivo": f"más de {MAX_BYTES // 1_000_000} MB"}
        pages = page_texts(data, url)
    except Exception as error:  # cada PDF por su cuenta: uno malo no para el informe
        return {"url": url, "legible": False, "motivo": str(error)[:200]}
    if not any(page.strip() for page in pages):
        return {"url": url, "legible": False, "motivo": "sin texto (¿escaneado?)", "paginas": len(pages)}
    return {"url": url, "legible": True, "paginas": len(pages), **detect(pages)}


def candidates(data: Path, sources: list[str], everything: bool) -> list[dict]:
    """Ofertas abiertas con PDF enlazado; sin `everything`, solo las de ficha sin texto bastante."""
    found = []
    for path in sorted(data.glob("*/offers.json")):
        if sources and path.parent.name not in sources:
            continue
        for offer in store.load(path, {}).values():
            if offer.get("status") != "open":
                continue
            if not everything and teletrabajo.read(offer).state != teletrabajo.UNKNOWN:
                continue
            links = pdf_links(offer)
            if links:
                found.append({"id": offer["id"], "fuente": offer["source"], "titulo": offer["title"],
                              "ficha": offer["url"], "pdfs": links[:PDFS_PER_OFFER]})
    return found


def extra(path: Path) -> list[dict]:
    """Bases sueltas de organismos que aún no se leen: una línea «organismo URL» por PDF."""
    found = []
    for line in path.read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) == 2 and not line.startswith("#"):
            found.append({"id": parts[1], "fuente": parts[0], "titulo": "(bases sueltas)", "ficha": parts[1],
                          "pdfs": [parts[1]]})
    return found


def report(results: list[dict]) -> str:
    """Informe en Markdown: un resumen por fuente y, por oferta, lo encontrado en cada PDF."""
    by_source: dict[str, Counter] = {}
    for item in results:
        count = by_source.setdefault(item["fuente"], Counter())
        count["ofertas"] += 1
        for pdf in item["leidos"]:
            count["pdf"] += 1
            count["legibles"] += pdf["legible"]
            for name in (*FIELDS, "plazo"):
                count[name] += bool(pdf.get(name))
    columns = ("ofertas", "pdf", "legibles", *FIELDS, "plazo")
    lines = ["# Lector de bases", "",
             "Frases literales de los PDF de bases; nada se clasifica. Cada campo cuenta los PDF que lo mencionan.", "",
             "| Fuente | " + " | ".join(columns) + " |", "|---|" + "---:|" * len(columns)]
    lines += [f"| {source} | " + " | ".join(str(count[c]) for c in columns) + " |"
              for source, count in sorted(by_source.items())]
    for item in results:
        lines += ["", f"## {item['fuente']} · {item['titulo']}", "", f"Ficha: {item['ficha']}"]
        for pdf in item["leidos"]:
            if not pdf["legible"]:
                lines.append(f"- {pdf['url']}: no legible ({pdf['motivo']})")
                continue
            lines.append(f"- {pdf['url']} ({pdf['paginas']} págs.)")
            for name in FIELDS:
                for hit in pdf[name]:
                    lines.append(f"  - **{name}** (p. {hit['pagina']}): «{hit['frase']}»")
            if pdf["plazo"]:
                lines.append(f"  - **plazo**: {', '.join(pdf['plazo'])}")
    return "\n".join(lines) + "\n"


def run(http: Client, items: list[dict], max_pdfs: int) -> list[dict]:
    results, budget = [], max_pdfs
    for item in items:
        if budget <= 0:
            break
        links = item["pdfs"][:budget]
        budget -= len(links)
        results.append({**item, "leidos": [read(http, url) for url in links]})
    return results


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("fuentes", nargs="*", help="ids de las fuentes (vacío: todas)")
    parser.add_argument("--todas", action="store_true", help="también las ofertas con ficha completa")
    parser.add_argument("--max", type=int, default=MAX_PDFS, help="PDF como mucho")
    parser.add_argument("--urls", type=Path, help="fichero con «organismo URL» por línea")
    args = parser.parse_args(argv)
    items = candidates(DATA, args.fuentes, args.todas) + (extra(args.urls) if args.urls else [])
    results = run(Client(DELAY), items, args.max)
    OUT.mkdir(exist_ok=True)
    (OUT / "bases.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    text = report(results)
    (OUT / "informe.md").write_text(text, encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main(sys.argv[1:])
