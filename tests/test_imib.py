import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import imib

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, page=None):
        self.urls = []
        self.page = page or fixture("imib-ofertas.html")

    def get(self, url):
        self.urls.append(url)
        if url == imib.PAGE:
            return self.page
        return fixture("imib-ficha.html") if url == imib.OLD + "2092" else "<p>Convocatoria</p>"


class Imib(unittest.TestCase):
    def test_filas_del_listado(self):
        rows = imib.parse_page(fixture("imib-ofertas.html"))
        self.assertEqual(len(rows), 10)
        row = next(r for r in rows if r["ref"] == "IMIB26_C77BIS")
        self.assertEqual((row["id"], row["opens_on"], row["deadline"], row["published_on"]),
                         ("2092", "2026-11-03", "2026-11-09", "2026-11-03"))
        self.assertEqual(row["title"], "TÉCNICO/A SUPERIOR FPII DE APOYO A LA INVESTIGACIÓN")

    def test_hora_de_la_ficha_antigua(self):
        self.assertEqual(imib.parse_hour(fixture("imib-ficha.html"), "2026-11-09"), ("2026-11-09", "10:00"))

    def test_sin_hora_si_la_ficha_da_otro_dia(self):
        self.assertEqual(imib.parse_hour(fixture("imib-ficha.html"), "2026-11-11"), ("2026-11-11", None))

    def test_solo_las_abiertas_y_su_ficha(self):
        http = Http()
        offers = imib.ImibSource(NOW).list_offers(http)
        self.assertEqual(sorted(o.ref for o in offers), ["IMIB26_C77BIS", "IMIB26_C79", "IMIB26_C83"])
        self.assertEqual(len(http.urls), 4)
        c77 = next(o for o in offers if o.ref == "IMIB26_C77BIS")
        self.assertEqual((c77.deadline, c77.deadline_time, c77.opens_on, c77.kind), ("2026-11-09", "10:00", "2026-11-03", None))

    def test_cierra_a_su_hora(self):
        late = datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)  # 10:00 en Madrid
        refs = [o.ref for o in imib.ImibSource(late).list_offers(Http())]
        self.assertNotIn("IMIB26_C77BIS", refs)

    def test_si_la_mas_antigua_sigue_abierta_se_detiene(self):
        page = fixture("imib-ofertas.html").replace("25/09/2026-05/10/2026", "25/09/2026-30/11/2026")
        with self.assertRaises(SourceLayoutError):
            imib.ImibSource(NOW).list_offers(Http(page))

    def test_sin_tabla_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            imib.parse_page("<p>Ofertas de Empleo</p>")


if __name__ == "__main__":
    unittest.main()
