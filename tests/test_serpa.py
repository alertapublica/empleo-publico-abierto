import unittest
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import serpa
from empleo.text import mixed_decode

FIXTURES = Path(__file__).parent / "fixtures"


def raw(name):
    return (FIXTURES / name).read_bytes()


def page(name):
    return mixed_decode(raw(name))


class FakeHttp:
    """Todas las fichas del tablón responden con la misma, salvo las indicadas."""

    def __init__(self, default="serpa-ficha.html", **special):
        self.default, self.special = default, special

    def get_bytes(self, url):
        if url == serpa.PAGE:
            return raw("serpa-ofertas.html")
        name = next((f for ref, f in self.special.items() if ref in url), self.default)
        return raw(name)


class Lectura(unittest.TestCase):
    def test_fichas_del_tablon_sin_repetir_ni_actas(self):
        entries = serpa.parse_board(page("serpa-ofertas.html"))
        self.assertEqual(len(entries), 8)
        self.assertEqual(entries[1]["ref"], "SP2026010_TITULADOSUPERIORINFORMATICO")
        self.assertTrue(all(e["url"].endswith(".htm") for e in entries))

    def test_tablon_desconocido(self):
        with self.assertRaises(SourceLayoutError):
            serpa.parse_board("<h1>Mantenimiento</h1>")

    def test_plazo_con_hora_y_contrato_literal(self):
        ficha = serpa.parse_ficha(page("serpa-ficha.html"))
        self.assertEqual(ficha["title"], "1 PLAZA DE PERSONAL PROGRAMADOR INFORMÁTICO. TITULADO SUPERIOR.")
        self.assertEqual((ficha["deadline"], ficha["deadline_time"]), ("2026-08-14", "08:00"))
        self.assertEqual((ficha["contract"], ficha["kind"], ficha["positions"]), ("Temporal", "temporal", 1))
        self.assertEqual(ficha["published_on"], "2026-08-03")
        self.assertFalse(ficha["cancelled"])
        self.assertIn("BASES", ficha["documents"])
        self.assertNotIn("ACTA", ficha["documents"])

    def test_anulada(self):
        self.assertTrue(serpa.parse_ficha(page("serpa-ficha-anulada.html"))["cancelled"])

    def test_fecha_sin_año_no_se_completa(self):
        ficha = serpa.parse_ficha(page("serpa-ficha-sin-año.html"))
        self.assertIsNone(ficha["deadline"])
        self.assertEqual(ficha["contract"], "Temporal a jornada completa")


class Fuente(unittest.TestCase):
    def listed(self, today, http):
        with mock.patch.object(serpa, "today_madrid", return_value=today):
            return serpa.SerpaSource().list_offers(http)

    def test_abierta_hasta_el_ultimo_dia_con_su_hora(self):
        http = FakeHttp("serpa-ficha-anulada.html", SP2026010="serpa-ficha.html")
        [offer] = self.listed("2026-08-14", http)
        self.assertEqual((offer.ref, offer.deadline, offer.deadline_time), ("SP2026010_TITULADOSUPERIORINFORMATICO", "2026-08-14", "08:00"))
        self.assertEqual(offer.kind, "temporal")

    def test_anulada_no_se_ofrece_aunque_su_plazo_siga(self):
        self.assertEqual(self.listed("2026-07-20", FakeHttp("serpa-ficha-anulada.html")), [])

    def test_ficha_del_año_sin_plazo_legible_avisa(self):
        with self.assertRaises(SourceLayoutError):
            self.listed("2026-08-01", FakeHttp("serpa-ficha.html", SP2026004="serpa-ficha-sin-año.html"))

    def test_ficha_antigua_sin_año_se_ignora(self):
        self.assertEqual(self.listed("2027-01-10", FakeHttp("serpa-ficha-sin-año.html")), [])

    def test_detalle_sin_otra_peticion(self):
        source = serpa.SerpaSource()
        with mock.patch.object(serpa, "today_madrid", return_value="2026-08-10"):
            offers = source.list_offers(FakeHttp("serpa-ficha-anulada.html", SP2026010="serpa-ficha.html"))
        detail = source.fetch_detail(None, offers[0])
        self.assertEqual([s["title"] for s in detail.sections], ["Descripción de la oferta", "Documentos de la convocatoria"])
