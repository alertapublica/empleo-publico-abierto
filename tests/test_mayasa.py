import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import mayasa

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 5, 20, 12, 0, tzinfo=timezone.utc)
PDF = (FIXTURES / "mayasa-convocatoria.txt").read_text(encoding="utf-8")
FICHA = "https://mayasa.es/trabaja-con-nosotros/administrativo-a-del-area-de-recursos-humanos/"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        return fixture("mayasa-empleo.html") if url == mayasa.PAGE else fixture("mayasa-ficha.html")


def pdf(text=PDF):
    return mock.patch.object(mayasa, "read_pdf", lambda http, url, what: text)


class Mayasa(unittest.TestCase):
    def test_procesos_del_listado(self):
        rows = mayasa.parse_page(fixture("mayasa-empleo.html"))
        self.assertEqual(len(rows), 5)
        first, last = rows[0], rows[-1]
        self.assertEqual((first["ref"], first["published_on"], first["deadline"], first["contract"], first["place"]),
                         ("administrativo-a-del-area-de-recursos-humanos", "2026-05-13", "2026-05-27", None,
                          "Almadén (Ciudad Real)"))
        self.assertEqual(last["contract"], "Indefinido")

    def test_pdf_de_la_convocatoria(self):
        self.assertTrue(mayasa.convocatoria(fixture("mayasa-ficha.html")).endswith(
            "Convocatoria-Administrativo-RRHH-13-mayo-2026.pdf"))

    def test_hora_solo_si_es_el_dia_del_cierre(self):
        self.assertEqual(mayasa.hour_for(PDF, "2026-05-27"), "23:59")
        self.assertIsNone(mayasa.hour_for(PDF, "2026-05-28"))

    def test_abierta_con_su_hora(self):
        http = Http()
        with pdf():
            (offer,) = mayasa.MayasaSource(NOW).list_offers(http)
        self.assertEqual((offer.ref, offer.deadline, offer.deadline_time, offer.published_on, offer.kind),
                         ("administrativo-a-del-area-de-recursos-humanos", "2026-05-27", "23:59", "2026-05-13", None))
        self.assertEqual(http.urls, [mayasa.PAGE, FICHA])

    def test_hoy_todas_cerradas(self):
        http = Http()
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(mayasa.MayasaSource(now).list_offers(http), [])
        self.assertEqual(http.urls, [mayasa.PAGE])

    def test_sin_procesos_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            mayasa.parse_page("<h1>Ofertas de Empleo</h1>")


if __name__ == "__main__":
    unittest.main()
