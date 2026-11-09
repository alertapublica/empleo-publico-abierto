import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import ciqus

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def get(self, url):
        return fixture("ciqus-ofertas.html")


class Ciqus(unittest.TestCase):
    def test_solo_las_filas_con_plazo(self):
        entries = ciqus.parse_page(fixture("ciqus-ofertas.html"))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["ref"], "convocatoria-publica-ordinaria-ciqus-142026-de-contratacion-de-personal-para-colaborar-en")
        self.assertEqual((entries[0]["opens_on"], entries[0]["deadline"], entries[0]["deadline_time"]),
                         ("2026-11-09", "2026-11-13", "23:59"))
        self.assertTrue(entries[0]["title"].startswith("Convocatoria Pública ORDINARIA CiQUS 14/2026"))

    def test_antes_de_empezar_se_ofrece_con_su_inicio(self):
        (offer,) = ciqus.CiqusSource(datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)).list_offers(Http())
        self.assertEqual((offer.opens_on, offer.kind, offer.company),
                         ("2026-11-09", None, "Universidade de Santiago de Compostela"))

    def test_cierra_a_su_hora(self):
        late = datetime(2026, 11, 13, 22, 59, tzinfo=timezone.utc)  # 23:59 en Madrid
        self.assertEqual(ciqus.CiqusSource(late).list_offers(Http()), [])

    def test_respeta_el_crawl_delay(self):
        self.assertEqual(ciqus.CiqusSource.delay, 10.0)

    def test_sin_tabla_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            ciqus.parse_page("<h1>Ofertas</h1>")


if __name__ == "__main__":
    unittest.main()
