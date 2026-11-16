"""Universidad de Córdoba: convocatorias de contratos de personal investigador y técnico (PIT).

Portal de Investigación (Joomla), página «Convocatorias de Contratos» (`/investigacion/portal/convocatorias-de-
contratos`): un artículo por tanda («11ª CONVOCATORIA DE CONTRATOS DE PERSONAL INVESTIGADOR Y TÉCNICO (PIT) 2026»),
de la más nueva a la más antigua, 20 por página (`?start=20`). Son tandas según un calendario anual aprobado por el
Consejo de Gobierno (11 en 2026; la 1.ª de 2027 se publica el 14/12/2026): varias plazas por tanda, que solo vienen en
los anexos del PDF de la resolución (sin leer). Se publica una oferta por tanda, como la USC.

Cada artículo trae entero, ya en el listado: la resolución con su fecha («30-10-2026 Resolución de 30 de octubre de
2026…», que da la publicación), el anuncio en el BOUCO, «Plazo de presentación de solicitudes: desde el 03 de
noviembre al 09 de noviembre de 2026» (también «desde el 22 al 28 de abril», «desde el 27 de mayo hasta el 2 de
junio»; sin hora), notas y, después, correcciones, listas de admitidos y de selección con su fecha y el «Plazo de
subsanación», que no se confunde con el de solicitudes. Un artículo sin un plazo de solicitudes y solo uno detiene la
fuente. Basta la primera página: si su último artículo sigue en plazo, se detiene. Una corrección del plazo cambia el
texto del artículo (la 6.ª de 2026: «Corrección de errores plazo de presentación de solicitudes» y el plazo nuevo).

Título del artículo con `humane_caps` (la mitad vienen en mayúsculas) y «PIT» en mayúsculas. Identificador = número
del artículo de Joomla («711-11-convocatoria-…» → «711»). Ficha = el artículo entero. Sin municipio (también hay
centros en Belmez). Robots.txt cerrado a todos salvo buscadores; el portal lo lee igual a su ritmo (decisión del
usuario). Lectura puntual del 2026-11-16 (0 en plazo: la 11.ª cerró el 09/11) y sondeo de Codex (encargo 40).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..dates import month_number, spanish_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from ..text import humane_caps
from .base import Source

SITE = "https://www.uco.es"
INDEX = SITE + "/investigacion/portal/convocatorias-de-contratos"
COMPANY = "Universidad de Córdoba"
MONTH = r"[a-záéíóú]+"
PERIOD = re.compile(
    rf"Plazo de presentación de solicitudes\s*:\s*desde el\s+(\d{{1,2}})(?:\s+de\s+({MONTH}))?(?:\s+de\s+(\d{{4}}))?"
    rf"\s+(?:al|hasta el)\s+(\d{{1,2}})\s+de\s+({MONTH})\s+de\s+(\d{{4}})", re.I)
ANY_PERIOD = re.compile(r"Plazo de presentación de solicitudes\s*:", re.I)  # no la «Corrección de errores plazo…»
# «30-10-2026 Resolución de 30 de octubre de 2026, …» (la fecha de delante, la de publicación) o, en las tandas
# anteriores a la 4.ª de 2026, solo «Resolución de 20 de febrero de 2026, …».
PUBLISHED = re.compile(rf"^(?:(\d{{2}})-(\d{{2}})-(\d{{4}})\s+)?Resolución de (\d{{1,2}}) de ({MONTH}) de (\d{{4}})\b")
ARTICLE = re.compile(r"^/investigacion/portal/convocatorias-de-contratos/(\d+)-[a-z0-9-]+$")


def _clean(text: str) -> str:
    return " ".join(text.replace("\xa0", " ").split())


def _period(text: str, title: str) -> tuple[str, str]:
    """Primer y último día del plazo de solicitudes; detiene si no hay exactamente uno o no es una fecha válida."""
    found = PERIOD.findall(text)
    if len(found) != 1 or len(ANY_PERIOD.findall(text)) != 1:
        raise SourceLayoutError(f"UCO: «{title}» no trae un plazo de solicitudes y solo uno ({len(found)})")
    day1, month1, year1, day2, month2, year2 = found[0]
    end = spanish_date(day2, month2, year2)
    start = spanish_date(day1, month1 or month2, year1 or year2) if end else None
    if start and not year1 and month1 and month_number(month1) > month_number(month2):  # «desde el 22 de diciembre al 5 de enero de 2027»
        start = spanish_date(day1, month1, int(year2) - 1)
    if not (start and end) or start > end:
        raise SourceLayoutError(f"UCO: plazo ilegible en «{title}» ({text[:160]!r})")
    return start.isoformat(), end.isoformat()


def title_of(text: str) -> str:
    return re.sub(r"\bpit\b", "PIT", humane_caps(text))


def parse_list(html: str) -> list[dict]:
    """Los artículos de la página, en su orden, con el plazo, la publicación y el HTML."""
    articles = BeautifulSoup(html, "html.parser").select('div[itemprop="blogPost"]')
    if not articles:
        raise SourceLayoutError("UCO: la página no tiene artículos de convocatoria")
    found = []
    for article in articles:
        link = article.select_one('h2 a[itemprop="url"][href]')
        path = ARTICLE.match(link["href"]) if link else None
        if not (path and _clean(link.get_text(" "))):
            raise SourceLayoutError(f"UCO: artículo sin enlace o título ({_clean(article.get_text(' '))[:120]!r})")
        title, url = _clean(link.get_text(" ")), urljoin(SITE, link["href"])
        opens_on, deadline = _period(_clean(article.get_text(" ")), title)
        published = None
        for p in article.select("p"):
            if match := PUBLISHED.match(_clean(p.get_text(" "))):
                day, month, year, *words = match.groups()
                signed = spanish_date(*words)
                published = f"{year}-{month}-{day}" if day else signed.isoformat() if signed else None
                break
        header = article.select_one(".page-header")
        if header:
            header.decompose()
        for a in article.select("a[href]"):  # relativos: `sanitize` solo deja los absolutos
            a["href"] = urljoin(url, a["href"])
        found.append({"ref": path.group(1), "url": url, "title": title_of(title),
                      "opens_on": opens_on, "deadline": deadline, "published_on": published,
                      "html": sanitize(article.decode_contents())})
    return found


class UcoSource(Source):
    id = "uco"
    name = COMPANY
    homepage = INDEX
    scope = "Andalucía"
    apply_label = "Ver la convocatoria y cómo presentar la solicitud"

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._articles: dict[str, str] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        articles = parse_list(http.get(INDEX))
        if not deadline_passed(articles[-1]["deadline"], None, now):
            raise SourceLayoutError("UCO: el último artículo de la primera página sigue en plazo")
        self._articles = {}
        offers = []
        for article in articles:
            if deadline_passed(article["deadline"], None, now):
                continue
            self._articles[article["ref"]] = article["html"]
            offers.append(ListedOffer(
                ref=article["ref"], title=article["title"], company=COMPANY, url=article["url"],
                apply_url=article["url"], kind=None, published_on=article["published_on"],
                opens_on=article["opens_on"], deadline=article["deadline"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        html = self._articles.get(offer.ref)
        if html is None:
            found = [a for a in parse_list(http.get(INDEX)) if a["ref"] == offer.ref]
            if not found:
                return None
            html = found[0]["html"]
        return OfferDetail(sections=[{"title": "La convocatoria", "level": 2, "html": html}])
