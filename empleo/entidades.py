"""Quién convoca y qué se solapa entre fuentes.

Una *fuente* es de dónde se lee (un portal); un *convocante*, quién convoca. Casi siempre coinciden,
pero no siempre: el portal de Tragsa publica ofertas de Tragsa y de Tragsatec, y Puertos del Estado
lista las convocatorias de las autoridades portuarias. `entidades.json` es la tabla, con los mismos ids
que las fuentes (son públicos en la API) y los nombres con que las publican. Basta para reconocer la
misma convocatoria en dos fuentes; de quién depende cada entidad (el organigrama) es otro asunto.

De momento solo se calcula y se informa: nada de esto cambia lo que se publica.
`python -m empleo.entidades informe [data]` lista, por fuente, a quién se asigna cada registro, lo que
queda sin convocante y las convocatorias que parecen la misma en dos fuentes, también las ya terminadas
(un duplicado del histórico se ve igual en la web y en la API). Si hay alguno, lo anota como aviso en Actions.
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


def comparable(title: str) -> str:
    """Título para buscar coincidencias: sin el sufijo de la autoridad o del código, sin tildes ni signos."""
    return slug(SUFFIX.sub("", title))


def _records(data: Path) -> list[dict]:
    """Todas las ofertas y todos los comunicados guardados, con su fuente, convocante y estado."""
    found = []
    for folder in sorted(p for p in data.iterdir() if p.is_dir()):
        source = folder.name
        for offer in store.load(folder / "offers.json", {}).values():
            status = offer.get("status")
            found.append({"source": source, "kind": "oferta", "title": offer["title"], "state": status,
                          "live": status == "open", "url": offer.get("url"),
                          "convocante": convocante(offer, source, "ofertas")})
        for notice in store.load(folder / "announcements.json", {}).values():
            state = notice.get("state")
            found.append({"source": source, "kind": "proceso", "title": notice["process"], "state": state,
                          "live": state in ("abierto", "curso"), "url": notice.get("process_url"),
                          "convocante": convocante(notice, source, "procesos")})
    return found


def duplicates(records: list[dict]) -> list[tuple[str, list[dict]]]:
    """Convocatorias del mismo convocante y título que aparecen en más de una fuente, vivas o no.

    Cada aparición es una oferta o un proceso de una fuente; los comunicados de un mismo proceso se
    juntan en una, con los estados que hayan tenido."""
    groups: dict[tuple, dict[tuple, dict]] = defaultdict(dict)
    for record in records:
        if not record["convocante"]:
            continue
        seen = groups[(record["convocante"], comparable(record["title"]))].setdefault(
            (record["source"], record["kind"], record["title"]),
            {"source": record["source"], "kind": record["kind"], "title": record["title"],
             "url": record["url"], "states": set()})
        seen["states"].add(record["state"] or "?")
        seen["url"] = seen["url"] or record["url"]
    return [(who, [items[k] for k in sorted(items)]) for (who, _), items in sorted(groups.items())
            if len({source for source, _, _ in items}) > 1]


def _appearance(item: dict) -> str:
    title = f"[{item['title']}]({item['url']})" if item["url"] else item["title"]
    return f"{item['source']} ({item['kind']}, {'/'.join(sorted(item['states']))}): {title}"


def report(data: Path) -> str:
    records = _records(data)
    lines = ["# Convocantes por fuente (ofertas abiertas y procesos en marcha)", ""]
    by_source: dict[str, Counter] = defaultdict(Counter)
    for record in records:
        if record["live"]:
            by_source[record["source"]][record["convocante"]] += 1
    for source, counts in sorted(by_source.items()):
        if set(counts) != {source}:
            lines.append(f"- {source}: " + ", ".join(f"{c or 'SIN CONVOCANTE'} {n}" for c, n in counts.most_common()))
    lines += ["", "# Posibles duplicados entre fuentes (mismo convocante y título, también en el histórico)", ""]
    found = duplicates(records)
    for who, items in found:
        lines.append(f"- {who}: " + " | ".join(_appearance(item) for item in items))
    if not found:
        lines.append("Ninguno.")
    return "\n".join(lines) + "\n"


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] == "informe":
        data = Path(sys.argv[2] if len(sys.argv) > 2 else "data")
        print(report(data), end="")
        found = duplicates(_records(data))
        if found:  # anotación de Actions: que se vea sin abrir el resumen
            print(f"::warning title=Duplicados entre fuentes::{len(found)} convocatoria(s) en más de una fuente;"
                  " ver «Posibles duplicados» en el resumen", file=sys.stderr)
    else:
        print("Uso: python -m empleo.entidades informe [data]")


if __name__ == "__main__":
    main()
