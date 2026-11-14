"""Compara lo publicado con lo guardado y registra los cambios."""
from __future__ import annotations

import sys
from dataclasses import asdict, replace
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from . import store
from .http import Client
from .model import (LISTING_OR_DETAIL, LIVE_STATES, MADRID, PROCESS_FIELDS, STATE_SCOPE, ListedOffer,
                    SourceLayoutError, deadline_passed, today_madrid)
from .regions import UNKNOWN, location_from_title, place_of, region_of
from .sources import ACTIVE
from .sources.base import Source

DATA = Path("data")
MISSED_RUNS_TO_CLOSE = 3  # (1,5 h con lecturas cada 30 min) un fallo puntual de la web no debe cerrar ofertas
MIN_VISIBLE_RATIO = 0.3  # si desaparece casi todo, lo raro es la lectura
MAX_PORTAL_TRIES = 4
EXTENSION_DAYS = 14  # días tras el plazo en que se sigue mirando si la ficha lo ha ampliado
EXTENSION_TRIES = 3  # lecturas al día de una ficha vencida de la que no se consigue leer el plazo
TRACKED = ("title", "code", "source_title", "category", "url", "apply_url")


def _record(source_id: str, offer: ListedOffer, now: str) -> dict:
    return {
        **asdict(offer),
        "id": f"{source_id}:{offer.ref}",
        "source": source_id,
        "status": "open",
        "first_seen": now,
        "closed_at": None,
        "missed_runs": 0,
        "detail_ok": False,
        "sections": [],
        "location": None,
        "region": None,
        "place": None,
        "department": None,
        "family": None,
        "published_on": offer.published_on,
        "listed_deadline": offer.deadline,  # el plazo según el listado, aunque la ficha lo corrija
        "parent_ref": None,
        "portal_tries": 0,
    }


def _event(events: list, record: dict, kind: str, now: str, **extra) -> None:
    events.append({"offer": record["id"], "kind": kind, "at": now, **extra})


def reconcile(offers: dict, listed: list[ListedOffer], source_id: str, now: datetime) -> list[dict]:
    """Aplica un listado a las ofertas guardadas y devuelve los eventos nuevos."""
    stamp = now.isoformat(timespec="seconds")
    events: list[dict] = []

    open_before = sum(record["status"] == "open" for record in offers.values())
    if open_before >= 20 and len(listed) < open_before * MIN_VISIBLE_RATIO:
        raise SourceLayoutError(
            f"{source_id}: se leen {len(listed)} ofertas y había {open_before} abiertas"
        )

    seen = set()
    for offer in listed:
        seen.add(offer.ref)
        record = offers.get(offer.ref)
        if record is None:
            record = offers[offer.ref] = _record(source_id, offer, stamp)
            _event(events, record, "new", stamp)
            continue
        # Si el listado no trae plazo, vale el guardado (de la ficha): sin él, una oferta vencida que
        # sigue listada se reabriría y cerraría en cada lectura. La hora solo vale si el día no cambia.
        deadline = offer.deadline if offer.deadline is not None else record["deadline"]
        same_day = deadline == record["deadline"]
        hour = offer.deadline_time or (record.get("deadline_time") if same_day else None)
        if record["status"] == "closed" and not deadline_passed(deadline, hour, now):
            record.update(status="open", closed_at=None)
            _event(events, record, "reopened", stamp)
        record["missed_runs"] = 0
        record["published_on"] = record["published_on"] or offer.published_on
        # Si el listado no trae plazo (se lee en la ficha), se conserva el ya guardado. Se compara con
        # el plazo que dio el listado la vez anterior: la ficha puede haberlo corregido (Tragsa).
        if offer.deadline is not None and offer.deadline != record.get("listed_deadline", record["deadline"]):
            _event(events, record, "deadline_changed", stamp,
                   before=record["deadline"], after=offer.deadline)
            record["deadline"] = offer.deadline
            record["deadline_time"] = None  # la hora del plazo anterior no vale para el nuevo
            record["detail_ok"] = False
        if offer.deadline is not None:
            record["listed_deadline"] = offer.deadline
        if offer.positions is not None and offer.positions != record["positions"]:  # o de la ficha
            _event(events, record, "positions_changed", stamp,
                   before=record["positions"], after=offer.positions)
            record["positions"] = offer.positions
            record["detail_ok"] = False
        for field in TRACKED:
            record[field] = getattr(offer, field)
        for field in LISTING_OR_DETAIL:  # si el listado no lo trae, vale lo leído en la ficha
            if getattr(offer, field) is not None:
                record[field] = getattr(offer, field)

    for ref, record in offers.items():
        if record["status"] != "open":
            continue
        expired = deadline_passed(record["deadline"], record.get("deadline_time"), now)
        if ref not in seen:
            record["missed_runs"] += 1
        if expired or record["missed_runs"] >= MISSED_RUNS_TO_CLOSE:
            record.update(status="closed", closed_at=stamp)
            _event(events, record, "closed", stamp)
    return events


