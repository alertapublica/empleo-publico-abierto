"""Feeds RSS 2.0. Generan las alertas sin pedir ningún dato a quien se suscribe."""
from __future__ import annotations

from datetime import datetime, timezone
from email.utils import format_datetime
from xml.sax.saxutils import escape

from .text import humane_caps

FEED_KINDS = {
    "new": "",
    "republished": "Republicada: ",
    "reopened": "Reabierta: ",
    "deadline_changed": "Plazo modificado: ",
    "positions_changed": "Plazas modificadas: ",
}
LIMIT = 100


def _when(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    return parsed if parsed.tzinfo else parsed.replace(hour=8, tzinfo=timezone.utc)


def offer_items(offers: dict, events: list, offer_url, summary) -> list[dict]:
    items = []
    for event in events:
        offer = offers.get(event["offer"])
        if offer is None or event["kind"] not in FEED_KINDS:
            continue
        original = event["kind"] in ("new", "republished")
        items.append({
            "title": FEED_KINDS[event["kind"]] + offer["title"],
            "link": offer_url(offer),
            "guid": f"{event['offer']}/{event['kind']}/{event['at']}",
            "date": _when(offer.get("published_on") or event["at"]) if original else _when(event["at"]),
            "text": summary(offer),
            "offer": offer,
        })
    return items


def announcement_id(item: dict) -> str:
    """Id de un comunicado en novedades.json y guid del RSS. Lleva el organismo y el título entero:
    dos comunicados del mismo proceso y día pueden empezar igual (Cetarsa: exámenes en dos sedes)."""
    return f"anuncio/{item['source']}/{item['process']}/{item['date']}/{item['title']}"


def announcement_items(announcements: list[dict]) -> list[dict]:
    return [
        {
            "title": f"{humane_caps(item['process'])}: {humane_caps(item['title'])}",
            "link": item["url"],
            "guid": announcement_id(item),
            "date": _when(item["date"] or item["first_seen"]),
            "text": item["title"],
            "offer": None,
            "source": item["source"],
            "process": item["process"],
        }
        for item in announcements if not item.get("baseline")  # los de la primera lectura no son novedad
    ]


def render(title: str, description: str, self_url: str, site_url: str, items: list[dict], now: datetime) -> str:
    chosen = sorted(items, key=lambda item: item["date"], reverse=True)[:LIMIT]
    rows = "".join(
        "<item>"
        f"<title>{escape(item['title'])}</title>"
        f"<link>{escape(item['link'])}</link>"
        f'<guid isPermaLink="false">{escape(item["guid"])}</guid>'
        f"<pubDate>{format_datetime(item['date'])}</pubDate>"
        f"<description>{escape(item['text'])}</description>"
        "</item>\n"
        for item in chosen
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<rss version="2.0" xmlns:atom="http://www.w3.org/2005/Atom"><channel>\n'
        f"<title>{escape(title)}</title><link>{escape(site_url)}</link>"
        f"<description>{escape(description)}</description><language>es</language>"
        f"<lastBuildDate>{format_datetime(now)}</lastBuildDate>"
        f'<atom:link href="{escape(self_url)}" rel="self" type="application/rss+xml"/>\n'
        f"{rows}</channel></rss>\n"
    )
