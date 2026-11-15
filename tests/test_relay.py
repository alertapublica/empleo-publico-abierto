"""Worker de relay/ (salida por Madrid): firma, a qué hosts se aplica, cookies y errores.

Un servidor local hace de Worker: comprueba la firma igual que él (HMAC-SHA256 de hora, método, URL y
cuerpo, en las cabeceras x-ts y x-firma) y devuelve las cookies del destino en x-relay-set-cookies.
"""
import email.message
import hashlib
import hmac
import io
import json
import shutil
import subprocess
import threading
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest import mock

from empleo import http, sondeo

CLAVE = "clave-de-prueba"
SEPI = "https://www.sepi.es/es/empleo-publico"
PORTAL_TRAGSA = "https://rrhhcandidato.tragsa.es:8443/psc/portalrh/EMPLOYEE/HRMS/c/X.GBL?Page=A"
WORKER = Path(__file__).parent.parent / "relay" / "src" / "index.js"


class FakeWorker(BaseHTTPRequestHandler):
    """Hace de relay/ (Worker de Cloudflare): firma de hora, método, URL y cuerpo; cookies en cabeceras propias."""
    seen: list[dict] = []
    answers: list[int] = []  # estados forzados, en orden (522: el Worker no conectó con el destino)

    def _answer(self, method):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        url = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)["url"][0]
        ts = self.headers["x-ts"]
        expected = hmac.new(CLAVE.encode(), f"{ts}\n{method}\n{url}\n".encode() + body, hashlib.sha256).hexdigest()
        self.seen.append({"method": method, "url": url, "body": body, "cookie": self.headers["x-relay-cookie"]})
        status = self.answers.pop(0) if self.answers else 200
        if not hmac.compare_digest(expected, self.headers["x-firma"] or ""):
            status = 403
        self.send_response(status)
        if status == 200:
            # Como el Worker: la lista JSON, en orden (PAGINA cambia dentro de la misma respuesta, como en una
            # redirección, y FIJA lleva una coma en Expires).
            cookies = ["PAGINA=0; path=/", f"PAGINA={len(self.seen)}; path=/; HttpOnly",
                       "FIJA=1; Expires=Wed, 21 Oct 2026 07:28:00 GMT; Secure"]
            self.send_header("x-relay-set-cookies", json.dumps(cookies))
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
        FakeWorker.seen, FakeWorker.answers = [], []
        base = f"http://127.0.0.1:{self.server.server_port}"
        env = mock.patch.dict("os.environ", {"RELAY_CF_CLAVE": CLAVE, "RELAY_CF_URL": base})
        env.start()
        self.addCleanup(env.stop)
        sleep = mock.patch.object(http.time, "sleep")
        sleep.start()
        self.addCleanup(sleep.stop)

    def test_get_y_post_del_portal_de_tragsa_con_firma_y_cookies(self):
        client = http.Client(delay=0)
        self.assertEqual(client.get(PORTAL_TRAGSA), f"GET {PORTAL_TRAGSA} ")
        self.assertEqual(client.post(PORTAL_TRAGSA, {"ICAction": "abajo"}), f"POST {PORTAL_TRAGSA} ICAction=abajo")
        self.assertEqual([s["method"] for s in FakeWorker.seen], ["GET", "POST"])
        self.assertIsNone(FakeWorker.seen[0]["cookie"])
        # La segunda petición lleva las cookies que devolvió la primera, sin atributos.
        self.assertEqual(FakeWorker.seen[1]["cookie"], "PAGINA=1; FIJA=1")

    def test_sepi_efe_y_la_rioja_van_por_el_worker(self):
        for url in (SEPI, "https://agenciaefe.es/empleo-efe-temporal/", "https://www.agenciaefe.es/empleo-efe-indefinido/",
                    "https://fundacion.unirioja.es/transparencia/ofertas-empleo"):
            self.assertEqual(http.Client(delay=0).get(url), f"GET {url} ")
        self.assertEqual(len(FakeWorker.seen), 4)

    def test_las_cookies_de_un_organismo_no_van_a_otro(self):
        client = http.Client(delay=0)
        client.get(PORTAL_TRAGSA)
        client.get(SEPI)
        client.post(PORTAL_TRAGSA, {"ICAction": "abajo"})
        client.get(SEPI)
        self.assertEqual([s["cookie"] for s in FakeWorker.seen], [None, None, "PAGINA=1; FIJA=1", "PAGINA=2; FIJA=1"])

    def test_firma_nueva_en_cada_intento(self):
        FakeWorker.answers = [522]  # el Worker no conectó con SEPI: se reintenta con otra firma
        with mock.patch.object(http, "relay_cf", wraps=http.relay_cf) as relay_cf:
            self.assertEqual(http.Client(delay=0).get(SEPI), f"GET {SEPI} ")
        self.assertEqual(relay_cf.call_count, 2)
        self.assertEqual(len(FakeWorker.seen), 2)

    def test_firma_mala_no_se_reintenta(self):
        with mock.patch.dict("os.environ", {"RELAY_CF_CLAVE": "otra"}):
            with self.assertRaisesRegex(RuntimeError, "403"):
                http.Client(delay=0).get(PORTAL_TRAGSA)
        self.assertEqual(len(FakeWorker.seen), 1)

    def test_la_cabecera_de_cookies_solo_vale_si_viene_del_worker(self):
        client = http.Client(delay=0)

        class Respuesta(io.BytesIO):
            headers = email.message.Message()
            headers["x-relay-set-cookies"] = json.dumps(["INTRUSA=1"])

        with mock.patch.object(client._opener, "open", return_value=Respuesta(b"ok")):
            self.assertEqual(client.get("https://www.tragsa.es/"), "ok")
        self.assertEqual(client._relay_cookies, {})

    def test_el_sondeo_tambien_y_no_enseña_el_worker(self):
        result = sondeo.fetch(SEPI)
        self.assertEqual((result["estado"], result["via"], result["url_final"]), (200, "relay", SEPI))
        self.assertEqual(FakeWorker.seen[0]["url"], SEPI)


