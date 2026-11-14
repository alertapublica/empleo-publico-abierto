"""Relay de IP española: firma, a qué hosts se aplica y cómo se comportan los errores.

Un servidor local hace de relay.php: comprueba la firma igual que él
(HMAC-SHA256 de ts + "\\n" + url, en las cabeceras x-ts y x-firma).
"""
import email.message
import hashlib
import hmac
import io
import json
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


PORTAL_TRAGSA = "https://rrhhcandidato.tragsa.es:8443/psc/portalrh/EMPLOYEE/HRMS/c/X.GBL?Page=A"


class FakeWorker(BaseHTTPRequestHandler):
    """Hace de relay/ (Worker de Cloudflare): firma de hora, método, URL y cuerpo; cookies en cabeceras propias."""
    seen: list[dict] = []
    legacy_only = False  # Worker anterior: solo la cabecera repetida, sin la lista JSON

    def _answer(self, method):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        url = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)["url"][0]
        ts = self.headers["x-ts"]
        expected = hmac.new(CLAVE.encode(), f"{ts}\n{method}\n{url}\n".encode() + body, hashlib.sha256).hexdigest()
        self.seen.append({"method": method, "url": url, "body": body, "cookie": self.headers["x-relay-cookie"]})
        ok = hmac.compare_digest(expected, self.headers["x-firma"] or "")
        self.send_response(200 if ok else 403)
        if ok:
            # Como el Worker: la lista JSON, en orden (PAGINA cambia dentro de la misma respuesta, como en una
            # redirección, y FIJA lleva una coma en Expires), y la cabecera antigua, una por cookie.
            cookies = ["PAGINA=0; path=/", f"PAGINA={len(self.seen)}; path=/; HttpOnly",
                       "FIJA=1; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Secure"]
            if not self.legacy_only:
                self.send_header("x-relay-set-cookies", json.dumps(cookies))
            for cookie in cookies:
                self.send_header("x-relay-set-cookie", cookie)
        self.end_headers()
        self.wfile.write(f"{method} {url} {body.decode()}".encode())

    def do_GET(self):
        self._answer("GET")

    def do_POST(self):
        self._answer("POST")

    def log_message(self, *_):
        pass


class RelayCloudflare(unittest.TestCase):
    def setUp(self):
        self.server = HTTPServer(("127.0.0.1", 0), FakeWorker)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        FakeWorker.seen = []
        FakeWorker.legacy_only = False
        base = f"http://127.0.0.1:{self.server.server_port}"
        env = mock.patch.dict("os.environ", {"RELAY_CF_CLAVE": CLAVE, "RELAY_CF_URL": base})
        env.start()
        self.addCleanup(env.stop)

    def test_get_y_post_del_portal_de_tragsa_con_firma_y_cookies(self):
        client = http.Client(delay=0)
        self.assertEqual(client.get(PORTAL_TRAGSA), f"GET {PORTAL_TRAGSA} ")
        self.assertEqual(client.post(PORTAL_TRAGSA, {"ICAction": "abajo"}), f"POST {PORTAL_TRAGSA} ICAction=abajo")
        self.assertEqual([s["method"] for s in FakeWorker.seen], ["GET", "POST"])
        self.assertIsNone(FakeWorker.seen[0]["cookie"])
        # La segunda petición lleva las cookies que devolvió la primera, sin atributos.
        self.assertEqual(FakeWorker.seen[1]["cookie"], "PAGINA=1; FIJA=1")

    def test_firma_mala_no_se_reintenta(self):
        with mock.patch.dict("os.environ", {"RELAY_CF_CLAVE": "otra"}):
            with self.assertRaisesRegex(RuntimeError, "403"):
                http.Client(delay=0).get(PORTAL_TRAGSA)
        self.assertEqual(len(FakeWorker.seen), 1)

    def test_con_un_worker_anterior_tambien_guarda_las_cookies(self):
        FakeWorker.legacy_only = True
        client = http.Client(delay=0)
        client.get(PORTAL_TRAGSA)
        client.post(PORTAL_TRAGSA, {"ICAction": "abajo"})
        self.assertEqual(FakeWorker.seen[1]["cookie"], "PAGINA=1; FIJA=1")

    def test_la_cabecera_de_cookies_solo_vale_si_viene_del_worker(self):
        client = http.Client(delay=0)

        class Respuesta(io.BytesIO):
            headers = email.message.Message()
            headers["x-relay-set-cookies"] = json.dumps(["INTRUSA=1"])
            headers["x-relay-set-cookie"] = "OTRA=1"

        with mock.patch.object(client._opener, "open", return_value=Respuesta(b"ok")):
            self.assertEqual(client.get("https://www.tragsa.es/"), "ok")
        self.assertEqual(client._relay_cookies, {})

    def test_los_demas_hosts_no_van_por_el_worker(self):
        self.assertIsNone(http.relay_cf("https://www.tragsa.es/es/equipo/trabaja-con-nosotros", None))
        self.assertIsNone(http.relay_cf(SEPI, None))

    def test_sin_clave_va_directo(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(http.relay_cf(PORTAL_TRAGSA, None))


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