def close_expired(offers: dict, events: list, now: datetime) -> None:
    """Cierra las abiertas cuyo plazo ya ha pasado: tras leer las fichas, que pueden traerlo."""
    stamp = now.isoformat(timespec="seconds")
    for record in offers.values():
        if record["status"] == "open" and deadline_passed(record["deadline"], record.get("deadline_time"), now):
            record.update(status="closed", closed_at=stamp)
            _event(events, record, "closed", stamp)


def check_dates(item, fields: tuple[str, ...]) -> None:
    """Una fecha imposible no se guarda: rompería la publicación entera."""
    for name in fields:
        value = getattr(item, name)
        if value:
            try:
                date.fromisoformat(value)
            except ValueError:
                raise SourceLayoutError(f"{name} no es una fecha válida: {value!r}") from None


def _locate(record: dict) -> None:
    title_hint = location_from_title(record["title"])
    # El paréntesis final del título solo vale si es un lugar: en Isdefe es la referencia
    # («2026-T00056») o un número. Lo que ya se guardó así se borra.
    if title_hint and region_of(title_hint) == UNKNOWN:
        if record["location"] == title_hint:
            record["location"] = None
        title_hint = None
    record["region"] = region_of(record["location"], title_hint)
    record["location"] = record["location"] or title_hint


def _extension_due(record: dict, undated: frozenset, now: datetime | None) -> bool:
    """Vencida que sigue en el listado, y el listado no da el plazo: solo la ficha dirá si lo amplían."""
    if now is None or record["ref"] not in undated or not record["deadline"]:
        return False
    if not deadline_passed(record["deadline"], record.get("deadline_time"), now):
        return False
    today = now.astimezone(MADRID).date()
    return (record.get("deadline_checked") != today.isoformat()
            and date.fromisoformat(record["deadline"]) >= today - timedelta(days=EXTENSION_DAYS))