class Directa(unittest.TestCase):
    def test_sin_clave_va_directa(self):
        with mock.patch.dict("os.environ", {}, clear=True):
            self.assertIsNone(http.relay_cf(PORTAL_TRAGSA, None))
            self.assertIsNone(http.relay_cf(SEPI, None))

    def test_otros_hosts_van_directos(self):
        with mock.patch.dict("os.environ", {"RELAY_CF_CLAVE": CLAVE, "RELAY_CF_URL": "https://relay.example"}):
            for url in ("https://www.tragsa.es/es/equipo/trabaja-con-nosotros", "https://www.sepides.es/empleo",
                        "https://sepi.es.example.com/", "https://sepi.es/es/empleo-publico"):
                self.assertIsNone(http.relay_cf(url, None), url)
            self.assertIsNotNone(http.relay_cf(SEPI, None))


class MismaListaQueElWorker(unittest.TestCase):
    def test_los_hosts_del_cliente_son_los_origenes_del_worker_y_todos_https(self):
        node = shutil.which("node") or "node"  # sin node, falla: no se salta en silencio
        # El Set exportado tal cual lo ve el Worker, no una lectura del texto del fichero.
        code = f"import({json.dumps(WORKER.as_uri())}).then(m => console.log(JSON.stringify([...m.ORIGENES])))"
        origenes = json.loads(subprocess.run([node, "-e", code], capture_output=True, text=True, check=True).stdout)
        self.assertTrue(origenes)
        self.assertTrue(all(urllib.parse.urlsplit(o).scheme == "https" for o in origenes), origenes)
        self.assertEqual({urllib.parse.urlsplit(o).hostname for o in origenes}, http.VIA_RELAY_CF)


if __name__ == "__main__":
    unittest.main()
