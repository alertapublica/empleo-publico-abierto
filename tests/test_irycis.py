import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import irycis

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, page=None):
        self.urls = []
        self.page = page or fixture("irycis-empleo.html")

    def get(self, url):
        self.urls.append(url)
        return self.page


class Irycis(unittest.TestCase):
    def test_filas_de_los_dos_ultimos_anios(self):
        rows = irycis.parse_page(fixture("irycis-empleo.html"))
        self.assertEqual([r["ref"] for r in rows],
                         ["C75/26", "C74/26", "C73/26", "C72/26", "C81/25", "C80/25", "C79/25"])
        c75 = rows[0]
        self.assertEqual((c75["opens_on"], c75["deadline"], c75["title"]),
                         ("2026-11-04", "2026-11-16", "Diplomatura/Grado en Enfermería"))
        self.assertTrue(c75["url"].endswith("/Convocatorias/2026/75%2026%20CONVOCATORIA.pdf"))

    def test_cierre_en_el_anio_siguiente(self):
        c81 = next(r for r in irycis.parse_page(fixture("irycis-empleo.html")) if r["ref"] == "C81/25")
        self.assertEqual((c81["opens_on"], c81["deadline"]), ("2025-12-29", "2026-01-22"))

    def test_solo_la_abierta(self):
        http = Http()
        (offer,) = irycis.IrycisSource(NOW).list_offers(http)
        self.assertEqual((offer.ref, offer.opens_on, offer.deadline, offer.deadline_time, offer.kind),
                         ("C75/26", "2026-11-04", "2026-11-16", None, None))
        self.assertEqual(http.urls, [irycis.PAGE])

    def test_en_enero_sigue_la_del_anio_anterior(self):
        january = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)
        refs = [o.ref for o in irycis.IrycisSource(january).list_offers(Http())]
        self.assertIn("C81/25", refs)

    def test_sufijo_distinto_del_anio_no_se_usa(self):
        page = fixture("irycis-empleo.html").replace("C75/26", "C75/25")
        refs = [r["ref"] for r in irycis.parse_page(page)]
        self.assertNotIn("C75/25", refs)

    def test_plazo_demasiado_largo_no_se_usa(self):
        page = fixture("irycis-empleo.html").replace("<td>16/11</td>", "<td>03/11</td>")
        refs = [r["ref"] for r in irycis.parse_page(page)]
        self.assertNotIn("C75/26", refs)

    def test_sin_tablas_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            irycis.parse_page("<main><h1>Ofertas de empleo</h1></main>")


if __name__ == "__main__":
    unittest.main()
