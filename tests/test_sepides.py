import re
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import sepides

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def __init__(self, html=None):
        self.html = html or fixture("sepides-empleo.html")

    def get(self, url):
        return self.html


def bases(http, url, what):
    return fixture("sepides-bases.txt")


def without_committee(html):
    """El proceso tal como estaba al convocarse, antes de publicar la composición del órgano."""
    return re.sub(r'<li><a href="[^"]*COMPOSICION-ORGANO-SELECCION-PYC[^"]*"[^>]*>[^<]*</a></li>', "", html)


class Page(unittest.TestCase):
    def setUp(self):
        self.processes = sepides.parse_page(fixture("sepides-empleo.html"))

    def test_pestanas_y_procesos(self):
        tabs = [p["tab"] for p in self.processes]
        self.assertEqual(tabs.count("PROCESOS ABIERTOS"), 2)
        self.assertEqual(tabs.count("PROCESOS CERRADOS"), 3)
        self.assertEqual(self.processes[0]["title"], "Subdirector/a de Planificación y Control")
        self.assertEqual(self.processes[0]["company"], "Sepides")

    def test_abierto_en_la_web_no_es_inscripcion_abierta(self):
        # Hoy los dos «abiertos» ya publicaron composición del órgano o listados.
        self.assertEqual([sepides._is_registration_open(p) for p in self.processes], [False] * 5)

    def test_pagina_sin_pestanas_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            sepides.parse_page("<h2>Empleo</h2>")


class Source(unittest.TestCase):
    def offers(self, html, today):
        source = sepides.SepidesSource(today=today)
        with mock.patch.object(sepides, "read_pdf", bases):
            return source, source.list_offers(FakeHttp(html))

    def test_hoy_no_hay_inscripciones_abiertas(self):
        _, offers = self.offers(fixture("sepides-empleo.html"), date(2026, 11, 7))
        self.assertEqual(offers, [])

    def test_proceso_recien_convocado_es_oferta_hasta_su_plazo(self):
        html = without_committee(fixture("sepides-empleo.html"))
        source, offers = self.offers(html, date(2026, 7, 10))
        (offer,) = offers
        self.assertEqual((offer.title, offer.company, offer.kind, offer.positions, offer.deadline),
                         ("Subdirector/a de Planificación y Control", "Sepides", "indefinido", 1, "2026-07-16"))
        self.assertEqual(offer.ref, "subdirector-a-de-planificacion-y-control-2026-07")
        self.assertEqual(source.fetch_detail(FakeHttp(html), offer).location, "Madrid")

    def test_pasado_el_plazo_deja_de_ser_oferta(self):
        html = without_committee(fixture("sepides-empleo.html"))
        _, offers = self.offers(html, date(2026, 7, 17))
        self.assertEqual(offers, [])

    def test_documento_desconocido_lo_deja_fuera(self):
        html = without_committee(fixture("sepides-empleo.html")).replace(
            "Convocatoria del proceso selectivo.</a></li>", "Convocatoria del proceso selectivo.</a></li><li><a href=\"https://sepides.es/x.pdf\">Algo nuevo.</a></li>", 1)
        _, offers = self.offers(html, date(2026, 7, 10))
        self.assertEqual(offers, [])
