import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import mercasa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("mercasa-unete.html")


def pdfs(http, url, what):
    if "AMPLIACION" in url:
        return fixture("mercasa-ampliacion.txt")
    return fixture("mercasa-bases-jur.txt" if "JURIDICA" in url else "mercasa-bases-tic.txt")


class Page(unittest.TestCase):
    def setUp(self):
        self.processes = mercasa.parse_page(fixture("mercasa-unete.html"))

    def test_procesos_con_sus_documentos(self):
        self.assertEqual([p["title"] for p in self.processes][:2], ["TÉCNICO/A APOYO TIC", "ASESOR/A JURÍDICO/A LETRADO/A"])
        self.assertTrue(any("AMPLIACIÓN" in label for label, _ in self.processes[1]["documents"]))

    def test_candidatos_a_oferta(self):
        self.assertEqual([mercasa._is_candidate(p) for p in self.processes], [True, True, False, False])

    def test_pagina_sin_documentos_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            mercasa.parse_page("<h2>Únete</h2>")


class Source(unittest.TestCase):
    def offers(self, today):
        source = mercasa.MercasaSource(today=today)
        with mock.patch.object(mercasa, "read_pdf", pdfs):
            return source, source.list_offers(FakeHttp())

    def test_la_ampliacion_manda_sobre_el_plazo_de_las_bases(self):
        _, offers = self.offers(date(2026, 11, 7))
        (offer,) = offers  # el técnico TIC cerró el 6 de noviembre
        self.assertEqual((offer.title, offer.deadline, offer.kind), ("Asesor/a jurídico/a letrado/a", "2026-11-16", "indefinido"))
        self.assertEqual(offer.deadline_time, "12:00")

    def test_hasta_el_ultimo_dia_sigue_abierta(self):
        _, offers = self.offers(date(2026, 11, 5))
        self.assertEqual([o.deadline for o in offers], ["2026-11-06", "2026-11-16"])

    def test_siglas_conservadas_en_el_titulo(self):
        _, offers = self.offers(date(2026, 11, 5))
        self.assertEqual(offers[0].title, "Técnico/a apoyo TIC")

    def test_pasado_el_plazo_no_hay_ofertas(self):
        _, offers = self.offers(date(2026, 11, 17))
        self.assertEqual(offers, [])

    def test_localidad_del_centro_de_trabajo(self):
        source, offers = self.offers(date(2026, 11, 7))
        self.assertEqual(source.fetch_detail(FakeHttp(), offers[0]).location, "Madrid")
