"""Cliente HTTP: los intermedios añadidos, la pausa de cada fuente y los grupos por servidor."""
import contextlib
import io
import ssl
import time
import unittest
from unittest import mock

from empleo import http, ingest, sources


def decoded(pem):
    return ssl._ssl._test_decode_cert(str(pem))


def fake(id, delay=0.0, group=None):
    return type("S", (), {"id": id, "delay": delay, "concurrency_group": group})()


def name(fields):
    return dict(pair for rdn in fields for pair in rdn).get("commonName")


class Certificados(unittest.TestCase):
    def test_solo_intermedios_nunca_raices(self):
        pems = sorted(http.CERTS.glob("*.pem"))
        self.assertTrue(pems)
        for pem in pems:
            cert = decoded(pem)
            self.assertNotEqual(name(cert["subject"]), name(cert["issuer"]), pem.name)

    def test_el_cliente_los_carga_ademas_del_sistema(self):
        loaded = {name(c["subject"]) for c in http.tls_context().get_ca_certs()}
        self.assertIn("DigiCert Global G2 TLS RSA SHA256 2020 CA1", loaded)
        self.assertIn("Sectigo Public Server Authentication CA DV R36", loaded)
        self.assertEqual(http.tls_context().verify_mode, ssl.CERT_REQUIRED)


class Pausa(unittest.TestCase):
    def test_cada_fuente_lee_con_su_pausa(self):
        slow = fake("lenta", 10.0)
        normal = fake("normal", http.DEFAULT_DELAY)
        seen = []
        with mock.patch.object(ingest, "ACTIVE", [slow, normal]), \
                mock.patch.object(ingest, "run_source", lambda s, client, *_: seen.append((s.id, client.delay))):
            ingest.main()
        self.assertEqual(seen, [("lenta", 10.0), ("normal", http.DEFAULT_DELAY)])


class Reintentos(unittest.TestCase):
    def test_no_espera_tras_el_ultimo_intento(self):
        client = http.Client(delay=0)
        client._opener = mock.Mock(open=mock.Mock(side_effect=http.urllib.error.URLError("caída")))
        with mock.patch.object(http.time, "sleep") as sleep, self.assertRaisesRegex(RuntimeError, "caída"):
            client.get("https://example.org/")
        self.assertEqual([c.args for c in sleep.call_args_list], [(5,), (15,)])
        self.assertEqual((client.attempts, client.failures), (3, 3))


class Registro(unittest.TestCase):
    def test_inicio_y_fin_de_cada_fuente_tambien_si_falla(self):
        sources = [fake("rota"), fake("sana")]

        def run(source, client, *_):
            client.attempts += 2
            if source.id == "rota":
                client.failures += 1
                raise RuntimeError("No se pudo leer")

        out = io.StringIO()
        with mock.patch.object(ingest, "ACTIVE", sources), mock.patch.object(ingest, "run_source", run), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ingest.main(), 1)
        expected = ["INICIO rota", r"FIN rota error \d+ s, 2 peticiones, 1 fallidas",
                    "INICIO sana", r"FIN sana bien \d+ s, 2 peticiones, 0 fallidas"]
        lines = out.getvalue().splitlines()
        self.assertEqual(len(lines), len(expected), lines)
        for line, pattern in zip(lines, expected):
            self.assertRegex(line, f"^{pattern}$")


class Grupos(unittest.TestCase):
    def test_por_servidor_en_orden_de_catalogo(self):
        a, b, c, d = fake("a", group="g"), fake("b"), fake("c", group="g"), fake("d")
        self.assertEqual(ingest.by_server([a, b, c, d]), [[a, c], [b], [d]])

    def test_dentro_del_grupo_se_respeta_la_pausa_y_entre_grupos_no(self):
        sources = [fake("lenta", 10.0, "g"), fake("normal", 2.0, "g"), fake("otra", 2.0)]
        seen = []

        def run(source, client, *_):
            seen.append((source.id, client.attempts))  # un Client nuevo por fuente
            client.attempts += 1
            client.last = time.monotonic()

        with mock.patch.object(ingest, "ACTIVE", sources), mock.patch.object(ingest, "run_source", run), \
                mock.patch.object(ingest.time, "sleep") as sleep, contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ingest.main(), 0)
        self.assertEqual(seen, [("lenta", 0), ("normal", 0), ("otra", 0)])
        self.assertEqual(len(sleep.call_args_list), 1)
        self.assertGreater(sleep.call_args.args[0], 9)  # la mayor de las dos pausas

    def test_los_grupos_del_catalogo_nombran_fuentes_activas(self):
        active = {source.id for source in sources.ACTIVE}
        for key, ids in sources.SHARED_SERVER.items():
            self.assertLessEqual(set(ids), active, key)
            self.assertTrue(all(s.concurrency_group == key for s in sources.ACTIVE if s.id in ids))
        self.assertTrue(all(s.concurrency_group is None for s in sources.ACTIVE
                            if all(s.id not in ids for ids in sources.SHARED_SERVER.values())))
