import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import hunosa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("sadim-empleo.html")


def bases(http, url, what):
    return fixture("sadim-bases-p2026-02.txt")


class Page(unittest.TestCase):
    def test_procesos_con_codigo_y_plazo(self):
        processes = {p["code"]: p for p in hunosa.parse_page(fixture("sadim-empleo.html"))}
        self.assertEqual(set(processes), {"P2026.01.II", "P2026.02", "P2026.03"})
        self.assertIsNone(processes["P2026.01.II"]["deadline"])
        self.assertEqual(processes["P2026.02"]["deadline"], date(2026, 11, 16))
        self.assertEqual(processes["P2026.02"]["deadline_time"], "17:00")
        self.assertEqual(processes["P2026.02"]["title"], "GEÓLOGO DE EXPLORACIÓN")
        self.assertEqual(processes["P2026.02"]["positions"], 1)

    def test_pagina_sin_bloques_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            hunosa.parse_page("<h1>Mantenimiento</h1>")


class Source(unittest.TestCase):
    def offers(self, today):
        source = hunosa.HunosaSource(today=today)
        with mock.patch.object(hunosa, "read_pdf", bases):
            return source, source.list_offers(FakeHttp())

    def test_el_desierto_no_es_oferta_y_los_abiertos_si(self):
        _, offers = self.offers(date(2026, 11, 7))
        self.assertEqual([o.ref for o in offers], ["P2026.02", "P2026.03"])
        first = offers[0]
        self.assertEqual((first.company, first.kind, first.category, first.deadline),
                         ("SADIM", "indefinido", "Tasa de reposición", "2026-11-16"))

    def test_localidad_de_las_bases(self):
        source, offers = self.offers(date(2026, 11, 7))
        self.assertEqual(source.fetch_detail(FakeHttp(), offers[0]).location, "Langreo (Asturias)")

    def test_vencido_el_plazo_no_hay_ofertas(self):
        _, offers = self.offers(date(2026, 11, 17))
        self.assertEqual(offers, [])
