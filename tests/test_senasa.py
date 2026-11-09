import unittest
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import senasa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("senasa-empleo.html")


class Lectura(unittest.TestCase):
    def setUp(self):
        self.entries = senasa.parse_list(fixture("senasa-empleo.html"))

    def test_solo_bloques_con_referencia(self):
        # 74 bloques: 5 resoluciones y la llamada permanente a controladores no tienen referencia.
        self.assertEqual(len(self.entries), 68)
        self.assertNotIn("CONTROLADORES", " ".join(e["title"] for e in self.entries))

    def test_datos_de_una_convocatoria(self):
        entry = next(e for e in self.entries if e["ref"] == "98-26")
        self.assertEqual(entry["title"], "Jefe-a de Equipo (Mecánica). Salamanca")
        self.assertEqual((entry["positions"], entry["published_on"], entry["deadline"]),
                         (1, "2026-10-05", "2026-11-16"))
        self.assertEqual(entry["pdf"], "https://www.senasa.es/recursos/adobePDF/OfertasERP/98-26.pdf")

    def test_pagina_sin_convocatorias_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            senasa.parse_list("<h1>Mantenimiento</h1>")

    def test_convocatoria_sin_plazo_es_un_cambio_de_pagina(self):
        html = '<div class="contrato activa"><h1>X</h1><p>Referencia: 1-26</p></div>'
        with self.assertRaises(SourceLayoutError):
            senasa.parse_list(html)

    def test_pdf_contrato_literal_y_centro(self):
        data = senasa.parse_pdf(fixture("senasa-41-26.txt"))
        self.assertEqual(data, {"contract": "Temporal", "kind": "temporal", "location": "Madrid"})

    def test_pdf_con_contrato_desconocido_no_inventa_tipo(self):
        data = senasa.parse_pdf("Centro de trabajo: Sevilla Dirección de dependencia: X "
                                "Modalidad de contratación: Relevo Pruebas de Selección: Entrevistas.")
        self.assertEqual((data["contract"], data["kind"], data["location"]), ("Relevo", None, "Sevilla"))


class Fuente(unittest.TestCase):
    def test_abiertas_por_fecha_y_no_por_la_etiqueta(self):
        with mock.patch.object(senasa, "today_madrid", return_value="2026-11-08"):
            listed = senasa.SenasaSource().list_offers(FakeHttp())
        refs = [o.ref for o in listed]
        self.assertEqual(len(refs), 9)
        self.assertIn("41-26", refs)
        self.assertNotIn("105-26", refs)  # vencida el 2026-11-06
        self.assertEqual(listed[0].apply_url, senasa.PAGE)
        self.assertIsNone(listed[0].kind)

    def test_sin_enlace_de_inscripcion_no_se_ofrece_aunque_la_fecha_siga_vigente(self):
        html = """<div class="contrato cerrada"><h1>Retirada</h1><p>Referencia: 1-26</p>
        <p>Fecha fin de vigencia: 2026-12-31</p><p><a href="/r/1-26.pdf">PDF</a></p></div>
        <div class="contrato activa"><h1><a href="#" onclick="javascript: inscripcion(this);" ref="2-26">Abierta</a></h1>
        <p>Referencia: 2-26</p><p>Fecha fin de vigencia: 2026-12-31</p><p><a href="/r/2-26.pdf">PDF</a></p></div>"""
        http = mock.Mock(get=mock.Mock(return_value=html))
        with mock.patch.object(senasa, "today_madrid", return_value="2026-11-08"):
            self.assertEqual([o.ref for o in senasa.SenasaSource().list_offers(http)], ["2-26"])

    def test_vence_hoy_sigue_abierta(self):
        with mock.patch.object(senasa, "today_madrid", return_value="2026-11-16"):
            self.assertEqual(len(senasa.SenasaSource().list_offers(FakeHttp())), 9)

    def test_ficha_desde_el_pdf(self):
        with mock.patch.object(senasa, "today_madrid", return_value="2026-11-08"):
            offer = next(o for o in senasa.SenasaSource().list_offers(FakeHttp()) if o.ref == "41-26")
        with mock.patch.object(senasa, "read_pdf", return_value=fixture("senasa-41-26.txt")):
            detail = senasa.SenasaSource().fetch_detail(None, offer)
        self.assertEqual((detail.contract, detail.kind, detail.location), ("Temporal", "temporal", "Madrid"))
        self.assertIn("41-26.pdf", detail.sections[0]["html"])
