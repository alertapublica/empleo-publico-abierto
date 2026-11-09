import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import lafe

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        return self.pages[url]


EXPIRED = fixture("lafe-empleo.html").replace("13/11/2026", "13/10/2026")


class LaFe(unittest.TestCase):
    def test_tarjeta_con_referencia_plazo_y_bases(self):
        first = lafe.parse_page(fixture("lafe-empleo.html"))[0]
        self.assertEqual((first["ref"], first["deadline"], first["published_on"]), ("165/2026", "2026-11-13", "2026-10-29"))
        self.assertEqual(first["title"], "Contratación de Técnico/a de investigación (T3) - Grupo de Investigación "
                                         "Hematología y Hemoterapia")
        self.assertTrue(first["bases"].endswith("/convocatorias/es/4198/ficheros/17587"))

    def test_solo_en_plazo_y_sigue_mientras_haya_alguna_abierta(self):
        http = Http({lafe.PAGE.format(1): fixture("lafe-empleo.html"), lafe.PAGE.format(2): EXPIRED})
        offers = lafe.LaFeSource(NOW).list_offers(http)
        self.assertEqual([o.ref for o in offers], ["165/2026", "162/2026"])
        self.assertEqual(len(http.urls), 2)  # la página 2 ya está toda vencida
        self.assertTrue(offers[0].apply_url.endswith("#inscripcion"))

    def test_pagina_toda_vencida_no_pide_mas(self):
        http = Http({lafe.PAGE.format(1): EXPIRED})
        self.assertEqual(lafe.LaFeSource(NOW).list_offers(http), [])
        self.assertEqual(len(http.urls), 1)

    def test_como_mucho_tres_paginas(self):
        http = Http({lafe.PAGE.format(n): fixture("lafe-empleo.html") for n in (1, 2, 3, 4)})
        lafe.LaFeSource(NOW).list_offers(http)
        self.assertEqual(len(http.urls), lafe.MAX_PAGES)

    def test_ficha_solo_con_las_bases(self):
        source = lafe.LaFeSource(NOW)
        offers = source.list_offers(Http({lafe.PAGE.format(1): fixture("lafe-empleo.html"), lafe.PAGE.format(2): EXPIRED}))
        detail = source.fetch_detail(None, offers[0])
        self.assertEqual(detail.location, "Valencia")
        self.assertIn("ficheros/17587", detail.sections[0]["html"])

    def test_cambios_de_marcado_detienen_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            lafe.parse_page("<h1>Empleo</h1>")
        with self.assertRaises(SourceLayoutError):
            lafe.parse_page(fixture("lafe-empleo.html").replace("Plazo de presentación", "Plazo", 1))


if __name__ == "__main__":
    unittest.main()
