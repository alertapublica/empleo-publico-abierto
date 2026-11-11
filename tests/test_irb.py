import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import irb

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Listado real; toda ficha devuelve la real de LAB/26/17 (cierre: 23/11/2026)."""

    def __init__(self):
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        return fixture("irb-jobs.html" if url == irb.PAGE else "irb-job.html")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def test_nueve_ofertas_sin_los_enlaces_externos(self):
        rows = irb.parse_page(fixture("irb-jobs.html"))
        self.assertEqual(len(rows), 9)
        self.assertEqual(rows[0]["ref"], "8699011")


    def test_estructura_desconocida_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            irb.parse_page(fixture("irb-jobs.html").replace("jobs_list_container", "otra-lista"))
        with self.assertRaises(SourceLayoutError):
            irb.parse_page(fixture("irb-jobs.html").replace("/jobs/", "/positions/"))

    def test_aviso_sin_vacantes_es_lista_vacia(self):
        self.assertEqual(irb.parse_page("<main><p>There are no open positions right now.</p></main>"), [])


class Job(unittest.TestCase):
    def test_jobposting_con_cierre_y_plazas_en_la_descripcion(self):
        job = irb.parse_job(fixture("irb-job.html"))
        self.assertEqual(job["title"], "Research Assistant (Ref. LAB/26/17)")
        self.assertEqual((job["deadline"], job["positions"], job["location"]), ("2026-11-23", 1, "Barcelona"))
        self.assertEqual(job["published_on"], "2026-10-26")
        self.assertIn("Research Assistant", job["description"])

    def test_sin_jobposting_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            irb.parse_job("<html><body>Job</body></html>")


class Source(unittest.TestCase):
    def test_ofertas_en_plazo_con_codigo_aparte(self):
        http = Http()
        source = irb.IrbSource(now=at(11, 11))
        offers = source.list_offers(http)
        self.assertEqual(len(http.asked), 1 + 9)
        self.assertEqual(len(offers), 9)
        labels = source.labels(offers[0].title, offers[0].ref)
        self.assertEqual((labels["title"], labels["code"]), ("Research Assistant", "LAB/26/17"))
        self.assertEqual(source.fetch_detail(http, offers[0]).location, "Barcelona")

    def test_vencido_el_cierre_no_es_oferta(self):
        self.assertEqual(irb.IrbSource(now=at(11, 24)).list_offers(Http()), [])


if __name__ == "__main__":
    unittest.main()
