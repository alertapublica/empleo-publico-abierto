"""Convierte ubicaciones en texto libre a comunidad autónoma, provincia y municipio."""
from __future__ import annotations

import csv
import re
import unicodedata
from functools import cache
from pathlib import Path

NATIONAL = "Ámbito nacional"
SEVERAL = "Varias comunidades"
UNKNOWN = "Sin ubicación"

_ALIASES = {
    "Andalucía": "andalucia almeria cadiz cordoba granada huelva jaen malaga sevilla cabril",
    "Aragón": "aragon huesca teruel zaragoza",
    "Asturias": "asturias oviedo gijon",
    "Illes Balears": "balears baleares mallorca menorca ibiza eivissa formentera",
    "Canarias": "canarias tenerife fuerteventura lanzarote|gran canaria|las palmas|la palma|la gomera|el hierro|santa cruz|sta. cruz",
    "Cantabria": "cantabria santander",
    "Castilla-La Mancha": "albacete|ciudad real|cuenca guadalajara toledo|castilla-la mancha|castilla la mancha",
    "Castilla y León": "avila burgos leon palencia salamanca segovia soria valladolid zamora juzbado garona|castilla y leon",
    "Cataluña": "cataluna catalunya barcelona girona gerona lleida lerida tarragona vandellos",
    "Ceuta": "ceuta",
    "Comunitat Valenciana": "valencia alicante alacant castellon castello|comunitat valenciana|comunidad valenciana",
    "Extremadura": "extremadura badajoz caceres",
    "Galicia": "galicia coruna ourense orense lugo pontevedra|santiago de compostela|vigo",
    "La Rioja": "rioja logrono",
    "Comunidad de Madrid": "madrid",
    "Melilla": "melilla",
    "Región de Murcia": "murcia",
    "Comunidad Foral de Navarra": "navarra nafarroa pamplona",
    "País Vasco": "araba alava gipuzkoa guipuzcoa bizkaia vizcaya bilbao vitoria donostia euskadi|pais vasco",
}
# "palma" solo se evalúa después de "las palmas" y "la palma": gana el alias más largo.
_ALIASES["Illes Balears"] += " palma"

REGIONS = sorted(_ALIASES) + [NATIONAL, SEVERAL, UNKNOWN]


