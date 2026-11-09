import unittest
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import sarga

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("sarga-especifico.html")


class Lectura(unittest.TestCase):
    def setUp(self):
        self.entries = sarga.parse_page(fixture("sarga-especifico.html"))

    def test_tarjetas_abiertas_y_cerradas(self):
        # Las cerradas llevan los botones en otra columna: también se leen.
        self.assertEqual(len(self.entries), 13)
        first = self.entries[0]
        self.assertEqual(first["title"], "TÉCNICO/A DE ASISTENCIAS DESARROLLO RURAL")
        self.assertEqual((first["published_on"], first["deadline"]), ("2026-10-30", "2026-11-12"))
        self.assertTrue(first["pdf"].endswith("31698_Perfil_T2C_T_Asist_des_rural.pdf"))

    def test_referencias_unicas_aunque_compartan_pdf(self):
        refs = [e["ref"] for e in self.entries]
        self.assertEqual(len(refs), len(set(refs)))
        self.assertGreater(len({e["pdf"] for e in self.entries}), 1)
        self.assertLess(len({e["pdf"] for e in self.entries}), len(self.entries))

    def test_pagina_desconocida(self):
        with self.assertRaises(SourceLayoutError):
            sarga.parse_page("<h1>Mantenimiento</h1>")

    def test_bases_con_hora_contrato_y_puestos(self):
        self.assertEqual(sarga.parse_bases(fixture("sarga-bases-asistencias.txt")), {
            "closing_day": "2026-11-12", "closing_time": "14:00", "contract": "Indefinido",
            "kind": "indefinido", "location": "Zaragoza", "positions": 4,
        })

    def test_dato_con_letras_cambiadas_no_se_guarda(self):
        bases = sarga.parse_bases(fixture("sarga-bases-alcaniz.txt"))
        self.assertIsNone(bases["location"])  # «Alcaæiz» en el PDF
        self.assertEqual((bases["contract"], bases["kind"]), ("Temporal, sustitución", "temporal"))


class Fuente(unittest.TestCase):
    def test_por_fecha_aunque_la_web_siga_ofreciendo_inscripcion(self):
        # El 8/11 la web aún enseñaba «Inscripción» en ofertas que cerraron el 3 y el 4.
        with mock.patch.object(sarga, "today_madrid", return_value="2026-11-08"):
            listed = sarga.SargaSource().list_offers(FakeHttp())
        self.assertEqual([o.title for o in listed], ["TÉCNICO/A DE ASISTENCIAS DESARROLLO RURAL"])

    def test_hora_de_cierre_solo_si_las_bases_dicen_el_mismo_dia(self):
        source = sarga.SargaSource()
        with mock.patch.object(sarga, "today_madrid", return_value="2026-11-08"):
            [offer] = source.list_offers(FakeHttp())
        with mock.patch.object(sarga, "read_pdf", return_value=fixture("sarga-bases-asistencias.txt")):
            detail = source.fetch_detail(None, offer)
            self.assertEqual((detail.deadline_time, detail.contract, detail.location), ("14:00", "Indefinido", "Zaragoza"))
            self.assertEqual(detail.positions, 4)
            offer.deadline = "2026-11-19"  # la web amplía el plazo y las bases no
            self.assertIsNone(source.fetch_detail(None, offer).deadline_time)

    def test_respeta_el_crawl_delay(self):
        self.assertEqual(sarga.SargaSource.delay, 10)
