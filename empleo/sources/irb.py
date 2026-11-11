"""IRB Barcelona (Institute for Research in Biomedicine).

Portal de Teamtailor (`recruitment.irbbarcelona.org`), en inglés. La portada lista las ofertas
publicadas (9 el 2026-11-11) con el título recortado y enlace a la ficha (`/jobs/<id>-<texto>`).

La ficha lleva un JSON-LD `JobPosting` con el título entero («Research Assistant (Ref.
LAB/26/17)»), la descripción en HTML y la localidad, pero sin `validThrough`: el cierre va en la
descripción («Deadline for applications : 23/11/2026 (If no suitable candidate is found, the deadline
will be extended)»), igual que las plazas («Number of positions available : 1»). Es oferta la que
tiene ese cierre sin vencer; si lo amplían, cambia el texto. Una petición por oferta del listado.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timezone

from bs4 import BeautifulSoup

from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed
from ..sanitize import sanitize
from .base import Source

SITE = "https://recruitment.irbbarcelona.org"
PAGE = SITE + "/"
COMPANY = "IRB Barcelona"
JOB = re.compile(r"^https://recruitment\.irbbarcelona\.org/jobs/(\d+)-")
DEADLINE = re.compile(r"Deadline for applications\s*:\s*(\d{1,2})/(\d{1,2})/(\d{4})", re.I)
# Aviso de Teamtailor sin vacantes (sin ver todavía en IRB): sin él ni lista, la fuente se detiene.
EMPTY = re.compile(r"no (?:job openings|open positions|current openings)|there are no (?:jobs|open)", re.I)
POSITIONS = re.compile(r"Number of positions available\s*:\s*(\d+)", re.I)


def parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    container = soup.select_one("#jobs_list_container")
    if container is None:
        if EMPTY.search(" ".join(soup.get_text(" ").split())):
            return []
        raise SourceLayoutError("IRB Barcelona: no se encuentra la lista de ofertas ni el aviso de que no hay")
    found = {}
    for link in container.find_all("a", href=True):
        job = JOB.match(link["href"])
        if job and job.group(1) not in found:
            found[job.group(1)] = {"ref": job.group(1), "url": link["href"]}
    if not found:
        raise SourceLayoutError("IRB Barcelona: la lista de ofertas no tiene enlaces a fichas")
    return list(found.values())


def parse_job(html: str) -> dict:
    posting = None
    for script in BeautifulSoup(html, "html.parser").find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
        except json.JSONDecodeError:
            continue
        for item in data if isinstance(data, list) else [data]:
            if isinstance(item, dict) and item.get("@type") == "JobPosting":
                posting = item
    if posting is None or not posting.get("title") or not posting.get("description"):
        raise SourceLayoutError("IRB Barcelona: ficha sin JobPosting")
    text = " ".join(BeautifulSoup(posting["description"], "html.parser").get_text(" ").split())
    deadline, seats = DEADLINE.search(text), POSITIONS.search(text)
    places = posting.get("jobLocation") or [{}]
    locality = ((places[0] if isinstance(places, list) else places).get("address") or {}).get("addressLocality")
    return {
        "title": " ".join(posting["title"].split()),
        "deadline": date(int(deadline.group(3)), int(deadline.group(2)), int(deadline.group(1))).isoformat()
        if deadline else None,
        "positions": int(seats.group(1)) if seats else None,
        "published_on": (posting.get("datePosted") or "")[:10] or None,
        "location": locality, "description": sanitize(posting["description"]),
    }


class IrbSource(Source):
    id = "irb"
    name = "IRB Barcelona"
    homepage = PAGE
    scope = "Cataluña"
    text_lang = "en"
    apply_label = "Ver la oferta y presentar la candidatura en la web oficial"
    title_code = re.compile(r"(?P<title>.+?)\s*\(Ref\.\s*(?P<code>[A-Z]+/\d+/\d+)\)")

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._jobs: dict[str, dict] = {}

    def list_offers(self, http: Client) -> list[ListedOffer]:
        now = self._now or datetime.now(timezone.utc)
        offers = []
        for row in parse_page(http.get(PAGE)):
            job = parse_job(http.get(row["url"]))
            if job["deadline"] is None or deadline_passed(job["deadline"], None, now):
                continue
            self._jobs[row["ref"]] = job
            offers.append(ListedOffer(
                ref=row["ref"], title=job["title"], company=COMPANY, url=row["url"], apply_url=row["url"], kind=None,
                positions=job["positions"], deadline=job["deadline"], published_on=job["published_on"],
            ))
        return offers

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        job = self._jobs.get(offer.ref) or parse_job(http.get(offer.url))
        return OfferDetail(location=job["location"],
                           sections=[{"title": "The position", "level": 2, "html": job["description"]}])
