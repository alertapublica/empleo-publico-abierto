import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import idibaps

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def get(self, url):
        assert url == idibaps.PAGE, url  # una sola petición: el histórico paginado no se lee
        return fixture("idibaps-ofertes.html")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def setUp(self):
        self.rows = idibaps.parse_page(fixture("idibaps-ofertes.html"))

    def test_solo_la_pestana_de_abiertas(self):
        self.assertEqual(len(self.rows), 5)  # las 2 «Tancades» del fixture no cuentan

    def test_codigo_fecha_y_pdf(self):
        first = self.rows[0]
        self.assertEqual((first["ref"], first["deadline"]), ("FU-338/2026", "2026-11-12"))
        self.assertTrue(first["url"].startswith("https://www.clinicbarcelona.org/uploads/"))
        self.assertTrue(first["url"].endswith(".pdf"))

    def test_codigo_con_dos_siglas(self):
        self.assertIn("FU-ES-16/2026", [r["ref"] for r in self.rows])

    def test_tarjetas_irreconocibles_detienen_la_fuente(self):
        html = fixture("idibaps-ofertes.html").replace("research-offer-card", "otra-tarjeta")
        with self.assertRaises(SourceLayoutError):
            idibaps.parse_page(html)

    def test_pestana_vacia_con_aviso_es_lista_vacia(self):
        self.assertEqual(idibaps.parse_page('<div id="active"><p>No hi ha ofertes obertes.</p></div>'), [])

    def test_sin_pestana_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            idibaps.parse_page("<main>Ofertes de feina</main>")


class Source(unittest.TestCase):
    def test_titulo_sin_prefijo_y_codigo_aparte(self):
        source = idibaps.IdibapsSource(now=at(11, 11))
        offer = source.list_offers(Http())[0]
        labels = source.labels(offer.title, offer.ref)
        self.assertEqual(labels["title"], "Tècnic Plataformes per a la Plataforma Biobanc")
        self.assertEqual(labels["code"], "FU-338/2026")
        self.assertEqual(labels["source_title"], offer.title)

    def test_el_ultimo_dia_sigue_abierta_y_despues_no(self):
        hoy = idibaps.IdibapsSource(now=at(11, 12)).list_offers(Http())
        manana = idibaps.IdibapsSource(now=at(11, 13)).list_offers(Http())
        self.assertIn("FU-338/2026", [o.ref for o in hoy])
        self.assertNotIn("FU-338/2026", [o.ref for o in manana])

    def test_enlace_saneado(self):
        source = idibaps.IdibapsSource(now=at(11, 11))
        offer = source.list_offers(Http())[0]
        offer.url = "javascript:alert(document.domain)"
        self.assertNotIn("javascript:", source.fetch_detail(Http(), offer).sections[0]["html"])

    def test_ficha_enlaza_la_convocatoria(self):
        source = idibaps.IdibapsSource(now=at(11, 11))
        offer = source.list_offers(Http())[0]
        detail = source.fetch_detail(Http(), offer)
        self.assertEqual(detail.location, "Barcelona")
        self.assertIn(offer.url, detail.sections[0]["html"])


if __name__ == "__main__":
    unittest.main()
