"""Avisos a Google con la Indexing API de las fichas con marcado JobPosting.

Compara el manifiesto que escribe `site.build` (huella del marcado de cada ficha y si lleva `noindex`)
con lo último que Google confirmó (`.github/indexing-state.json`) y manda lo pendiente:
- `URL_UPDATED`: la ficha gana el marcado, cambia su huella, o lo pierde y sigue indexable;
- `URL_DELETED`: perdió el marcado y ya lleva `noindex`, o la ficha ya no existe.

Primero las retiradas; luego cambios y altas, como mucho PER_RUN por ejecución. Nunca más de DAILY
peticiones al día del Pacífico, que es como cuenta Google la cuota. Solo un 200 cuenta como hecho, y
el estado se guarda tras cada uno. Diseño en sondeo/plan-indexing-2026-11-27.md.

Uso: GOOGLE_TOKEN=… python -m empleo.indexing [manifiesto] [estado]
"""
from __future__ import annotations

import json
import os
import random
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ENDPOINT = "https://indexing.googleapis.com/v3/urlNotifications:publish"
UPDATED, DELETED = "URL_UPDATED", "URL_DELETED"
DAILY = 200  # peticiones al día por proyecto, de los dos tipos
PER_RUN = 150  # tope propio de cambios y altas por ejecución; las retiradas no esperan por él
MAX_FAILS = 3  # rechazos de la misma URL antes de apartarla hasta que cambie lo que hay que avisar
ATTEMPTS = 3  # intentos por aviso ante un 429 temporal, un 5xx o un fallo de red
TIMEOUT = 30  # segundos por petición
BUDGET = 15 * 60  # segundos para todo el paso (el job entero tiene 30 minutos)
PACIFIC = ZoneInfo("America/Los_Angeles")
UNCERTAIN = "incierta"  # huella de un alta que quizá llegó a Google sin acuse: se repite o se retira


class DailyQuota(Exception):
    """Cuota del día agotada: no se manda nada más hasta el cambio de día en el Pacífico."""


class Fatal(Exception):
    """Fallo que no depende de la URL (token, permisos, Google caído): se para la ejecución."""


class Rejected(Exception):
    """Google rechaza esta URL en concreto."""


def empty_state() -> dict:
    return {"dia": None, "enviados": 0, "urls": {}}


