import unittest
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import gesplan

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("gesplan-trabaja.html" if url == gesplan.PAGE else "gesplan-ficha.html")


class Lectura(unittest.TestCase):
    def test_tarjetas(self):
        entries = gesplan.parse_page(fixture("gesplan-trabaja.html"))
        self.assertEqual(len(entries), 5)
        first = entries[0]
        self.assertEqual(first["title"], "GC TF Técnico/a Especialista en Ciberseguridad Estrategia Corporativa")
        self.assertEqual((first["published_on"], first["deadline"]), ("2026-10-15", "2026-10-22"))
        self.assertEqual(first["place"], "Gran Canaria, Tenerife")

    def test_pagina_desconocida(self):
        with self.assertRaises(SourceLayoutError):
            gesplan.parse_page("<h1>Mantenimiento</h1>")

    def test_ficha_con_contrato_literal(self):
        detail = gesplan.parse_detail(fixture("gesplan-ficha.html"))
        self.assertEqual((detail.contract, detail.kind), ("Indefinido (100)", "indefinido"))
        self.assertEqual([s["title"] for s in detail.sections][:2], ["Descripción", "Requisitos"])

    def test_contrato_por_codigo_no_se_traduce(self):
        html = """<article><div class="uncont"><div class="vc_custom_heading_wrap"><h3><span>Tipo de contrato:</span></h3></div>
        <div class="uncode_text_column"><p>Circunstancias de la producción (402).</p></div></div></article>"""
        detail = gesplan.parse_detail(html)
        self.assertEqual((detail.contract, detail.kind), ("Circunstancias de la producción (402)", None))


class Fuente(unittest.TestCase):
    def test_hoy_no_hay_ninguna_abierta(self):
        with mock.patch.object(gesplan, "today_madrid", return_value="2026-11-08"):
            self.assertEqual(gesplan.GesplanSource().list_offers(FakeHttp()), [])

    def test_abierta_hasta_el_ultimo_dia_incluido(self):
        source = gesplan.GesplanSource()
        with mock.patch.object(gesplan, "today_madrid", return_value="2026-10-22"):
            [offer] = source.list_offers(FakeHttp())
        self.assertEqual((offer.deadline, offer.published_on), ("2026-10-22", "2026-10-15"))
        self.assertEqual(source.fetch_detail(FakeHttp(), offer).location, "Gran Canaria, Tenerife")
