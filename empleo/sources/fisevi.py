"""FISEVI (Fundación para la Gestión de la Investigación en Salud de Sevilla).

WordPress. Las convocatorias son entradas de la categoría 45. La página `/ofertas-de-empleo/` da 6
por página con una etiqueta «Abierta» o «Cerrada» que no sigue el plazo (140 «abiertas» el
2026-11-08), así que el listado se pide a la API REST: una petición con id, fecha, enlace y título.
La API da el contenido vacío, así que se lee cada entrada publicada en los últimos `DIAS` días: el
plazo dura de 6 a 10 días desde la publicación.

En la entrada: «Modalidad contractual: …» (texto literal) y «Antes de las 23:59 horas del día 13
de noviembre de 2026». El año a veces está mal (una del 03/11/2026 decía «17 de septiembre de
2023»), así que el plazo solo vale si cae entre la publicación y `MAX_PLAZO` días después; si no,
la entrada no se ofrece. Tampoco se ofrecen las que mencionan una anulación. Una corrección de
errores en PDF que cambie el plazo no se detecta. Clave: id de la entrada. Solo se enlaza la
entrada: el seguimiento incluye resoluciones.
"""
from __future__ import annotations

import html
import json
import re
from datetime import date, datetime, timedelta, timezone

from bs4 import BeautifulSoup

from ..dates import spanish_date
from ..http import Client
from ..model import MADRID, ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from .base import Source

SITE = "https://fisevi.com"
PAGE = f"{SITE}/ofertas-de-empleo/"
API = f"{SITE}/wp-json/wp/v2/posts?categories=45&per_page=50&_fields=id,date,link,title&after="
DIAS = 15
MAX_PLAZO = 60
PLAZO = re.compile(r"Antes de las (\d{1,2})[:.](\d{2}) horas del día (\d{1,2}) de ([a-záéíóú]+) de (\d{4})", re.I)


def parse_posts(text: str) -> list[dict]:
    try:
        posts = json.loads(text)
        return [{"ref": str(p["id"]), "published_on": p["date"][:10], "url": p["link"],
                 "title": " ".join(html.unescape(p["title"]["rendered"]).split())} for p in posts]
    except (ValueError, KeyError, TypeError) as error:
        raise SourceLayoutError(f"FISEVI: la API no da el listado esperado ({error})") from error


def parse_entry(page: str) -> dict | None:
    """Plazo y contrato de la entrada, o None si no publica un plazo o está anulada."""
    content = BeautifulSoup(page, "html.parser").select_one(".post-content")
    if content is None:
        raise SourceLayoutError("FISEVI: entrada sin contenido")
    text = " ".join(content.get_text(" ").split())
    found = PLAZO.search(text)
    if found is None or re.search(r"anulaci[oó]n", text, re.I):
        return None
    hour, minute, day, month, year = found.groups()
    deadline = spanish_date(day, month, year)
    if deadline is None:
        return None
    contract = None
    for item in content.find_all("li"):
        label = item.find("strong")
        if label and "Modalidad contractual" in label.get_text():
            contract = " ".join(item.get_text(" ").split()).split(":", 1)[-1].strip().rstrip(".") or None
    return {"deadline": deadline, "deadline_time": f"{int(hour):02d}:{minute}", "contract": contract}


class FiseviSource(Source):
    id = "fisevi"
    name = "FISEVI"
    homepage = PAGE
    title_code = re.compile(r"(?P<title>.+?)\s+REF:\s*(?P<code>.+)")  # «… REF: 297/26 IBiS»
    scope = "Andalucía"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        since = (now.astimezone(MADRID) - timedelta(days=DIAS)).strftime("%Y-%m-%dT00:00:00")
        posts = parse_posts(http.get(API + since))
        offers, read, dated = [], 0, 0
        for post in posts:
            entry = parse_entry(http.get(post["url"]))
            read += 1
            if entry is None:
                continue
            dated += 1
            published = date.fromisoformat(post["published_on"])
            if not published <= entry["deadline"] <= published + timedelta(days=MAX_PLAZO):
                continue  # año equivocado: el plazo no es fiable
            deadline = entry["deadline"].isoformat()
            if deadline_passed(deadline, entry["deadline_time"], now):
                continue
            offers.append(ListedOffer(
                ref=post["ref"], title=post["title"], company="FISEVI", url=post["url"], apply_url=post["url"],
                kind=None, deadline=deadline, deadline_time=entry["deadline_time"],
                published_on=post["published_on"], contract=entry["contract"],
            ))
        if read and not dated:
            raise SourceLayoutError("FISEVI: ninguna entrada trae el plazo con la frase esperada")
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        return OfferDetail(location="Sevilla")
