import unittest
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import isdefe

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if url == isdefe.PAGE:
            return fixture("isdefe-puestos.html")
        if "/calendario-" in url:
            return fixture("isdefe-calendario.html")
        return fixture("isdefe-convocatoria.html")


class Lectura(unittest.TestCase):
    def test_solo_filas_con_enlace_de_inscripcion(self):
        entries = isdefe.parse_list(fixture("isdefe-puestos.html"))
        self.assertEqual(len(entries), 15)  # de las 41 filas del recorte
        first = entries[0]
        self.assertEqual(first["ref"], "2614")
        self.assertEqual(first["title"], "Consultor/a de Innovación y Capacidades de Defensa (2026-T00056)")
        self.assertEqual(first["published_on"], "2026-11-06")
        self.assertEqual(first["url"], "https://seleccionisdefe.es/convocatoria-2614")
        self.assertEqual(first["apply_url"], "https://seleccionisdefe.es/registro-2614")

    def test_tabla_casi_vacia_es_un_cambio_de_pagina(self):
        html = fixture("isdefe-puestos.html")
        start, end = html.index("<tr>", html.index("<tbody")), html.index("</tbody>")
        with self.assertRaises(SourceLayoutError):
            isdefe.parse_list(html[:start] + html[end:])

    def test_pagina_sin_tabla(self):
        with self.assertRaises(SourceLayoutError):
            isdefe.parse_list("<h1>Mantenimiento</h1>")

    def test_calendario(self):
        self.assertEqual(isdefe.parse_calendar(fixture("isdefe-calendario.html")), ("2026-11-06", "2026-11-13"))

    def test_calendario_con_el_hito_en_mayusculas(self):
        html = "<table><tbody><tr><td>INSCRIPCIÓN</td><td>03/11/2026</td><td>10/11/2026</td></tr></tbody></table>"
        self.assertEqual(isdefe.parse_calendar(html), ("2026-11-03", "2026-11-10"))

    def test_calendario_sin_inscripcion(self):
        html = "<table><tbody><tr><td>Listado provisional</td><td>16/11/2026</td><td>18/11/2026</td></tr></tbody></table>"
        self.assertIsNone(isdefe.parse_calendar(html))

    def test_perfil_con_contrato_literal(self):
        detail = isdefe.parse_profile(fixture("isdefe-convocatoria.html"))
        self.assertEqual((detail.contract, detail.kind), ("Contrato indefinido", "indefinido"))
        self.assertIn("Contabilidad", detail.sections[0]["html"])
        self.assertNotIn("Bases para", detail.sections[0]["html"])


class Fuente(unittest.TestCase):
    def test_ofertas_con_plazo_del_calendario(self):
        http = FakeHttp()
        with mock.patch.object(isdefe, "today_madrid", return_value="2026-11-08"):
            listed = isdefe.IsdefeSource().list_offers(http)
        self.assertEqual(len(listed), 15)
        self.assertEqual((listed[0].opens_on, listed[0].deadline), ("2026-11-06", "2026-11-13"))
        self.assertIsNone(listed[0].kind)
        self.assertEqual(sum("/calendario-" in url for url in http.urls), 15)

    def test_inscripcion_vencida_aunque_siga_el_enlace(self):
        with mock.patch.object(isdefe, "today_madrid", return_value="2026-11-14"):
            self.assertEqual(isdefe.IsdefeSource().list_offers(FakeHttp()), [])
