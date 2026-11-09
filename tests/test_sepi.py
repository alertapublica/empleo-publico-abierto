import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import sepi

FIXTURES = Path(__file__).parent / "fixtures"
DOS_PUESTOS = "https://www.sepi.es/es/empleo-publico/convocatoria-de-proceso-de-seleccion-para-la-cobertura-de-dos-puestos-de-personal"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, page):
        self.page, self.urls = page, []

    def get(self, url):
        self.urls.append(url)
        return fixture(self.page) if url == sepi.PAGE else fixture("sepi-ficha.html")


def offers(page, now):
    http = Http(page)
    return sepi.SepiSource(now).list_offers(http), http


class Sepi(unittest.TestCase):
    def test_listado(self):
        rows = sepi.parse_page(fixture("sepi-empleo.html"))
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0]["ref"], "convocatoria-de-proceso-de-seleccion-para-la-cobertura-de-15-puestos-de-personal")
        self.assertTrue(rows[0]["title"].startswith("CONVOCATORIA DE PROCESO DE SELECCIÓN PARA LA COBERTURA DE 15 PUESTOS"))
        self.assertEqual(rows[0]["status"], "Concluido el plazo de presentación de candidaturas.")

    def test_frases_del_plazo(self):
        cases = {
            "El plazo de presentación de candidaturas finaliza el 1 de junio de 2026 a las 23.59 horas.":
                ("2026-06-01", "23:59"),
            "El plazo de presentación de candidaturas finalizará a las 23.59 horas del día 27 de enero de 2026.":
                ("2026-01-27", "23:59"),
            "El plazo de presentación de solicitudes finaliza el 30 de junio de 2025 a las 23.59 horas.":
                ("2025-06-30", "23:59"),
            "El plazo de presentación de solicitudes finaliza el 30 de junio de 2025.": ("2025-06-30", None),
            # Otras fases: no son ofertas.
            "Concluido el plazo de presentación de candidaturas.": (None, None),
            "El plazo para reclamar finaliza el 14 de noviembre de 2025, a las 23.59 horas.": (None, None),
            "El plazo para presentar alegaciones para el puesto de la Dirección de Personas - Perfil B "
            "finaliza el 20 de mayo a las 23.59 horas.": (None, None),
            # Sin año no se adivina.
            "El plazo de presentación de candidaturas finaliza el 1 de junio a las 23.59 horas.": (None, None),
            # La hora de otra frase no se toma.
            "El plazo de presentación de candidaturas finaliza el 1 de junio de 2026. "
            "El plazo para reclamar acaba a las 14.00 horas.": ("2026-06-01", None),
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(sepi.deadline_of(text), expected)

    def test_dos_plazos_de_candidaturas_distintos(self):
        with self.assertRaises(SourceLayoutError):
            sepi.deadline_of("El plazo de presentación de candidaturas finaliza el 1 de junio de 2026. "
                             "El plazo de presentación de candidaturas finaliza el 8 de junio de 2026.")

    def test_abierta_entre_otras_fases(self):
        (offer,), http = offers("sepi-empleo-2026-05.html", datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc))
        self.assertEqual((offer.ref, offer.url, offer.deadline, offer.deadline_time, offer.kind, offer.published_on),
                         (DOS_PUESTOS.rsplit("/", 1)[-1], DOS_PUESTOS, "2026-06-01", "23:59", None, None))
        self.assertEqual(http.urls, [sepi.PAGE])

    def test_dos_abiertas_y_una_en_reclamaciones(self):
        found, _ = offers("sepi-empleo-2025-06.html", datetime(2025, 6, 24, 12, 0, tzinfo=timezone.utc))
        self.assertEqual([(o.deadline, o.deadline_time) for o in found], [("2025-06-30", "23:59")] * 2)
        self.assertEqual(len({o.ref for o in found}), 2)

    def test_cierra_a_la_hora(self):
        page = "sepi-empleo-2026-01.html"
        self.assertEqual(len(offers(page, datetime(2026, 1, 27, 22, 58, tzinfo=timezone.utc))[0]), 1)
        self.assertEqual(offers(page, datetime(2026, 1, 27, 23, 0, tzinfo=timezone.utc))[0], [])

    def test_hoy_ninguna_abierta(self):
        self.assertEqual(offers("sepi-empleo.html", datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc))[0], [])

    def test_ficha(self):
        source = sepi.SepiSource(datetime(2026, 5, 19, 12, 0, tzinfo=timezone.utc))
        http = Http("sepi-empleo-2026-05.html")
        (offer,) = source.list_offers(http)
        detail = source.fetch_detail(http, offer)
        self.assertEqual([s["title"] for s in detail.sections], ["Plazo", "Documentos de la convocatoria"])
        self.assertIn("finaliza el 1 de junio de 2026 a las 23.59 horas", detail.sections[0]["html"])
        documents = sepi.documents(fixture("sepi-ficha.html"))
        self.assertEqual(len(documents), 5)
        self.assertEqual(documents[0], ("Bases convocatoria", "https://www.sepi.es/sites/default/files/2026-04/"
                                        "bases_movilidad_interadministrativa_sepi_2026_web_sepi.pdf"))

    def test_pagina_cambiada(self):
        with self.assertRaises(SourceLayoutError):
            sepi.parse_page("<html><body><p>Nada</p></body></html>")


if __name__ == "__main__":
    unittest.main()