def load_state(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else empty_state()


def save_state(path: Path, state: dict) -> None:
    """Escritura atómica: un corte a mitad no deja el estado roto."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def offer_url(base_url: str):
    """Comprueba que una dirección es una ficha (`site.offer_path`): Google solo admite páginas JobPosting."""
    pattern = re.compile(re.escape(base_url + "ofertas/") + r"[a-z0-9-]+/")
    return lambda url: bool(pattern.fullmatch(url))


def pending(manifest: dict, state: dict) -> tuple[list, list]:
    """Avisos pendientes como (url, tipo, huella): primero las retiradas, luego cambios y altas."""
    is_offer = offer_url(manifest["base_url"])
    fichas = manifest["fichas"]
    removals, updates = [], []
    for url, entry in fichas.items():
        if not is_offer(url):
            continue
        last = state["urls"].get(url, {})
        huella = entry["huella"]
        if huella:
            if last.get("tipo") != UPDATED or last.get("huella") != huella:
                updates.append((url, UPDATED, huella))
        elif last.get("tipo") == UPDATED:
            if entry["noindex"]:
                removals.append((url, DELETED, None))
            elif last.get("huella"):  # perdió el marcado y sigue indexable
                removals.append((url, UPDATED, None))
    for url, last in state["urls"].items():  # avisadas cuya ficha ya no existe (da 404)
        if url not in fichas and is_offer(url) and last.get("tipo") == UPDATED:
            removals.append((url, DELETED, None))
    return removals, updates


def set_aside(state: dict, url: str, kind: str, huella: str | None) -> bool:
    """Google rechazó MAX_FAILS veces este mismo aviso: se aparta hasta que cambie."""
    failed = state["urls"].get(url, {}).get("fallos")
    return bool(failed) and failed["tipo"] == kind and failed["huella"] == huella and failed["veces"] >= MAX_FAILS


def is_daily_quota(code: int, text: str) -> bool:
    text = text.lower()
    return code in (403, 429) and any(mark in text for mark in ("per day", "perday", "dailylimitexceeded"))


def is_rate_limit(code: int, text: str) -> bool:
    """Límite temporal (por minuto): se reintenta con espera."""
    text = text.lower()
    return code == 429 or (code == 403 and any(
        mark in text for mark in ("ratelimitexceeded", "per minute", "perminute")))


def error_message(text: str) -> str:
    try:
        return json.loads(text)["error"]["message"]
    except (ValueError, KeyError, TypeError):
        return text[:200]


class Sender:
    """Manda los avisos de uno en uno, lleva la cuenta del día y guarda el estado tras cada uno."""

    def __init__(self, state: dict, path: Path, token: str, now=lambda: datetime.now(timezone.utc),
                 opener=None, sleep=time.sleep, clock=time.monotonic):
        self.state, self.path, self.token = state, path, token
        self.now, self.opener, self.sleep, self.clock = now, opener or urlopen, sleep, clock
        self.started = clock()
        self.arrived = False
        self.left()

    def left(self) -> int:
        """Peticiones que quedan hoy. El día se mira cada vez: una ejecución puede cruzar la medianoche."""
        today = self.now().astimezone(PACIFIC).date().isoformat()
        if self.state.get("dia") != today:
            self.state["dia"], self.state["enviados"] = today, 0
        return DAILY - self.state["enviados"]

    def out_of_time(self) -> bool:
        return self.clock() - self.started >= BUDGET

    def request(self, url: str, kind: str) -> None:
        """Un aviso, con reintentos. Cada petición cuenta para la cuota: también los reintentos."""
        body = json.dumps({"url": url, "type": kind}).encode("utf-8")
        self.arrived = False  # si alguna petición pudo llegar a Google sin que lo sepamos
        for attempt in range(ATTEMPTS):
            if self.left() <= 0:
                raise DailyQuota()
            if self.out_of_time():
                raise Fatal("se acabó el tiempo del paso")
            self.state["enviados"] += 1
            save_state(self.path, self.state)  # antes de mandarla: mejor contar de más que de menos
            req = Request(ENDPOINT, data=body, method="POST", headers={
                "Authorization": f"Bearer {self.token}", "Content-Type": "application/json"})
            try:
                with self.opener(req, timeout=TIMEOUT) as response:
                    if response.status == 200:
                        return
                    problem = f"respuesta {response.status}"
            except HTTPError as err:
                with err:
                    text = err.read().decode("utf-8", "replace")
                if is_daily_quota(err.code, text):
                    raise DailyQuota() from err
                problem = f"{err.code}: {error_message(text)}"
                if err.code >= 500:
                    self.arrived = True
                elif err.code in (401, 403) and not is_rate_limit(err.code, text):
                    raise Fatal(problem) from err
                elif not is_rate_limit(err.code, text):
                    raise Rejected(problem) from err
            except (URLError, OSError) as err:  # timeout incluido: puede haber llegado, se admite el duplicado
                self.arrived = True
                problem = f"red: {err}"
            else:
                self.arrived = True
            if attempt + 1 < ATTEMPTS:
                self.sleep(2 ** (attempt + 1) + random.uniform(0, 1))
        raise Fatal(f"sin respuesta válida tras {ATTEMPTS} intentos ({problem})")

    def send(self, url: str, kind: str, huella: str | None) -> bool:
        """True si Google lo confirmó. Un rechazo de la URL se anota y no para la ejecución."""
        confirmed = False
        try:
            self.request(url, kind)
            confirmed = True
        except Rejected as err:
            entry = self.state["urls"].setdefault(url, {})
            failed = entry.get("fallos")
            same = failed and failed["tipo"] == kind and failed["huella"] == huella
            entry["fallos"] = {"tipo": kind, "huella": huella, "veces": failed["veces"] + 1 if same else 1,
                               "motivo": str(err)}
        finally:
            if confirmed:
                entry = self.state["urls"].setdefault(url, {})
                entry.pop("fallos", None)
                entry.update(tipo=kind, huella=huella, acuse=self.now().isoformat(timespec="seconds"))
            elif self.arrived:
                # Alta o baja sin acuse que quizá llegó, acabe como acabe: con esta huella la siguiente
                # ejecución repite el alta, retira la ficha si ya no lo tiene o avisa de que reabre.
                self.state["urls"].setdefault(url, {}).update(tipo=UPDATED, huella=UNCERTAIN)
            save_state(self.path, self.state)  # también la cuenta de un intento que acabó mal
        return confirmed


def run(manifest: dict, state_path: Path, token: str, **options) -> tuple[list[str], bool]:
    """Manda lo pendiente. Devuelve las líneas del resumen y si hubo un fallo que señalar."""
    state = load_state(state_path)
    sender = Sender(state, state_path, token, **options)
    save_state(state_path, state)  # existe desde la primera ejecución, aunque no haya nada que mandar
    if not manifest["fichas"]:  # retiraría todo lo avisado
        return ["- Parada: el manifiesto no trae ninguna ficha."], True
    removals, updates = pending(manifest, state)
    wanted = {url: (kind, huella) for url, kind, huella in removals + updates}
    for url, entry in state["urls"].items():  # un rechazo de algo que ya no hay que avisar no cuenta
        if "fallos" in entry and wanted.get(url) != (entry["fallos"]["tipo"], entry["fallos"]["huella"]):
            del entry["fallos"]
    removals = [item for item in removals if not set_aside(state, *item)]
    updates = [item for item in updates if not set_aside(state, *item)][:PER_RUN]
    done = {UPDATED: 0, DELETED: 0}
    rejected, problem, quota = [], None, False
    for url, kind, huella in removals + updates:
        try:
            if sender.send(url, kind, huella):
                done[kind] += 1
            else:
                rejected.append(f"{url} ({state['urls'][url]['fallos']['motivo']})")
        except DailyQuota:
            state["enviados"] = DAILY
            save_state(state_path, state)
            quota = True
            break
        except Fatal as err:
            problem = str(err)
            break
    save_state(state_path, state)
    left_removals, left_updates = pending(manifest, state)
    aside = [item for item in left_removals + left_updates if set_aside(state, *item)]
    lines = [
        f"- Confirmados: {done[UPDATED]} `URL_UPDATED` y {done[DELETED]} `URL_DELETED`.",
        f"- Pendientes: {len(left_removals)} retiradas y {len(left_updates)} cambios o altas.",
        f"- Cuota del día ({state['dia']}, hora del Pacífico): {min(state['enviados'], DAILY)} de {DAILY}"
        + (" (agotada)." if quota or state["enviados"] >= DAILY else "."),
    ]
    if aside:
        lines.append(f"- Apartadas tras {MAX_FAILS} rechazos: {len(aside)}.")
    lines += [f"- Rechazada: {item}" for item in rejected]
    if problem:
        lines.append(f"- Parada: {problem}")
    return lines, bool(problem or rejected)


def main() -> int:
    manifest_path = Path(sys.argv[1] if len(sys.argv) > 1 else "jobposting.json")
    state_path = Path(sys.argv[2] if len(sys.argv) > 2 else ".github/indexing-state.json")
    token = os.environ.get("GOOGLE_TOKEN")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if not token:
        print("Sin GOOGLE_TOKEN: no se avisa a Google.")
        return 0
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        lines, failed = run(manifest, state_path, token)
    except Exception as err:  # la web ya está publicada: se avisa y se sigue
        lines, failed = [f"- Parada: {type(err).__name__}: {err}"], True
    text = "### Avisos a Google (Indexing API)\n\n" + "\n".join(lines) + "\n"
    print(text)
    if summary:
        with open(summary, "a", encoding="utf-8") as f:
            f.write(text)
    if failed:  # un rechazo o una parada: aviso visible, sin poner la ejecución en rojo
        print(f"::warning title=Indexing API::{lines[-1][2:]}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
