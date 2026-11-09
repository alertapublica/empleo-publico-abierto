import unittest
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import fgc

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("fgc-convocatories.html" if url == fgc.PAGE else "fgc-ficha.html")


class Lectura(unittest.TestCase):
    def test_tarjetas_con_plazo_y_contrato_literal(self):
        entries, total = fgc.parse_tiles(fixture("fgc-convocatories.html"))
        self.assertEqual((len(entries), total), (4, 4))
        first = entries[0]
        self.assertEqual(first["ref"], "1373217457")
        self.assertEqual(first["title"], "Tècnic/a mitjà/mitjana de Bon Govern Corporatiu")
        self.assertEqual(first["deadline"], "2026-11-13")
        self.assertEqual(first["contract"], "Durada determinada / Indefinit")
        self.assertTrue(first["url"].startswith("https://treballar.fgc.cat/job/"))

    def test_plazo_de_la_tarjeta_y_no_el_de_retirada_del_anuncio(self):
        # Montserrat: «Termini presentació» 06/11/2026; su ficha dice validThrough del día 10.
        entries, _ = fgc.parse_tiles(fixture("fgc-convocatories.html"))
        self.assertEqual(entries[3]["deadline"], "2026-11-06")

    def test_sin_convocatorias(self):
        html = "<p>Actualment no hi ha posicions obertes que coincideixin.</p>"
        self.assertEqual(fgc.parse_tiles(html), ([], 0))

    def test_pagina_desconocida(self):
        with self.assertRaises(SourceLayoutError):
            fgc.parse_tiles("<h1>Manteniment</h1>")

    def test_ficha_sin_plazo_y_con_lugar(self):
        detail = fgc.parse_job(fixture("fgc-ficha.html"))
        self.assertIsNone(detail.deadline)
        self.assertEqual(detail.location, "Barcelona")
        self.assertIn("Bon Govern Corporatiu", detail.sections[0]["html"])


class Fuente(unittest.TestCase):
    def test_abiertas_por_el_plazo_de_la_tarjeta(self):
        with mock.patch.object(fgc, "today_madrid", return_value="2026-11-08"):
            listed = fgc.FgcSource().list_offers(FakeHttp())
        self.assertEqual([o.deadline for o in listed], ["2026-11-13", "2026-11-19", "2026-11-20"])
        self.assertEqual(listed[0].apply_url, "https://treballar.fgc.cat/talentcommunity/apply/1373217457/?locale=ca_ES")
        self.assertIsNone(listed[0].kind)
        self.assertEqual(listed[0].contract, "Durada determinada / Indefinit")
