import unittest
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import gpex

FIXTURES = Path(__file__).parent / "fixtures"


def raw(name):
    return (FIXTURES / name).read_bytes()


def page(name):
    return gpex.decode(raw(name))


def six_open():
    """La página de cerrados tiene seis tarjetas: con la marca de abiertas sirve de página llena."""
    return page("gpex-cerrados.html").replace("dtos_oferta_cerrada", "dtos_oferta").encode()


class FakeHttp:
    def __init__(self, listing="gpex-abiertos.html"):
        self.listing, self.urls = listing, []

    def get_bytes(self, url):
        self.urls.append(url)
        if "id_oferta=" in url:
            return raw("gpex-ficha.html")
        if "modulo=anuncios" in url:
            return raw("gpex-anuncios.html")
        return self.listing if isinstance(self.listing, bytes) else raw(self.listing)


class Lectura(unittest.TestCase):
    def test_codificacion_mixta(self):
        self.assertEqual(gpex.decode("Área ".encode() + "Mérida".encode("latin-1")), "Área Mérida")

    def test_proceso_abierto(self):
        [entry] = gpex.parse_open(page("gpex-abiertos.html"))
        self.assertEqual(entry["ref"], "2557")
        self.assertEqual(entry["title"], "BC26342 Personal Técnico Medio Ambiental")
        self.assertEqual((entry["opens_on"], entry["deadline"]), ("2026-11-06", "2026-11-12"))
        self.assertEqual(entry["positions"], 1)
        self.assertEqual(entry["area"], "GPEX / Área de Gestión Forestal y Medio Natural")

    def test_las_tarjetas_cerradas_no_se_leen_como_abiertas(self):
        self.assertEqual(gpex.parse_open(page("gpex-cerrados.html")), [])
        self.assertEqual(gpex.parse_open(gpex.decode(six_open()))[0]["deadline"], "2026-10-30")

    def test_pagina_desconocida(self):
        with self.assertRaises(SourceLayoutError):
            gpex.parse_open("<h1>Mantenimiento</h1>")

    def test_lista_vacia_es_valida(self):
        self.assertEqual(gpex.parse_open('<div id="contenido"><div id="ofertas"></div></div>'), [])

    def test_ficha(self):
        detail = gpex.parse_detail(page("gpex-ficha.html"))
        self.assertEqual(detail.location, "Mérida (Badajoz)")
        self.assertEqual(detail.contract, "Cubrir plaza temporal")
        self.assertIsNone(detail.kind)
        titles = [s["title"] for s in detail.sections]
        self.assertIn("Requisitos", titles)
        self.assertNotIn("Procedimiento", titles)
        self.assertIn("Características del puesto", titles)

    def test_llamamiento_de_bolsa_es_un_proceso(self):
        [notice] = gpex.parse_notices(page("gpex-anuncios.html"))
        self.assertEqual(notice.date, "2026-11-08")
        self.assertEqual(notice.via, "bolsa")
        self.assertEqual(notice.title, "GPEX convoca una oferta de empleo para un perfil de BC26364 Programador/a Senior")
        self.assertTrue(notice.url.endswith("id_noticia=883"))
        self.assertIsNone(notice.deadline)


class Fuente(unittest.TestCase):
    def test_abiertas_por_fecha(self):
        source = gpex.GpexSource()
        with mock.patch.object(gpex, "today_madrid", return_value="2026-11-08"):
            [offer] = source.list_offers(FakeHttp())
        self.assertEqual((offer.opens_on, offer.deadline, offer.kind), ("2026-11-06", "2026-11-12", None))
        self.assertEqual(source.enrich(None), {"2557": {"department": "Área de Gestión Forestal y Medio Natural"}})

    def test_vencidas_no_se_ofrecen(self):
        with mock.patch.object(gpex, "today_madrid", return_value="2026-11-13"):
            self.assertEqual(gpex.GpexSource().list_offers(FakeHttp()), [])

    def test_paginas_de_seis_sin_repetir(self):
        http = FakeHttp(six_open())  # seis tarjetas: pide la siguiente, que repite
        with mock.patch.object(gpex, "today_madrid", return_value="2026-01-01"):
            listed = gpex.GpexSource().list_offers(http)
        self.assertEqual(len(listed), 6)
        self.assertEqual(len(http.urls), 2)
