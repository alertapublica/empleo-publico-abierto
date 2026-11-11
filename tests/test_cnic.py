import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import cnic

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def get(self, url):
        return fixture("cnic-ofertas.html" if url == cnic.PAGE else "cnic-ficha.html")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def setUp(self):
        self.rows = cnic.parse_page(fixture("cnic-ofertas.html"))

    def test_filas_con_referencia_fecha_y_estado(self):
        self.assertEqual(len(self.rows), 12)
        first = self.rows[0]
        self.assertEqual((first["ref"], first["deadline"], first["state"]),
                         ("TECPROYECTO-FSC-10.26", "2026-11-26", "Presentación de solicitudes"))
        self.assertEqual(first["url"], "https://www.cnic.es/es/convocatoria/tecnicoa-proyecto-sustitucion-persona-trabajadora-0")

    def test_manda_el_texto_de_la_fecha_y_no_su_atributo(self):
        # El atributo `content` de la primera fila dice 2026-11-11; el texto, 26/11/2026.
        self.assertIn('content="2026-11-11', fixture("cnic-ofertas.html"))
        self.assertEqual(self.rows[0]["deadline"], "2026-11-26")

    def test_sin_tabla_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            cnic.parse_page("<p>Ofertas de empleo</p>")


class Detail(unittest.TestCase):
    def test_texto_y_criterios(self):
        detail = cnic.parse_detail(fixture("cnic-ficha.html"))
        sections = {s["title"]: s["html"] for s in detail.sections}
        self.assertIn("Gestión y seguimiento de proyecto", sections["La convocatoria"])
        self.assertNotIn("<img", sections["La convocatoria"])
        self.assertIn("C8 - Entrevista (se desarrollará parcialmente en inglés) - 20%", sections["Criterios de valoración"])
        self.assertEqual(detail.location, "Madrid")


class Source(unittest.TestCase):
    def read(self, now):
        source = cnic.CnicSource(now=now)
        return source, source.list_offers(Http()), source.list_announcements(Http())

    def test_en_presentacion_de_solicitudes_y_en_plazo_es_oferta(self):
        source, offers, notices = self.read(at(11, 11))
        self.assertEqual(len(offers), 6)  # la de prácticas cierra hoy y sigue abierta todo el día
        self.assertEqual(offers[0].deadline, "2026-11-26")
        self.assertTrue(offers[0].apply_url.endswith("#block-inscripcion"))
        self.assertEqual(source.labels(offers[0].title, offers[0].ref)["code"], "TECPROYECTO-FSC-10.26")

    def test_las_demas_son_procesos_con_su_estado(self):
        _, _, notices = self.read(at(11, 11))
        self.assertEqual(len(notices), 6)
        self.assertEqual({n.date for n in notices}, {""})
        by_title = {n.title for n in notices}
        self.assertTrue({"Evaluación", "Cerrada"} <= by_title)
        cerrada = next(n for n in notices if n.title == "Cerrada")
        self.assertEqual(cerrada.state, "finalizado")
        self.assertTrue(cerrada.process.endswith(")"))  # con su referencia: hay títulos repetidos

    def test_vencido_el_plazo_pasa_a_proceso(self):
        _, offers, notices = self.read(at(11, 12))
        self.assertEqual(len(offers), 5)
        self.assertIn("Presentación de solicitudes", {n.title for n in notices})


if __name__ == "__main__":
    unittest.main()
