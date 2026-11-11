"""Quién convoca, de quién depende y qué se solapa entre fuentes.

Una *fuente* es de dónde se lee (un portal); un *convocante*, quién convoca. Casi siempre coinciden,
pero no siempre: el portal de Tragsa publica ofertas de Tragsa y de Tragsatec, y Puertos del Estado
lista las convocatorias de las autoridades portuarias. `entidades.json` es la tabla, con los mismos ids
que las fuentes (son públicos en la API) y la dependencia de cada entidad (`depende_de`).

De momento solo se calcula y se informa: nada de esto cambia lo que se publica.
`python -m empleo.entidades informe [data]` lista, por fuente, a quién se asigna cada registro, lo que
queda sin convocante y las convocatorias que parecen la misma en dos fuentes.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from . import store
from .text import slug

TABLE = Path(__file__).with_name("entidades.json")
SUFFIX = re.compile(r"\s*\((?:Autoridad Portuaria|[A-Z]{2,}[-\w/]*)[^()]*\)\s*$")


@lru_cache(maxsize=1)
def table() -> dict:
    data = json.loads(TABLE.read_text(encoding="utf-8"))
    entities = {e["id"]: e for e in data["entidades"]}
    aliases = {}
    for entity in data["entidades"]:
        for name in [entity["nombre"], *entity["alias"]]:
            aliases.setdefault(slug(name), entity["id"])
    return {"entities": entities, "aliases": aliases, "coverage": data["coberturas"]}


def _by_name(name: str | None) -> str | None:
    return table()["aliases"].get(slug(name)) if name else None


def convocante(record: dict, source: str, kind: str) -> str | None:
    """Id de quien convoca una oferta (`kind="ofertas"`) o un comunicado (`"procesos"`); None si no se sabe."""
    rule = table()["coverage"].get(source, {}).get(kind)
    if rule == "empresa":
        return _by_name(record.get("company"))
    if rule == "ubicacion":
        return _by_name(record.get("location"))
    return source if source in table()["entities"] else None


def ancestors(entity: str) -> list[str]:
    """De quién depende, del más cercano al más lejano."""
    found, current = [], table()["entities"][entity]["depende_de"]
    while current:
        found.append(current)
        current = table()["entities"][current]["depende_de"]
    return found


def descendants(entity: str) -> set[str]:
    """La entidad y todas las que dependen de ella, a cualquier nivel."""
    return {e for e in table()["entities"] if e == entity or entity in ancestors(e)}


def comparable(title: str) -> str:
    """Título para buscar coincidencias: sin el sufijo de la autoridad o del código, sin tildes ni signos."""
    return slug(SUFFIX.sub("", title))


def _live(data: Path) -> list[dict]:
    """Ofertas abiertas y comunicados de procesos vivos, con su fuente y su convocante."""
    found = []
    for folder in sorted(p for p in data.iterdir() if p.is_dir()):
        source = folder.name
        for offer in store.load(folder / "offers.json", {}).values():
            if offer.get("status") == "open":
                found.append({"source": source, "kind": "oferta", "title": offer["title"],
                              "convocante": convocante(offer, source, "ofertas")})
        for notice in store.load(folder / "announcements.json", {}).values():
            if notice.get("state") in ("abierto", "curso"):
                found.append({"source": source, "kind": "proceso", "title": notice["process"],
                              "convocante": convocante(notice, source, "procesos")})
    return found


def report(data: Path) -> str:
    records = _live(data)
    lines = ["# Convocantes por fuente", ""]
    by_source: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        by_source[record["source"]][record["convocante"]] += 1
    for source, counts in sorted(by_source.items()):
        if set(counts) != {source}:
            lines.append(f"- {source}: " + ", ".join(f"{c or 'SIN CONVOCANTE'} {n}" for c, n in counts.most_common()))
    lines += ["", "# Posibles duplicados entre fuentes (mismo convocante y título)", ""]
    groups = defaultdict(set)
    for record in records:
        if record["convocante"]:
            groups[(record["convocante"], comparable(record["title"]))].add((record["source"], record["kind"], record["title"]))
    duplicates = [(key, sorted(items)) for key, items in sorted(groups.items()) if len({s for s, _, _ in items}) > 1]
    for (who, _), items in duplicates:
        lines.append(f"- {who}: " + " | ".join(f"{s} ({k}): {t}" for s, k, t in items))
    if not duplicates:
        lines.append("Ninguno.")
    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "informe":
        print(report(Path(sys.argv[2] if len(sys.argv) > 2 else "data")), end="")
    else:
        print("Uso: python -m empleo.entidades informe [data]")


if __name__ == "__main__":
    main()
