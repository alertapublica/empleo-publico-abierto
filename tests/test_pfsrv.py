import unittest
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources.pfsrv import AENA, ENAIRE, parse_aena, parse_enaire

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_bytes().decode("latin-1")  # estas webs sirven Latin-1


class Enaire(unittest.TestCase):
    def test_lee_filas_y_fechas(self):
        rows = parse_enaire(fixture("enaire-convocatorias.html"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0], {
            "code": "20261107", "title": "CONVOCATORIA EXTERNA TITULADOS/AS NIVELES A Y B",
            "start": "2026-11-06", "end": "2026-11-26", "published": "2026-11-06",
            "end_time": "23:59",
        })

    def test_solo_es_oferta_la_que_esta_en_plazo(self):
        offers = ENAIRE.offers_on(fixture("enaire-convocatorias.html"), "2026-11-07")
        self.assertEqual([o.ref for o in offers], ["20261107"])
        self.assertEqual(offers[0].deadline_time, "23:59")
        offer = offers[0]
        self.assertEqual(offer.title, "Convocatoria externa titulados/as niveles A y B")
        self.assertEqual((offer.opens_on, offer.deadline), ("2026-11-06", "2026-11-26"))
        self.assertEqual(offer.apply_url, ENAIRE.page)
        self.assertIsNone(offer.kind)
        self.assertEqual(ENAIRE.offers_on(fixture("enaire-convocatorias.html"), "2026-11-27"), [])
        self.assertEqual(ENAIRE.offers_on(fixture("enaire-convocatorias.html"), "2026-11-05"), [])

    def test_pagina_sin_tabla_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            parse_enaire("<h1>Mantenimiento</h1>")

    def test_fila_sin_fechas_detiene_la_lectura(self):
        html = ('<table class="empleo__tabla-convocatorias"><tbody><tr><td>Algo</td>'
                '<td><a href="PFSrv?codigo=1">x</a></td></tr></tbody></table>')
        with self.assertRaises(SourceLayoutError):
            parse_enaire(html)


class Aena(unittest.TestCase):
    def test_lee_los_cinco_bloques(self):
        rows = parse_aena(fixture("aena-convocatorias.html"))
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0]["code"], "20260630")
        self.assertEqual(rows[0]["title"], "24 PLAZAS TITULADOS/AS UNIVERSITARIOS/AS")
        self.assertEqual((rows[0]["start"], rows[0]["end"]), ("2026-07-01", "2026-07-14"))

    def test_hoy_no_hay_ninguna_abierta(self):
        self.assertEqual(AENA.offers_on(fixture("aena-convocatorias.html"), "2026-11-07"), [])

    def test_en_plazo_saca_las_plazas_del_titulo(self):
        offers = AENA.offers_on(fixture("aena-convocatorias.html"), "2026-07-05")
        first = next(o for o in offers if o.ref == "20260630")
        self.assertEqual(first.positions, 24)
        self.assertEqual((first.opens_on, first.deadline), ("2026-07-01", "2026-07-14"))

    def test_pagina_sin_bloques_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            parse_aena("<h1>Mantenimiento</h1>")
