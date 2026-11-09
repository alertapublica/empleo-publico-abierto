"""Limpia el HTML ajeno: solo pasa una lista blanca de etiquetas y enlaces seguros."""
from __future__ import annotations

from bs4 import BeautifulSoup, NavigableString, Tag

ALLOWED = {"p", "ul", "ol", "li", "strong", "em", "br", "a"}
DROP_WITH_CONTENT = {"script", "style", "iframe", "object", "embed", "template", "svg"}
ALIASES = {"b": "strong", "i": "em"}
SAFE_SCHEMES = ("http://", "https://", "mailto:")
INVISIBLE = "​﻿"


def sanitize(fragment: str) -> str:
    soup = BeautifulSoup(fragment, "html.parser")
    for tag in soup.find_all(DROP_WITH_CONTENT):
        tag.decompose()
    for tag in list(soup.find_all(True)):
        if tag.name in ALIASES:
            tag.name = ALIASES[tag.name]
        if tag.name not in ALLOWED:
            tag.unwrap()
            continue
        href = tag.get("href", "") if tag.name == "a" else ""
        tag.attrs = {}
        if tag.name == "a":
            if href.lower().startswith(SAFE_SCHEMES):
                tag["href"] = href
            else:
                tag.unwrap()
    for text in list(soup.find_all(string=True)):
        if isinstance(text, NavigableString):
            cleaned = text.translate({ord(c): None for c in INVISIBLE}).replace("\xa0", " ")
            if cleaned != text:
                text.replace_with(cleaned)
    for tag in reversed(soup.find_all(["p", "li", "strong", "em", "ul", "ol"])):
        if isinstance(tag, Tag) and not tag.get_text(strip=True) and not tag.find("br"):
            tag.decompose()
    return str(soup).strip()
