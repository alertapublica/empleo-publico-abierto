"""Relay de IP española: firma, a qué hosts se aplica y cómo se comportan los errores.

Un servidor local hace de relay.php: comprueba la firma igual que él
(HMAC-SHA256 de ts + "\\n" + url, en las cabeceras x-ts y x-firma).
"""
import hashlib
import hmac
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest import mock

from empleo import http, sondeo

CLAVE = "clave-de-prueba"
SEPI = "https://www.sepi.es/es/empleo-publico"


class FakeRelay(BaseHTTPRequestHandler):
    answers: list[int] = []
    seen: list[dict] = []

    def do_GET(self):
        query = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        url, ts, firma = query["url"][0], self.headers["x-ts"], self.headers["x-firma"]
        expected = hmac.new(CLAVE.encode(), f"{ts}\n{url}".encode(), hashlib.sha256).hexdigest()
        self.seen.append({"path": self.path, "url": url, "ts": ts})
        status = self.answers.pop(0) if self.answers else 200
        if not hmac.compare_digest(expected, firma or ""):
            status = 403
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if status == 200:
            self.send_header("x-relay-ms", "12")
        self.end_headers()
        self.wfile.write(f"por el relay: {url}".encode())

    def log_message(self, *_):
        pass


class Relay(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), FakeRelay)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        FakeRelay.answers, FakeRelay.seen = [], []
        base = f"http://127.0.0.1:{self.server.server_port}/relay.php"
        env = mock.patch.dict("os.environ", {"RELAY_CLAVE": CLAVE, "RELAY_URL": base})
        env.start()
        self.addCleanup(env.stop)
        sleep = mock.patch.object(http.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_sepi_va_por_el_relay_con_firma(self):
        body = http.Client(delay=0).get(SEPI)
        self.assertEqual(body, f"por el relay: {SEPI}")
        self.assertEqual(FakeRelay.seen[0]["url"], SEPI)
        self.assertTrue(FakeRelay.seen[0]["path"].startswith("/relay.php/?url="))

    def test_efe_va_por_el_relay(self):
        for url in ("https://agenciaefe.es/empleo-efe-temporal/", "https://www.agenciaefe.es/empleo-efe-indefinido/"):
            self.assertEqual(http.Client(delay=0).get(url), f"por el relay: {url}")

    def test_firma_nueva_en_cada_intento(self):
        FakeRelay.answers = [502]  # fallo de red del relay: se reintenta
        with mock.patch.object(http, "relay", wraps=http.relay) as relay:
            body = http.Client(delay=0).get(SEPI)
        self.assertEqual(body, f"por el relay: {SEPI}")
        self.assertEqual(relay.call_count, 2)
        self.assertEqual(len(FakeRelay.seen), 2)

    def test_firma_mala_no_se_reintenta(self):
        with mock.patch.dict("os.environ", {"RELAY_CLAVE": "otra"}):
            with self.assertRaisesRegex(RuntimeError, "403"):
                http.Client(delay=0).get(SEPI)
        self.assertEqual(len(FakeRelay.seen), 1)

    def test_el_sondeo_tambien_y_no_enseña_el_relay(self):
        result = sondeo.fetch(SEPI)
        self.assertEqual((result["estado"], result["via"], result["url_final"]), (200, "relay", SEPI))


class Directa(unittest.TestCase):
    def test_sin_clave_va_directa(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertEqual(http.relay(SEPI), (SEPI, {}))

    def test_otros_hosts_van_directos(self):
        with mock.patch.dict("os.environ", {"RELAY_CLAVE": CLAVE, "RELAY_URL": "http://relay.example/r.php"}):
            self.assertEqual(http.relay("https://www.sepides.es/empleo"), ("https://www.sepides.es/empleo", {}))
            self.assertEqual(http.relay("https://sepi.es.example.com/"), ("https://sepi.es.example.com/", {}))

    def test_post_nunca_va_por_el_relay(self):
        sent = []
        client = http.Client(delay=0)

        def capture(request, timeout):
            sent.append(request.full_url)
            raise http.urllib.error.HTTPError(request.full_url, 404, "x", {}, None)

        with mock.patch.dict("os.environ", {"RELAY_CLAVE": CLAVE, "RELAY_URL": "http://relay.example/r.php"}), \
                mock.patch.object(client._opener, "open", capture):
            with self.assertRaises(RuntimeError):
                client.post(SEPI, {"a": "b"})
        self.assertEqual(sent, [SEPI])


if __name__ == "__main__":
    unittest.main()
