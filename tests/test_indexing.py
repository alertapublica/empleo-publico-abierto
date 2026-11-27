import io
import json
import tempfile
import unittest
import unittest.mock
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError

from empleo import indexing

BASE = "https://alertapublica.es/"
NOW = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)  # 27/11 a las 04:00 en el Pacífico


def url(n):
    return f"{BASE}ofertas/tragsa-{n}/"


def manifest(**fichas):
    """fichas: n=huella (marcado e indexable), n=None (sin marcado, indexable), n="noindex"."""
    entries = {}
    for name, value in fichas.items():
        n = name.removeprefix("f")
        entries[url(n)] = ({"huella": None, "noindex": True} if value == "noindex"
                           else {"huella": value, "noindex": False})
    return {"base_url": BASE, "generado": NOW.isoformat(), "fichas": entries}


class Response:
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def error(code, message="error"):
    body = json.dumps({"error": {"code": code, "message": message}}).encode()
    return HTTPError(indexing.ENDPOINT, code, message, {}, io.BytesIO(body))


class Google:
    """urlopen simulado: responde 200 salvo lo programado para cada URL (en orden)."""

    def __init__(self, **plan):
        self.plan = {url(k.removeprefix("f")): list(v) for k, v in plan.items()}
        self.sent = []

    def __call__(self, request, timeout):
        sent = json.loads(request.data)
        self.sent.append((sent["url"], sent["type"]))
        assert request.full_url == "https://indexing.googleapis.com/v3/urlNotifications:publish"
        assert request.get_method() == "POST"
        assert request.headers["Authorization"] == "Bearer token"
        assert request.headers["Content-type"] == "application/json"
        assert timeout == indexing.TIMEOUT
        queued = self.plan.get(sent["url"])
        if queued:
            raise queued.pop(0)
        return Response()


class IndexingTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / ".github/indexing-state.json"
        self.sleeps = []

    def tearDown(self):
        self.tmp.cleanup()

    def run_with(self, data, google=None, now=NOW, clock=lambda: 0.0):
        google = google or Google()
        lines, failed = indexing.run(data, self.path, "token", now=lambda: now, opener=google,
                                     sleep=self.sleeps.append, clock=clock)
        return google, lines, failed

    def state(self):
        return json.loads(self.path.read_text())

    def test_altas_cambios_perdida_y_noindex(self):
        google, _, failed = self.run_with(manifest(f1="a", f2="b", f3=None))
        self.assertFalse(failed)
        # La 3 nunca tuvo marcado: no se avisa.
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED"), (url(2), "URL_UPDATED")])
        self.assertEqual(self.state()["urls"][url(1)]["huella"], "a")
        self.assertEqual(self.state()["urls"][url(1)]["acuse"], NOW.isoformat(timespec="seconds"))
        # Sin cambios: nada que mandar.
        google, _, _ = self.run_with(manifest(f1="a", f2="b", f3=None))
        self.assertEqual(google.sent, [])
        # Cambia la huella de la 1 y la 2 pierde el marcado pero sigue indexable.
        google, _, _ = self.run_with(manifest(f1="a2", f2=None, f3=None))
        self.assertEqual(google.sent, [(url(2), "URL_UPDATED"), (url(1), "URL_UPDATED")])
        self.assertIsNone(self.state()["urls"][url(2)]["huella"])
        # A las 48 horas del cierre la 2 lleva noindex: se retira, una sola vez.
        google, _, _ = self.run_with(manifest(f1="a2", f2="noindex", f3=None))
        self.assertEqual(google.sent, [(url(2), "URL_DELETED")])
        google, _, _ = self.run_with(manifest(f1="a2", f2="noindex", f3=None))
        self.assertEqual(google.sent, [])

    def test_ficha_que_desaparece_se_retira(self):
        self.run_with(manifest(f1="a", f2="b"))
        google, _, _ = self.run_with(manifest(f1="a"))
        self.assertEqual(google.sent, [(url(2), "URL_DELETED")])
        google, _, _ = self.run_with(manifest(f1="a"))
        self.assertEqual(google.sent, [])

    def test_cierre_y_reapertura_el_mismo_dia(self):
        self.run_with(manifest(f1="a"))
        google, _, _ = self.run_with(manifest(f1=None))
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED")])
        google, _, _ = self.run_with(manifest(f1="a"))
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED")])
        self.assertEqual(self.state()["urls"][url(1)]["huella"], "a")
        self.assertEqual(self.state()["enviados"], 3)
        # Reabierta después de retirada: vuelve a avisarse.
        self.run_with(manifest(f1="noindex"))
        google, _, _ = self.run_with(manifest(f1="b"))
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED")])

    def test_retiradas_primero_y_sin_esperar_al_tope_propio(self):
        many = {f"f{n}": "a" for n in range(1, 161)}
        google, lines, _ = self.run_with(manifest(**many))
        self.assertEqual(len(google.sent), indexing.PER_RUN)
        self.assertIn("- Pendientes: 0 retiradas y 10 cambios o altas.", lines)
        # Al día siguiente: 10 altas pendientes, 3 retiradas y 150 cambios de huella.
        changed = {f"f{n}": "b" for n in range(1, 161)} | {"f1": "noindex", "f2": None, "f3": "noindex"}
        google, _, _ = self.run_with(manifest(**changed), now=datetime(2026, 11, 28, 12, tzinfo=timezone.utc))
        self.assertEqual(google.sent[:3], [(url(1), "URL_DELETED"), (url(2), "URL_UPDATED"), (url(3), "URL_DELETED")])
        self.assertEqual(len(google.sent), 3 + indexing.PER_RUN)

    def test_cuota_diaria_entre_ejecuciones_y_cambio_de_dia_en_el_pacifico(self):
        many = {f"f{n}": "a" for n in range(1, 251)}
        google, _, _ = self.run_with(manifest(**many))
        self.assertEqual(len(google.sent), 150)
        google, lines, failed = self.run_with(manifest(**many))
        self.assertEqual(len(google.sent), 50)
        self.assertFalse(failed)
        self.assertIn("(agotada)", lines[2])
        self.assertEqual(self.state()["enviados"], 200)
        # Las 07:59 UTC del 28 aún son el 27 en el Pacífico; las 08:00, ya el 28.
        google, _, _ = self.run_with(manifest(**many), now=datetime(2026, 11, 28, 7, 59, tzinfo=timezone.utc))
        self.assertEqual(google.sent, [])
        google, _, _ = self.run_with(manifest(**many), now=datetime(2026, 11, 28, 8, 0, tzinfo=timezone.utc))
        self.assertEqual(len(google.sent), 50)
        self.assertEqual(self.state()["dia"], "2026-11-28")

    def test_429_de_cuota_del_dia_para_hasta_el_dia_siguiente(self):
        google = Google(f2=[error(429, "Quota exceeded for quota metric 'Publish requests' and limit "
                                       "'Publish requests per day per project'")])
        _, _, failed = self.run_with(manifest(f1="a", f2="b", f3="c"), google)
        self.assertEqual([u for u, _ in google.sent], [url(1), url(2)])
        self.assertFalse(failed)
        self.assertEqual(self.state()["enviados"], indexing.DAILY)
        self.assertNotIn("huella", self.state()["urls"].get(url(2), {}))
        google, _, _ = self.run_with(manifest(f1="a", f2="b", f3="c"))
        self.assertEqual(google.sent, [])

    def test_403_de_cuota_del_dia_y_403_por_minuto(self):
        google = Google(f1=[error(403, "Daily Limit Exceeded (dailyLimitExceeded)")])
        _, lines, failed = self.run_with(manifest(f1="a", f2="b"), google)
        self.assertEqual(len(google.sent), 1)
        self.assertFalse(failed)
        self.assertEqual(self.state()["enviados"], indexing.DAILY)
        self.assertIn("200 de 200 (agotada)", lines[2])
        # Por minuto: espera y reintenta, sin dar el día por perdido.
        self.path.unlink()
        google = Google(f1=[error(403, "User Rate Limit Exceeded (rateLimitExceeded)")])
        _, _, failed = self.run_with(manifest(f1="a", f2="b"), google)
        self.assertFalse(failed)
        self.assertEqual(len(google.sent), 3)
        self.assertEqual(self.state()["urls"][url(1)]["huella"], "a")

    def test_cuota_justo_agotada_sin_429_lo_dice(self):
        many = {f"f{n}": "a" for n in range(1, 151)}
        self.run_with(manifest(**many))
        _, lines, _ = self.run_with(manifest(**many | {f"f{n}": "a" for n in range(151, 201)}))
        self.assertIn("200 de 200 (agotada)", lines[2])

    def test_ejecucion_que_cruza_la_medianoche_del_pacifico(self):
        self.run_with(manifest(**{f"f{n}": "a" for n in range(1, 101)}))  # 100 el 27
        google = Google()
        # Tras 20 avisos dan las 00:00 en el Pacífico (08:00 UTC del 28).
        moment = lambda: datetime(2026, 11, 28, 7, 59, tzinfo=timezone.utc) \
            if len(google.sent) < 20 else datetime(2026, 11, 28, 8, 0, tzinfo=timezone.utc)
        indexing.run(manifest(**{f"f{n}": "a" for n in range(1, 301)}), self.path, "token", now=moment,
                     opener=google, sleep=self.sleeps.append, clock=lambda: 0.0)
        # Sin mirar el día en cada aviso se pararía en 200 del 27 (100 más); así llega al tope de 150.
        self.assertEqual(len(google.sent), indexing.PER_RUN)
        self.assertEqual(self.state()["dia"], "2026-11-28")
        self.assertEqual(self.state()["enviados"], indexing.PER_RUN - 20)

    def test_429_temporal_y_5xx_se_reintentan_con_espera(self):
        google = Google(f1=[error(429, "Too many requests per minute"), error(503, "Unavailable")])
        _, _, failed = self.run_with(manifest(f1="a", f2="b"), google)
        self.assertFalse(failed)
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED")] * 3 + [(url(2), "URL_UPDATED")])
        self.assertEqual(len(self.sleeps), 2)
        self.assertTrue(2 <= self.sleeps[0] < 3 and 4 <= self.sleeps[1] < 5)
        self.assertEqual(self.state()["enviados"], 4)  # los reintentos cuentan para la cuota
        self.assertEqual(self.state()["urls"][url(1)]["huella"], "a")

    def test_fallo_persistente_para_y_guarda_los_acuses_previos(self):
        google = Google(f2=[error(500), URLError("timeout"), error(502)])
        _, lines, failed = self.run_with(manifest(f1="a", f2="b", f3="c"), google)
        self.assertTrue(failed)
        self.assertIn("Parada", lines[-1])
        self.assertEqual(len(google.sent), 4)  # la 1 y tres intentos de la 2; la 3 ya no
        state = self.state()
        self.assertEqual(state["urls"][url(1)]["huella"], "a")
        self.assertEqual(state["enviados"], 4)
        # La 2 quizá llegó: se repite si sigue igual…
        self.assertEqual(state["urls"][url(2)]["huella"], indexing.UNCERTAIN)
        google, _, _ = self.run_with(manifest(f1="a", f2="b", f3="c"))
        self.assertEqual(google.sent, [(url(2), "URL_UPDATED"), (url(3), "URL_UPDATED")])

    def test_alta_incierta_que_se_cierra_o_desaparece_se_retira(self):
        for later, kind in ((None, "URL_UPDATED"), ("noindex", "URL_DELETED"), ("gone", "URL_DELETED")):
            with self.subTest(later=later):
                if self.path.exists():
                    self.path.unlink()
                self.run_with(manifest(f1="a"), Google(f1=[URLError("timeout")] * 3))
                self.assertEqual(self.state()["urls"][url(1)]["huella"], indexing.UNCERTAIN)
                data = manifest(f9="z") if later == "gone" else manifest(f1=later)
                google, _, _ = self.run_with(data)
                self.assertIn((url(1), kind), google.sent)

    def test_la_incertidumbre_se_conserva_si_luego_llega_cuota_o_rechazo(self):
        for then in (error(429, "Publish requests per day"), error(400, "Invalid URL")):
            with self.subTest(then=then.code):
                self.path.unlink(missing_ok=True)
                self.run_with(manifest(f1="a", f2="b"), Google(f1=[URLError("timeout"), then]))
                self.assertEqual(self.state()["urls"][url(1)]["huella"], indexing.UNCERTAIN)
                # La ficha desaparece al día siguiente: se retira, porque quizá Google la tiene.
                google, _, _ = self.run_with(manifest(f2="b"), now=datetime(2026, 11, 28, 12, tzinfo=timezone.utc))
                self.assertIn((url(1), "URL_DELETED"), google.sent)

    def test_baja_incierta_no_oculta_la_reapertura(self):
        self.run_with(manifest(f1="a"))
        self.run_with(manifest(f1="noindex"), Google(f1=[URLError("timeout")] * 3))
        self.assertEqual(self.state()["urls"][url(1)]["huella"], indexing.UNCERTAIN)
        google, _, _ = self.run_with(manifest(f1="a"))  # reabre con la misma huella
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED")])

    def test_rechazo_sin_respuesta_no_es_incierto(self):
        google = Google(f1=[error(429, "per minute") for _ in range(3)])
        _, _, failed = self.run_with(manifest(f1="a"), google)
        self.assertTrue(failed)
        self.assertNotIn(url(1), self.state()["urls"])

    def test_401_o_403_sin_cuota_paran_la_ejecucion(self):
        for code in (401, 403):
            with self.subTest(code=code):
                google = Google(f1=[error(code, "Permission denied. Failed to verify the URL ownership.")])
                _, lines, failed = self.run_with(manifest(f1="a", f2="b"), google)
                self.assertTrue(failed)
                self.assertEqual(len(google.sent), 1)
                self.assertIn(str(code), lines[-1])
                self.assertNotIn(url(1), self.state()["urls"])

    def test_primera_ejecucion_sin_nada_que_mandar_deja_el_estado(self):
        google, _, failed = self.run_with(manifest(f1=None))
        self.assertFalse(failed)
        self.assertEqual(google.sent, [])
        self.assertEqual(self.state(), {"dia": "2026-11-27", "enviados": 0, "urls": {}})

    def test_manifiesto_vacio_no_retira_nada(self):
        self.run_with(manifest(f1="a"))
        data = manifest()
        google, lines, failed = self.run_with(data)
        self.assertTrue(failed)
        self.assertEqual(google.sent, [])
        self.assertIn("ninguna ficha", lines[-1])

    def test_url_rechazada_se_aparta_tras_tres_veces(self):
        bad = lambda: error(400, "Invalid URL")
        for attempt in range(indexing.MAX_FAILS):
            google = Google(f1=[bad()])
            _, lines, failed = self.run_with(manifest(f1="a", f2="b"), google)
            self.assertTrue(failed)  # se señala, aunque la ejecución sigue con las demás
            self.assertIn(url(1), google.sent[0][0])
        self.assertEqual(self.state()["urls"][url(1)]["fallos"]["veces"], indexing.MAX_FAILS)
        google, lines, _ = self.run_with(manifest(f1="a", f2="b"), Google())
        self.assertEqual(google.sent, [])
        self.assertIn("- Apartadas tras 3 rechazos: 1.", lines)
        # Cambia lo que hay que avisar: se vuelve a intentar y, al confirmarse, se olvida el fallo.
        google, _, _ = self.run_with(manifest(f1="a2", f2="b"), Google())
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED")])
        self.assertNotIn("fallos", self.state()["urls"][url(1)])

    def test_rechazo_que_deja_de_estar_pendiente_se_olvida(self):
        for _ in range(indexing.MAX_FAILS):
            self.run_with(manifest(f1="a"), Google(f1=[error(400, "Invalid URL")]))
        # Se cierra (nunca tuvo acuse: nada que avisar) y reabre con la misma huella: se intenta otra vez.
        self.run_with(manifest(f1=None))
        self.assertNotIn("fallos", self.state()["urls"][url(1)])
        google, _, _ = self.run_with(manifest(f1="a"))
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED")])

    def test_tiempo_agotado_para(self):
        ticks = iter([0, 0, indexing.BUDGET])
        google, lines, failed = self.run_with(manifest(f1="a", f2="b"), clock=lambda: next(ticks))
        self.assertTrue(failed)
        self.assertEqual(len(google.sent), 1)

    def test_nunca_avisa_de_lo_que_no_es_una_ficha(self):
        data = manifest(f1="a")
        data["fichas"][BASE + "organismos/tragsa/"] = {"huella": "x", "noindex": False}
        data["fichas"]["https://otro.example/ofertas/x/"] = {"huella": "x", "noindex": False}
        for odd in ("ofertas/", "ofertas/../organismos/tragsa/", "ofertas/x/?p=2", "ofertas/x", "ofertas/a/b/"):
            data["fichas"][BASE + odd] = {"huella": "x", "noindex": False}
        google, _, _ = self.run_with(data)
        self.assertEqual(google.sent, [(url(1), "URL_UPDATED")])
        # Tampoco retira las del estado con otra dirección base.
        state = self.state()
        state["urls"]["https://otro.example/ofertas/y/"] = {"tipo": "URL_UPDATED", "huella": "x", "acuse": ""}
        self.path.write_text(json.dumps(state))
        google, _, _ = self.run_with(manifest(f1="a"))
        self.assertEqual(google.sent, [])

    def test_sin_token_no_hace_nada(self):
        with tempfile.TemporaryDirectory() as tmp, unittest.mock.patch.dict(
                "os.environ", {"GOOGLE_TOKEN": "", "GITHUB_STEP_SUMMARY": ""}), \
                unittest.mock.patch.object(indexing, "urlopen", side_effect=AssertionError), \
                unittest.mock.patch("sys.argv", ["indexing", str(Path(tmp) / "no-existe.json"),
                                                 str(Path(tmp) / "estado.json")]):
            self.assertEqual(indexing.main(), 0)
            self.assertFalse((Path(tmp) / "estado.json").exists())

    def test_main_avisa_si_falla_algo_inesperado(self):
        tmp = Path(self.tmp.name)
        summary = tmp / "resumen.md"
        with unittest.mock.patch.dict("os.environ", {"GOOGLE_TOKEN": "token", "GITHUB_STEP_SUMMARY": str(summary)}), \
                unittest.mock.patch("sys.argv", ["indexing", str(tmp / "no-existe.json"), str(self.path)]):
            self.assertEqual(indexing.main(), 1)
        self.assertIn("Parada: FileNotFoundError", summary.read_text())

    def test_main_avisa_de_un_rechazo(self):
        tmp = Path(self.tmp.name)
        (tmp / "jobposting.json").write_text(json.dumps(manifest(f1="a", f2="b")))
        out = io.StringIO()
        with unittest.mock.patch.dict("os.environ", {"GOOGLE_TOKEN": "token", "GITHUB_STEP_SUMMARY": ""}), \
                unittest.mock.patch.object(indexing, "urlopen", Google(f1=[error(400, "Invalid URL")])), \
                unittest.mock.patch("sys.argv", ["indexing", str(tmp / "jobposting.json"), str(self.path)]), \
                unittest.mock.patch("sys.stdout", out):
            self.assertEqual(indexing.main(), 1)
        self.assertIn(f"::warning title=Indexing API::Rechazada: {url(1)} (400: Invalid URL)", out.getvalue())
        self.assertEqual(self.state()["urls"][url(2)]["huella"], "b")

    def test_main_escribe_el_resumen(self):
        tmp = Path(self.tmp.name)
        (tmp / "jobposting.json").write_text(json.dumps(manifest(f1="a")))
        summary = tmp / "resumen.md"
        with unittest.mock.patch.dict("os.environ", {"GOOGLE_TOKEN": "token", "GITHUB_STEP_SUMMARY": str(summary)}), \
                unittest.mock.patch.object(indexing, "urlopen", Google()), \
                unittest.mock.patch("sys.argv", ["indexing", str(tmp / "jobposting.json"), str(self.path)]):
            self.assertEqual(indexing.main(), 0)
        self.assertIn("Confirmados: 1 `URL_UPDATED`", summary.read_text())


if __name__ == "__main__":
    unittest.main()