def fetch_details(source: Source, http: Client, offers: dict, events: list, now: datetime | None = None,
                  undated: frozenset = frozenset()) -> None:
    """Lee las fichas pendientes. `undated`: ofertas que esta lectura ha listado sin plazo."""
    checked = extended = unread = 0
    for record in offers.values():
        # Si el plazo solo está en la ficha (Correos, Navantia, BSM), una prórroga no llega por el
        # listado: mientras la oferta siga listada se vuelve a mirar la ficha, una vez al día.
        recheck = _extension_due(record, undated, now)
        if not recheck and (record["status"] != "open" or (
                record["detail_ok"] and record.get("detail_version", 1) == source.detail_version)):
            continue
        # Los registros anteriores a un campo nuevo no lo tienen: vale su valor por defecto.
        listed = ListedOffer(**{field: record[field] for field in ListedOffer.__dataclass_fields__
                                if field in record})
        try:
            detail = source.fetch_detail(http, listed)
            if detail is not None:
                check_dates(detail, ("deadline", "opens_on", "published_before"))
        except Exception as error:  # una ficha mala no debe parar el resto
            print(f"AVISO {record['id']}: {error}", file=sys.stderr)
            detail = None
        if recheck:
            checked += 1
            if detail is None or not detail.deadline:
                # Sin plazo legible no se sabe si lo han ampliado: se reintenta en la lectura
                # siguiente, pero no más de unas pocas veces al día.
                unread += 1
                record["deadline_tries"] = record.get("deadline_tries", 0) + 1
                if record["deadline_tries"] >= EXTENSION_TRIES:
                    record.update(deadline_checked=today_madrid(now), deadline_tries=0)
                continue
            record.update(deadline_checked=today_madrid(now), deadline_tries=0)
            if deadline_passed(detail.deadline, detail.deadline_time, now):
                continue  # sigue vencida: no se toca
            extended += 1
            stamp = now.isoformat(timespec="seconds")
            closed_now = [event for event in events
                          if event["offer"] == record["id"] and event["kind"] == "closed"]
            if closed_now:  # se cerró en esta misma lectura: no llegó a publicarse como cerrada
                events.remove(closed_now[0])
            else:
                _event(events, record, "reopened", stamp)
            _event(events, record, "deadline_changed", stamp, before=record["deadline"], after=detail.deadline)
            # La hora del plazo anterior no vale para el nuevo, y el nuevo se mirará cuando venza.
            record.update(status="open", closed_at=None, deadline_time=None)
            del record["deadline_checked"]
        if detail is None:
            continue
        # Hasta leer la ficha, la ubicación es provisional (la del título, el ámbito de la fuente): manda la de
        # la ficha (58786: «Lleida o Barcelona», no «Cataluña»). En una relectura se queda la guardada.
        if record["detail_ok"]:
            record["location"] = record["location"] or detail.location
        else:
            record["location"] = detail.location or record["location"]
        # Una relectura que llega sin texto no borra el que ya había.
        record.update(sections=detail.sections or (record["sections"] if recheck else []), detail_ok=True,
                      detail_version=source.detail_version, parent_ref=detail.parent_ref)
        record["deadline"] = detail.deadline or record["deadline"]
        for field in LISTING_OR_DETAIL:
            record[field] = getattr(detail, field) or record.get(field)
        if detail.published_before and detail.published_before < (record["published_on"] or "9999"):
            record["published_on"] = detail.published_before
        if detail.parent_ref:
            for event in events:
                if event["offer"] == record["id"] and event["kind"] == "new":
                    event["kind"] = "republished"
        _locate(record)
    if checked:
        print(f"{source.id}: prórrogas: {checked} fichas vencidas consultadas, {extended} con plazo ampliado, "
              f"{unread} sin plazo legible")
        if unread == checked:
            print(f"AVISO {source.id}: no se pudo leer el plazo de ninguna ficha vencida", file=sys.stderr)


def apply_enrichment(source: Source, http: Client, offers: dict) -> None:
    """Completa con `enrich` lo que falta; lo que ya se tiene (de la ficha o de una lectura anterior) se queda.

    La ubicación de la ficha es más precisa y literal que la del portal, y la primera fecha de publicación
    vale más que la que el portal pone al ampliar el plazo.
    """
    pending = [
        record for record in offers.values()
        if record["status"] == "open"
        and any(not record[field] for field in source.enrich_fields)
        and record["portal_tries"] < MAX_PORTAL_TRIES
    ]
    if not pending:
        return
    try:
        extra = source.enrich(http)
    except Exception as error:  # el portal aporta extras: su fallo no bloquea
        print(f"AVISO {source.id}: datos adicionales no disponibles: {error}", file=sys.stderr)
        return
    for record in pending:
        record["portal_tries"] += 1
        values = extra.get(record["ref"])
        if values:
            record.update({key: value for key, value in values.items() if value and not record.get(key)
                           # la ubicación de la ficha manda: la del portal, solo si ya se leyó y no la daba
                           and (key != "location" or record["detail_ok"])})
            _locate(record)


