import json
import tempfile
import unittest
from pathlib import Path

from empleo import sondeo

PAGE = """<html><head><title>Empleo  público</title></head><body>
<ul><li><a href="/bases.pdf">Bases</a></li><li><a href="/otra">Convocatoria 2026</a></li></ul>
<p>Cargando...</p><script src="/wp-content/x.js"></script></body></html>"""


def fake(pages):
    calls = []

    def getter(url):
        calls.append(url)
        return dict(pages.get(url, {"estado": 404, "cuerpo": ""}))

    getter.calls = calls
    return getter


class Sondeo(unittest.TestCase):
    def test_analiza_lo_que_importa(self):
        result = sondeo.analyse(PAGE)
        self.assertEqual(result["titulo"], "Empleo público")
        self.assertEqual(result["enlaces"], 2)
        self.assertEqual(result["enlaces_pdf"], 1)
        self.assertTrue(result["marca_de_carga"])
        self.assertIn("wordpress", result["pistas"])
        self.assertGreaterEqual(result["palabras_de_oferta"], 1)

    def test_pide_cada_pagina_con_pausa_y_guarda_el_html(self):
        getter = fake({
            "https://a.example/empleo": {"estado": 200, "cuerpo": PAGE, "url_final": "https://a.example/empleo"},
        })
        pauses = []
        with tempfile.TemporaryDirectory() as tmp:
            report = sondeo.run(
                [("a", "https://a.example/empleo"), ("a", "https://a.example/otra")],
                Path(tmp), getter, pauses.append,
            )
            self.assertEqual(getter.calls, ["https://a.example/empleo", "https://a.example/otra"])
            self.assertEqual(report["paginas"][0]["analisis"]["enlaces_pdf"], 1)
            self.assertTrue((Path(tmp) / "html/01-a.html").exists())
            self.assertEqual(len(json.loads((Path(tmp) / "sondeo.json").read_text())["paginas"]), 2)
        self.assertEqual(pauses, [sondeo.DELAY])

    def test_error_de_red_queda_anotado_sin_romper(self):
        getter = fake({"https://b.example/e": {"estado": None, "error": "TimeoutError", "cuerpo": ""}})
        with tempfile.TemporaryDirectory() as tmp:
            report = sondeo.run([("b", "https://b.example/e")], Path(tmp), getter, lambda s: None)
        self.assertEqual(report["paginas"][0]["error"], "TimeoutError")
        self.assertIn("TimeoutError", sondeo.summary(report))

    def test_los_destinos_son_https_y_sin_inicio_de_sesion(self):
        for _, url in sondeo.TARGETS + sondeo.TARGETS_2 + sondeo.TARGETS_5 + sondeo.TARGETS_6:
            self.assertTrue(url.startswith("https://"), url)
        self.assertNotIn("procesosmasivos", " ".join(u for _, u in sondeo.TARGETS))
        self.assertLessEqual(len(sondeo.TARGETS), 25)
