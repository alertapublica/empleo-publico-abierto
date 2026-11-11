import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import idisba

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Página 1 real; la 2, la misma con las fechas de 2025 (todo vencido)."""

    def __init__(self):
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        page = fixture("idisba-ofertas.html")
        return page if url == idisba.PAGE else page.replace("2026", "2025")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def setUp(self):
        self.rows = idisba.parse_page(fixture("idisba-ofertas.html"))

    def test_cinco_convocatorias_con_plazo(self):
        self.assertEqual(len(self.rows), 5)
        first = self.rows[0]
        self.assertEqual((first["ref"], first["opens_on"], first["deadline"]),
                         ("2026-50-RLTIDISBA", "2026-10-28", "2026-11-10"))
        self.assertEqual(first["bulletin"], "Núm. BOIB: 137 - 27/10/2026")
        self.assertTrue(first["url"].startswith("https://www.idisba.es/es/trabajo/ofertas-de-trabajo/5110/"))

    def test_documentos_sin_el_tamano(self):
        labels = [label for label, _ in self.rows[4]["documents"]]
        self.assertIn("20261104_lista_provis_admitidos_y_excluidos_2026-53-IDISBA", labels)
        self.assertFalse(any("PDF" in label for label in labels))

    def test_sin_convocatorias_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            idisba.parse_page("<main><h1>Ofertas de trabajo</h1></main>")


class Source(unittest.TestCase):
    def test_en_plazo_y_lee_la_pagina_siguiente(self):
        http = Http()
        offers = idisba.IdisbaSource(now=at(11, 11)).list_offers(http)
        self.assertEqual([o.deadline for o in offers], ["2026-12-03"] * 3)
        self.assertEqual(len(http.asked), 2)  # la página 1 tenía abiertas; la 2, ya no

    def test_sin_abiertas_no_sigue(self):
        http = Http()
        self.assertEqual(idisba.IdisbaSource(now=at(12, 4)).list_offers(http), [])
        self.assertEqual(len(http.asked), 1)

    def test_ficha_con_plazo_boib_y_documentos(self):
        source = idisba.IdisbaSource(now=at(11, 11))
        offer = source.list_offers(Http())[0]
        sections = {s["title"]: s["html"] for s in source.fetch_detail(Http(), offer).sections}
        self.assertIn("Inicio: 23/10/2026 - Fin: 03/12/2026", sections["Plazo de presentación"])
        self.assertIn("Publicación oficial", sections["Publicación en el BOIB"])
        self.assertIn("Bases (ES)", sections["Documentación"])
        self.assertEqual(source.labels(offer.title, offer.ref)["code"], offer.ref)


if __name__ == "__main__":
    unittest.main()
