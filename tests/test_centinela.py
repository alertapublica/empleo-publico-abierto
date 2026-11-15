import unittest
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import ADIF, FURIOJA, RENFE

FIXTURES = Path(__file__).parent / "fixtures"


class FakeHttp:
    def __init__(self, html):
        self.html = html

    def get(self, url):
        return self.html


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Centinela(unittest.TestCase):
    def test_paginas_vacias_reales_no_dan_ofertas(self):
        self.assertEqual(ADIF.list_offers(FakeHttp(fixture("adif-plazo-abierto.html"))), [])
        self.assertEqual(RENFE.list_offers(FakeHttp(fixture("renfe-search.html"))), [])
        self.assertEqual(FURIOJA.list_offers(FakeHttp(fixture("furioja-ofertas.html"))), [])

    def test_si_desaparece_el_texto_falla_y_dice_donde_mirar(self):
        with self.assertRaises(SourceLayoutError) as caught:
            RENFE.list_offers(FakeHttp("<table><tr><td>Maquinista</td></tr></table>"))
        self.assertIn("empleo.renfe.com/search/", str(caught.exception))

    def test_tolera_saltos_de_linea_en_el_texto(self):
        text = "En estos momentos no hay ninguna\n   oferta de empleo público."
        self.assertEqual(ADIF.list_offers(FakeHttp(text)), [])
