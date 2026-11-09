"""Cliente HTTP educado: secuencial, con pausas y reintentos."""
from __future__ import annotations

import gzip
import hashlib
import hmac
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


# Hosts que no responden a las IP de GitHub Actions: se leen por un relay con IP española, firmado con
# RELAY_CLAVE y situado en RELAY_URL (secretos del repo). Cada host tiene que estar también en la lista
# de hosts permitidos del relay.
VIA_RELAY = {"sepi.es", "www.sepi.es"}


def relay(url: str) -> tuple[str, dict[str, str]]:
    """URL y cabeceras con las que leer `url`: por el relay si su host lo pide y hay clave; si no, directa.

    La firma caduca a los 120 s, así que se calcula en cada intento. Solo para GET.
    """
    clave, base = os.environ.get("RELAY_CLAVE"), os.environ.get("RELAY_URL")
    if not (clave and base) or urllib.parse.urlsplit(url).hostname not in VIA_RELAY:
        return url, {}
    ts = str(int(time.time()))
    firma = hmac.new(clave.encode(), f"{ts}\n{url}".encode(), hashlib.sha256).hexdigest()
    return base.rstrip("/") + "/?" + urllib.parse.urlencode({"url": url}), {"x-ts": ts, "x-firma": firma}


class Client:
    def __init__(self, delay: float = DEFAULT_DELAY, retries: int = 3, timeout: float = 60):
        self.delay = delay
        self.retries = retries
        self.timeout = timeout
        self._opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=tls_context()),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()),
        )
        self._last = 0.0

    def get(self, url: str) -> str:
        return self._request(url, None).decode("utf-8", "replace")

    def get_bytes(self, url: str) -> bytes:
        """Contenido sin decodificar (PDF)."""
        return self._request(url, None)

    def post(self, url: str, fields: dict[str, str]) -> str:
        return self._request(url, urllib.parse.urlencode(fields).encode()).decode("utf-8", "replace")

    def _request(self, url: str, data: bytes | None) -> bytes:
        last_error: Exception | None = None
        for attempt in range(self.retries):
            pause = self._last + self.delay - time.monotonic()
            if pause > 0:
                time.sleep(pause)
            target, signed = relay(url) if data is None else (url, {})
            request = urllib.request.Request(target, data=data, headers={**HEADERS, **signed})
            try:
                with self._opener.open(request, timeout=self.timeout) as response:
                    body = response.read()
                    if response.headers.get("Content-Encoding") == "gzip":
                        body = gzip.decompress(body)
                    return body
            except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
                last_error = error
                if isinstance(error, urllib.error.HTTPError) and error.code < 500:
                    break
                time.sleep(5 * 3**attempt)
            finally:
                self._last = time.monotonic()
        raise RuntimeError(f"No se pudo leer {url}: {last_error}")