def sync_announcements(source: Source, http: Client, known: dict, now: datetime) -> None:
    """Añade los comunicados nuevos y pone al día los datos de cada proceso."""
    stamp = now.isoformat(timespec="seconds")
    items = source.list_announcements(http)
    if not items:  # sin lectura válida no se puede concluir que un proceso haya terminado
        return
    for item in items:
        check_dates(item, ("date", "deadline"))
    for key in [key for key, record in known.items() if "via" not in record]:
        del known[key]  # formato anterior: la lectura de hoy lo sustituye con todos sus datos
    first_read = not known
    processes = {}
    for position, item in enumerate(items):
        key = f"{source.id}:{item.key}"
        before = known.get(key)
        first_seen = before["first_seen"] if before else stamp
        known[key] = {**asdict(item), "source": source.id, "first_seen": first_seen}
        # Lo que ya estaba en la primera lectura no es novedad, tenga fecha o no: si no, una fuente
        # nueva avisaría de todo su histórico.
        if before.get("baseline") if before else first_read:
            known[key]["baseline"] = True
        if not item.date:
            # Sin fecha de la fuente no se inventa una: se ordena por cuándo se detectó y por su lugar
            # en la web oficial.
            known[key]["position"] = position
        processes[item.process] = known[key]
    for record in known.values():
        current = processes.get(record["process"])
        if current:
            record.update({field: current[field] for field in PROCESS_FIELDS})
        elif record["state"] != "finalizado":
            record.update(state="retirado", deadline=None, deadline_time=None, apply_url=None)
        # La fuente decide por días: pasada la hora de cierre, la inscripción ya no está abierta.
        if record["state"] == "abierto" and deadline_passed(record["deadline"], record.get("deadline_time"), now):
            record.update(state="curso", deadline=None, deadline_time=None, apply_url=None)
        if source.stale_after_days and record["state"] in LIVE_STATES and (
                record.get("baseline") or now - datetime.fromisoformat(record["first_seen"])
                >= timedelta(days=source.stale_after_days)):
            record.update(state="retirado", deadline=None, deadline_time=None, apply_url=None)


def run_source(source: Source, http: Client, data: Path, now: datetime) -> None:
    folder = data / source.id
    offers = store.load(folder / "offers.json", {})
    events = store.load(folder / "events.json", [])
    announcements = store.load(folder / "announcements.json", {})

    for record in offers.values():  # guardadas antes de separar el código del título (una vez)
        if "source_title" not in record:
            record.update(source.labels(record["title"], record["ref"]))
    # El código se separa aquí; si la fuente ya da el título literal aparte, se respeta.
    listed = [offer if offer.source_title else replace(offer, **source.labels(offer.title, offer.ref, offer.code))
              for offer in source.list_offers(http)]
    for offer in listed:
        check_dates(offer, ("deadline", "published_on", "opens_on"))
    new_events = reconcile(offers, listed, source.id, now)
    fetch_details(source, http, offers, new_events, now,
                  frozenset(offer.ref for offer in listed if offer.deadline is None))
    close_expired(offers, new_events, now)
    apply_enrichment(source, http, offers)
    for record in offers.values():
        if record["status"] == "open":
            if record["region"] in (None, UNKNOWN):  # también si la tabla de comunidades ha mejorado
                _locate(record)
            # Sin ubicación en la ficha: en un organismo de una sola comunidad, esa comunidad.
            if not record["location"] and source.scope != STATE_SCOPE:
                record["location"] = source.scope
                _locate(record)
            record["place"] = place_of(record["title"], record["sections"])
    events.extend(new_events)
    store.save(folder / "offers.json", offers)
    store.save(folder / "events.json", events)

    sync_announcements(source, http, announcements, now)
    store.save(folder / "announcements.json", announcements)

    open_count = sum(record["status"] == "open" for record in offers.values())
    print(f"{source.id}: {open_count} abiertas, {len(new_events)} eventos, "
          f"{len(announcements)} anuncios")


def chosen(ids: list[str]) -> list[Source]:
    """Las fuentes pedidas por su id, en el orden del catálogo; sin ids, todas."""
    unknown = set(ids) - {source.id for source in ACTIVE}
    if unknown:
        raise SystemExit(f"Fuentes desconocidas: {', '.join(sorted(unknown))}")
    return [source for source in ACTIVE if not ids or source.id in ids]


def main(ids: list[str] | None = None) -> int:
    now = datetime.now(timezone.utc)
    http = Client()
    failed = False
    for source in chosen(ids or []):
        http.delay = source.delay
        try:
            run_source(source, http, DATA, now)
        except Exception as error:  # cada fuente es independiente
            print(f"ERROR {source.id}: {error}", file=sys.stderr)
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
