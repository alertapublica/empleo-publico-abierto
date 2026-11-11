import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import emt

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Listado real; toda ficha devuelve la real del 23-10-2026 (inscripción hasta el 31/12/2026)."""

    def __init__(self):
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        return fixture("emt-empleo.html" if url == emt.PAGE else "emt-ficha.html")


def at(month, day, year=2026):
    return datetime(year, month, day, 10, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def test_diecisiete_convocatorias_con_su_fecha(self):
        rows = emt.parse_page(fixture("emt-empleo.html"))
        self.assertEqual(len(rows), 17)
        self.assertEqual((rows[0]["title"], rows[0]["published"]),
                         ("Convocatoria 2 plazas Titulado/a Superior Dirección de Servicios de Transporte", "2026-10-23"))

    def test_sin_lista_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            emt.parse_page("<p>Empleo</p>")


class Detail(unittest.TestCase):
    def test_periodo_y_documentos_fechados(self):
        detail = emt.parse_detail(fixture("emt-ficha.html"))
        self.assertEqual((detail["opens_on"], detail["deadline"]), ("2026-10-24", "2026-12-31"))
        self.assertEqual(detail["documents"][0]["label"], "1. Bases convocatoria 23-10-2026")
        self.assertEqual(detail["documents"][0]["date"], "2026-10-23")
        self.assertIn("dos plazas de Titulado/a Superior", detail["summary"])


    def test_enlaces_saneados(self):
        html = fixture("emt-ficha.html").replace('href="/getattachment/', 'href="javascript:alert(1)//')
        source = emt.EmtSource(now=at(11, 11))

        class Bad(Http):
            def get(self, url):
                return fixture("emt-empleo.html") if url == emt.PAGE else html

        offer = source.list_offers(Bad())[0]
        self.assertNotIn("javascript:", " ".join(s["html"] for s in source.fetch_detail(Bad(), offer).sections))


class Source(unittest.TestCase):
    def test_se_leen_todas_las_de_la_lista(self):
        # Filtrar por antigüedad daría por retirados procesos que la web sigue listando.
        http = Http()
        offers = emt.EmtSource(now=at(11, 11)).list_offers(http)
        self.assertEqual(len(http.asked), 1 + 17)
        self.assertEqual(offers[0].positions, 2)
        self.assertEqual((offers[0].deadline, offers[0].opens_on), ("2026-12-31", "2026-10-24"))

    def test_cerrada_la_inscripcion_sus_documentos_son_comunicados(self):
        source = emt.EmtSource(now=at(1, 2, 2027))
        self.assertEqual(source.list_offers(Http()), [])
        notices = source.list_announcements(Http())
        self.assertEqual(notices[0].date, "2026-10-23")
        self.assertEqual(notices[0].title, "1. Bases convocatoria 23-10-2026")


if __name__ == "__main__":
    unittest.main()