def _normalize(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return re.sub(r"\s*-\s*", "-", plain)


def _build() -> list[tuple[str, str]]:
    multi = {
        "gran canaria", "las palmas", "la palma", "la gomera", "el hierro", "santa cruz",
        "sta. cruz", "ciudad real", "castilla-la mancha", "castilla la mancha",
        "castilla y leon", "santiago de compostela", "pais vasco", "comunitat valenciana",
        "comunidad valenciana",
    }
    table: list[tuple[str, str]] = []
    for region, names in _ALIASES.items():
        for chunk in names.split("|"):
            chunk = chunk.strip()
            if chunk in multi:
                table.append((chunk, region))
            else:
                table.extend((word, region) for word in chunk.split())
    return sorted(table, key=lambda item: -len(item[0]))


TABLE = _build()


def _found_regions(plain: str) -> set[str]:
    found = set()
    for alias, region in TABLE:
        pattern = rf"(?<![a-z]){re.escape(alias)}(?![a-z])"
        if re.search(pattern, plain):
            found.add(region)
            plain = re.sub(pattern, " ", plain)
    return found


def region_of(*candidates: str | None) -> str:
    """Devuelve la comunidad del primer texto que permita deducirla."""
    for text in candidates:
        if not text:
            continue
        plain = _normalize(text)
        if re.search(r"\bnacional\b|toda espana", plain):
            return NATIONAL
        if re.search(r"\bvarias\b", plain):
            return SEVERAL
        found = _found_regions(plain)
        if not found and (municipality := municipality_of(text)):  # «Rubí», «Ribes de Freser»
            found = {REGION_OF_CCAA[municipality[1]]}
        if len(found) == 1:
            return found.pop()
        if found:
            return SEVERAL
    return UNKNOWN


# Nombres de comunidad (o genéricos) que no son una localidad.
_NOT_A_PLACE = {
    "andalucia", "aragon", "asturias", "canarias", "cantabria", "castilla y leon",
    "castilla-la mancha", "cataluna", "extremadura", "galicia", "la rioja", "navarra",
    "pais vasco", "murcia", "comunitat valenciana", "illes balears", "baleares",
    "varias provincias", "varios", "nacional", "espana",
}
_MAX_PLACE = 35


def _place_ok(text: str) -> str | None:
    text = re.sub(r"^provincia de\s+", "", text.strip(), flags=re.I)
    plain = _normalize(text)
    if (not text or len(text) > _MAX_PLACE or plain in _NOT_A_PLACE
            or plain.startswith("comunidad de ") or region_of(text) in (UNKNOWN, SEVERAL, NATIONAL)):
        return None
    return text


def address_hint(sections: list[dict]) -> str | None:
    """Línea «Dirección: …» de la sección «Lugar de Trabajo», si la hay."""
    for section in sections:
        if section.get("title") == "Lugar de Trabajo":
            text = re.sub(r"<[^>]+>", "\n", section.get("html", ""))
            match = re.search(r"Direcci[oó]n:\s*([^\n]+)", text)
            if match:
                return match.group(1).strip()
    return None


def place_of(title: str, sections: list[dict]) -> str | None:
    """Localidad más concreta que deducen el título y la ficha, o None."""
    for hint in (location_from_title(title), address_hint(sections)):
        place = _place_ok(hint) if hint else None
        if place:
            return place
    return None


def location_from_title(title: str) -> str | None:
    """Algunas ofertas llevan la provincia entre paréntesis al final del título."""
    match = re.search(r"\(([^()]+)\)\s*$", title)
    return match.group(1).strip() if match else None


# Códigos del INE. La comunidad sale del nombre de `region_of`; la provincia y el municipio, de
# los textos de la fuente, solo si no hay duda.
CCAA = {
    "Andalucía": "01", "Aragón": "02", "Asturias": "03", "Illes Balears": "04", "Canarias": "05",
    "Cantabria": "06", "Castilla y León": "07", "Castilla-La Mancha": "08", "Cataluña": "09",
    "Comunitat Valenciana": "10", "Extremadura": "11", "Galicia": "12", "Comunidad de Madrid": "13",
    "Región de Murcia": "14", "Comunidad Foral de Navarra": "15", "País Vasco": "16", "La Rioja": "17",
    "Ceuta": "18", "Melilla": "19",
}
REGION_OF_CCAA = {code: name for name, code in CCAA.items()}

# Código: nombre oficial y otros nombres con que aparece (islas incluidas), separados por «|».
PROVINCES = {
    "01": ("Araba/Álava", "araba|alava"), "02": ("Albacete", "albacete"),
    "03": ("Alicante/Alacant", "alicante|alacant"), "04": ("Almería", "almeria"),
    "05": ("Ávila", "avila"), "06": ("Badajoz", "badajoz"),
    "07": ("Illes Balears", "illes balears|islas baleares|baleares|balears|mallorca|menorca|ibiza|eivissa|formentera"),
    "08": ("Barcelona", "barcelona"), "09": ("Burgos", "burgos"), "10": ("Cáceres", "caceres"),
    "11": ("Cádiz", "cadiz"), "12": ("Castellón/Castelló", "castellon|castello"),
    "13": ("Ciudad Real", "ciudad real"), "14": ("Córdoba", "cordoba"),
    "15": ("A Coruña", "a coruna|la coruna|coruna"), "16": ("Cuenca", "cuenca"),
    "17": ("Girona", "girona|gerona"), "18": ("Granada", "granada"),
    "19": ("Guadalajara", "guadalajara"), "20": ("Gipuzkoa", "gipuzkoa|guipuzcoa"),
    "21": ("Huelva", "huelva"), "22": ("Huesca", "huesca"), "23": ("Jaén", "jaen"),
    "24": ("León", "leon"), "25": ("Lleida", "lleida|lerida"), "26": ("La Rioja", "la rioja|rioja"),
    "27": ("Lugo", "lugo"), "28": ("Madrid", "madrid"), "29": ("Málaga", "malaga"),
    "30": ("Murcia", "murcia"), "31": ("Navarra", "navarra|nafarroa"),
    "32": ("Ourense", "ourense|orense"), "33": ("Asturias", "asturias"),
    "34": ("Palencia", "palencia"),
    "35": ("Las Palmas", "las palmas|gran canaria|fuerteventura|lanzarote"),
    "36": ("Pontevedra", "pontevedra"), "37": ("Salamanca", "salamanca"),
    "38": ("Santa Cruz de Tenerife",
           "santa cruz de tenerife|sta. cruz de tenerife|tenerife|la palma|la gomera|el hierro"),
    "39": ("Cantabria", "cantabria"), "40": ("Segovia", "segovia"), "41": ("Sevilla", "sevilla"),
    "42": ("Soria", "soria"), "43": ("Tarragona", "tarragona"), "44": ("Teruel", "teruel"),
    "45": ("Toledo", "toledo"), "46": ("Valencia/València", "valencia"),
    "47": ("Valladolid", "valladolid"), "48": ("Bizkaia", "bizkaia|vizcaya"),
    "49": ("Zamora", "zamora"), "50": ("Zaragoza", "zaragoza"), "51": ("Ceuta", "ceuta"),
    "52": ("Melilla", "melilla"),
}
_PROVINCE_TABLE = sorted(
    ((alias, code) for code, (_, names) in PROVINCES.items() for alias in names.split("|")),
    key=lambda item: -len(item[0]),
)
# Nombres de comunidad que contienen el de una provincia («Castilla y León»).
_REGION_NAMES = re.compile(r"castilla y leon|castilla-la mancha|castilla la mancha")


def _provinces_in(plain: str) -> set[str]:
    plain = _REGION_NAMES.sub(" ", plain)
    found = set()
    for alias, code in _PROVINCE_TABLE:
        pattern = rf"(?<![a-z]){re.escape(alias)}(?![a-z])"
        if re.search(pattern, plain):
            found.add(code)
            plain = re.sub(pattern, " ", plain)
    return found


@cache
def _municipalities() -> dict[str, list[tuple[str, str]]]:
    """Nombre normalizado -> [(código, comunidad)], de la relación del INE (municipios.csv)."""
    names: dict[str, list[tuple[str, str]]] = {}
    with open(Path(__file__).with_name("municipios.csv"), encoding="utf-8") as file:
        for row in csv.DictReader(file):
            for name in row["nombre"].split("/"):  # «Alacant/Alicante»
                name = name.strip()
                forms = {name}
                if match := re.fullmatch(r"(.+), (\S+)", name):  # «Palmas de Gran Canaria, Las»
                    forms |= {match[1], f"{match[2]} {match[1]}".replace("' ", "'")}
                for form in forms:
                    names.setdefault(_normalize(form), []).append((row["codigo"], row["ccaa"]))
    return names


def _area_name(plain: str) -> bool:
    """El texto es exactamente el nombre de una provincia o comunidad («Sevilla», «Murcia»)."""
    return (any(alias == plain for alias, _ in _PROVINCE_TABLE) or plain in _NOT_A_PLACE
            or plain in {_normalize(name) for name in CCAA})


def municipality_of(text: str | None) -> tuple[str, str] | None:
    """(código, comunidad) si el texto es un municipio sin ambigüedad: «Rubí», «Langreo (Asturias)»,
    «Moncada, Valencia». Un nombre que es también provincia o comunidad («Sevilla») no cuenta."""
    if not text:
        return None
    parts = re.split(r"\s*[(,]\s*", text.strip(), maxsplit=1)
    name, rest = _normalize(parts[0]), _normalize(parts[1]) if len(parts) > 1 else ""
    if not name or _area_name(name):
        return None
    candidates = _municipalities().get(name, [])
    if rest:
        provinces = _provinces_in(rest)
        regions = {CCAA[r] for r in _found_regions(rest)}
        candidates = [(code, ccaa) for code, ccaa in candidates
                      if (not provinces or code[:2] in provinces) and (not regions or ccaa in regions)]
    return candidates[0] if len(candidates) == 1 else None


def codes_of(region: str | None, *texts: str | None) -> dict:
    """Códigos INE de comunidad, provincia y municipio. La comunidad es la de `region`; provincia
    y municipio salen del primer texto que los dé sin contradecirla."""
    ccaa = CCAA.get(region or "")
    codes = {"ccaa": ccaa, "provincia": None, "municipio": None}
    if not ccaa:
        return codes
    uniprovincial = [province for province, owner in _ccaa_provinces() if owner == ccaa]
    for text in texts:
        if not text:
            continue
        found = municipality_of(text)
        if found and found[1] == ccaa and codes["provincia"] in (None, found[0][:2]):
            codes.update(provincia=found[0][:2], municipio=found[0])
            return codes
        provinces = {p for p in _provinces_in(_normalize(text)) if _ccaa_of_province(p) == ccaa}
        if len(provinces) == 1 and not codes["provincia"]:
            codes["provincia"] = provinces.pop()
    if not codes["provincia"] and len(uniprovincial) == 1:
        codes["provincia"] = uniprovincial[0]
    return codes


@cache
def _ccaa_provinces() -> tuple[tuple[str, str], ...]:
    """(provincia, comunidad) según la relación del INE."""
    pairs = {(code[:2], ccaa) for entries in _municipalities().values() for code, ccaa in entries}
    return tuple(sorted(pairs))


def _ccaa_of_province(province: str) -> str:
    return dict(_ccaa_provinces())[province]
