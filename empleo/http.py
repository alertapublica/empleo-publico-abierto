"""Cliente HTTP educado: secuencial, con pausas y reintentos."""
from __future__ import annotations

import gzip
import hashlib
import hmac
import json
import math
import http.cookiejar
import os
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# Sin URL y con Accept: el WAF de ADIF rechaza lo contrario.
HEADERS = {
    "User-Agent": "empleo-publico-abierto/0.1",
    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
    "Accept-Encoding": "gzip",
}


DEFAULT_DELAY = 2.0  # segundos entre peticiones, salvo que el portal pida más
# Intermedios que algunos servidores oficiales no envían bien (ver certs/README.md).
CERTS = Path(__file__).parent / "certs"


def tls_context() -> ssl.SSLContext:
    """Verificación TLS completa: almacén del sistema más los intermedios de `certs/`."""
    context = ssl.create_default_context()
    for pem in sorted(CERTS.glob("*.pem")):
        context.load_verify_locations(cafile=pem)
    return context


# Hosts que no responden a las IP de GitHub Actions (EE. UU.): se leen por el Worker de Cloudflare de relay/,
# que sale por Madrid, con GET y POST y las cookies de la sesión. Secretos RELAY_CF_URL y RELAY_CF_CLAVE.
# Tragsa (portal de candidatos, solo en el puerto 8443): timeout. SEPI: no responde. EFE: 403. Fundación de
# la Universidad de La Rioja: 429. Cada host tiene que estar también en ORIGENES de relay/src/index.js.
VIA_RELAY_CF = {"rrhhcandidato.tragsa.es", "www.sepi.es", "agenciaefe.es", "www.agenciaefe.es", "fundacion.unirioja.es"}


def relay_cf(url: str, data: bytes | None) -> tuple[str, dict[str, str]] | None:
    """URL y cabeceras firmadas para leer `url` por el Worker, o None si no le toca o falta la clave.

    La firma cubre hora, método, URL y cuerpo, y caduca a los 120 s: se calcula en cada intento.
    """
    clave, base = os.environ.get("RELAY_CF_CLAVE"), os.environ.get("RELAY_CF_URL")
    if not (clave and base) or urllib.parse.urlsplit(url).hostname not in VIA_RELAY_CF:
        return None
    ts = str(int(time.time()))
    method = "GET" if data is None else "POST"
    signed = f"{ts}\n{method}\n{url}\n".encode() + (data or b"")
    firma = hmac.new(clave.encode(), signed, hashlib.sha256).hexdigest()
    return base.rstrip("/") + "/?" + urllib.parse.urlencode({"url": url}), {"x-ts": ts, "x-firma": firma}


def _origin(url: str) -> str:
    """Esquema, host y puerto: el Worker no sigue redirecciones a otro origen, así que sus cookies son de este."""
    parts = urllib.parse.urlsplit(url)
    port = parts.port if parts.port not in (None, {"https": 443, "http": 80}.get(parts.scheme)) else None
    return f"{parts.scheme}://{parts.hostname}" + (f":{port}" if port else "")


class OutOfTime(BaseException):
    """Se acabó el plazo de la fuente o de la lectura. Hereda de BaseException para que ningún
    `except Exception` (una ficha mala, datos adicionales) la trague: corta la fuente entera."""


class Client:
    def __init__(self, delay: float = DEFAULT_DELAY, retries: int = 3, timeout: float = 60,
                 deadline: float | None = None):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self.deadline = deadline  # time.monotonic() desde el que no se pide nada más
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=tls_context()),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        self.last = 0.0  # fin de la última petición (monotonic)
        self.attempts = 0  # peticiones hechas, contando reintentos (para el registro de la ingesta)
        self.failures = 0
        # Cookies de las sesiones que pasan por el Worker, por origen del destino: no son del dominio del
        # Worker y no van al CookieJar. Un mismo Client lee varios organismos: no se mezclan.
        self._relay_cookies: dict[str, dict[str, str]] = {}

    def get(self, url: str) -> str:
        return self._request(url, None).decode("utf-8", "replace")

    def get_bytes(self, url: str) -> bytes:
        """Contenido sin decodificar (PDF)."""
        return self._request(url, None)

    def post(self, url: str, fields: dict[str, str]) -> str:
        return self._request(url, urllib.parse.urlencode(fields).encode()).decode("utf-8", "replace")

    def _left(self) -> float:
        return math.inf if self.deadline is None else self.deadline - time.monotonic()

    def _wait(self, seconds: float, url: str) -> None:
        """Espera, salvo que al acabar ya no quede plazo para pedir nada."""
        if max(seconds, 0) >= self._left():
            raise OutOfTime(f"sin tiempo para leer {url}")
        if seconds > 0:
            time.sleep(seconds)

    def _request(self, url: str, data: bytes | None) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            self._wait(self.last + self.delay - time.monotonic(), url)
            via_cf = relay_cf(url, data)
            target, signed = via_cf or (url, {})
            jar = self._relay_cookies.setdefault(_origin(url), {}) if via_cf else {}
            if jar:
                signed["x-relay-cookie"] = "; ".join(f"{k}={v}" for k, v in jar.items())
            request = urllib.request.Request(target, data=data, headers={**HEADERS, **signed})
            self.attempts += 1
            try:
                # Por operación de socket: una respuesta que llega a goteo puede pasarse algo del plazo.
                with self._opener.open(request, timeout=min(self.timeout, self._left())) as response:
                    if via_cf:  # lista JSON de las Set-Cookie del destino, en orden (relay/src/index.js)
                        for line in json.loads(response.headers.get("x-relay-set-cookies") or "[]"):
                            name, _, value = line.split(";")[0].partition("=")
                            if name.strip():
                                jar[name.strip()] = value.strip()
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_error = error
                self.failures += 1
                if isinstance(error, urllib.error.HTTPError) and error.code < 500:
                    break
                if attempt + 1 < self.retries:  # tras el último intento no hay nada que esperar
                    self._wait(5 * 3**attempt, url)
            finally:
                self.last = time.monotonic()
        raise RuntimeError(f"No se pudo leer {url}: {last_error}")
