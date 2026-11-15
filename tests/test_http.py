"""Cliente HTTP y lectura: intermedios, pausas, grupos por servidor, hilos y plazos."""
import contextlib
import io
import ssl
import threading
import time
import unittest
from unittest import mock

from empleo import http, ingest, sources
from empleo.model import ListedOffer


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
        self.assertEqual(sorted(seen), [("lenta", 10.0), ("normal", http.DEFAULT_DELAY)])


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
                mock.patch.dict("os.environ", {"INGESTA_HILOS": "1"}), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ingest.main(), 1)
        expected = ["INICIO rota", r"FIN rota error \d+ s, 2 peticiones, 1 fallidas",
                    "INICIO sana", r"FIN sana bien \d+ s, 2 peticiones, 0 fallidas",
                    "RESUMEN 2 fuentes, 1 a la vez: 1 bien; error: rota"]
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
        self.assertEqual(sorted(seen), [("lenta", 0), ("normal", 0), ("otra", 0)])
        self.assertEqual(len(sleep.call_args_list), 1)
        self.assertGreater(sleep.call_args.args[0], 5)  # la mayor de las dos pausas (10 s), no 2

    def test_los_grupos_del_catalogo_nombran_fuentes_activas(self):
        active = {source.id for source in sources.ACTIVE}
        for key, ids in sources.SHARED_SERVER.items():
            self.assertLessEqual(set(ids), active, key)
            self.assertTrue(all(s.concurrency_group == key for s in sources.ACTIVE if s.id in ids))
        self.assertTrue(all(s.concurrency_group is None for s in sources.ACTIVE
                            if all(s.id not in ids for ids in sources.SHARED_SERVER.values())))


class Plazo(unittest.TestCase):
    def client(self, seconds, delay=0.0):
        client = http.Client(delay=delay, deadline=time.monotonic() + seconds)
        client._opener = mock.Mock(open=mock.Mock(side_effect=http.urllib.error.URLError("caída")))
        return client

    def test_vencido_no_pide_nada(self):
        client = self.client(-1)
        with self.assertRaises(http.OutOfTime):
            client.get("https://example.org/")
        client._opener.open.assert_not_called()

    def test_no_espera_si_tras_la_pausa_no_queda_plazo(self):
        client = self.client(10, delay=20)
        client.last = time.monotonic()
        with mock.patch.object(http.time, "sleep") as sleep, self.assertRaises(http.OutOfTime):
            client.get("https://example.org/")
        sleep.assert_not_called()

    def test_si_vence_durante_la_pausa_no_pide_con_timeout_nulo(self):
        client = self.client(10)
        client._left = mock.Mock(side_effect=[10, 0])  # antes de la pausa y después
        with self.assertRaises(http.OutOfTime):
            client.get("https://example.org/")
        client._opener.open.assert_not_called()

    def test_recorta_el_timeout_y_no_espera_el_reintento_sin_plazo(self):
        client = self.client(10)  # (con `sleep` simulado, el reloj no avanza)
        with mock.patch.object(http.time, "sleep") as sleep, self.assertRaises(http.OutOfTime):
            client.get("https://example.org/")
        sleep.assert_called_once_with(5)  # tras el 2.º fallo tocaría esperar 15 s y quedan menos de 10
        self.assertEqual(client.attempts, 2)
        self.assertLessEqual(client._opener.open.call_args.kwargs["timeout"], 10)

    def test_ninguna_ficha_mala_se_lo_traga(self):
        self.assertFalse(issubclass(http.OutOfTime, Exception))

        class Source:
            id, detail_version = "x", 1

            def fetch_detail(self, client, offer):
                raise http.OutOfTime("sin tiempo para leer la ficha")

        listed = ListedOffer(ref="1", title="Técnico", company="X", url="https://example.org/1",
                             apply_url="https://example.org/1")
        offers = {"1": ingest._record("x", listed, "2026-11-15T00:00:00+00:00")}
        with self.assertRaises(http.OutOfTime):
            ingest.fetch_details(Source(), None, offers, [])


class Hilos(unittest.TestCase):
    def test_grupos_a_la_vez_y_dentro_del_grupo_de_uno_en_uno(self):
        sources = [fake("a1", group="a"), fake("b1", group="b"), fake("a2", group="a"), fake("b2", group="b")]
        both = threading.Barrier(2, timeout=30)  # se rompe si los dos grupos no van a la vez
        lock, active, most = threading.Lock(), {"a": 0, "b": 0}, {"a": 0, "b": 0}

        def run(source, *_):
            with lock:
                active[source.concurrency_group] += 1
                most[source.concurrency_group] = max(most[source.concurrency_group], active[source.concurrency_group])
            if source.id.endswith("1"):
                both.wait()
            time.sleep(0.02)
            with lock:
                active[source.concurrency_group] -= 1

        with mock.patch.object(ingest, "ACTIVE", sources), mock.patch.object(ingest, "run_source", run), \
                mock.patch.dict("os.environ", {"INGESTA_HILOS": "2"}), contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(ingest.main(), 0)
        self.assertEqual(most, {"a": 1, "b": 1})

    def test_una_fuente_sin_tiempo_no_frena_a_las_demas(self):
        sources = [fake("lenta"), fake("sana"), fake("otra")]
        seen = []

        def run(source, client, *_):
            if source.id == "lenta":
                raise http.OutOfTime("sin tiempo para leer https://example.org/")
            seen.append(source.id)

        out = io.StringIO()
        with mock.patch.object(ingest, "ACTIVE", sources), mock.patch.object(ingest, "run_source", run), \
                contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(ingest.main(), 1)
        self.assertEqual(sorted(seen), ["otra", "sana"])
        self.assertRegex(out.getvalue(), r"FIN lenta sin tiempo \d+ s")
        self.assertIn(": 2 bien; sin tiempo: lenta", out.getvalue())

    def test_cada_fuente_con_su_plazo_sin_pasar_del_total(self):
        deadlines = {}
        sources = [fake("primera", group="g"), fake("segunda", group="g")]

        def run(source, client, *_):
            deadlines[source.id] = client.deadline - time.monotonic()

        with mock.patch.object(ingest, "ACTIVE", sources), mock.patch.object(ingest, "run_source", run), \
                mock.patch.object(ingest, "SOURCE_BUDGET", 600), mock.patch.object(ingest, "TOTAL_BUDGET", 60), \
                contextlib.redirect_stdout(io.StringIO()):
            ingest.main()
        self.assertTrue(all(0 < left <= 60 for left in deadlines.values()), deadlines)  # el total, no 600
