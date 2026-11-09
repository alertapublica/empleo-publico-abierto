import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import canal

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, page=None):
        self.urls = []
        self.page = page or fixture("canal-puestos.html")

    def get(self, url):
        self.urls.append(url)
        if url == canal.PAGE:
            return self.page
        return fixture("canal-calendario.html") if url.endswith("-251") else "<table><tr><td>Admisión de solicitudes</td><td>03/09/2026</td><td>17/09/2026</td></tr></table>"


class Canal(unittest.TestCase):
    def test_filas_de_la_tabla(self):
        rows = canal.parse_list(fixture("canal-puestos.html"))
        self.assertEqual(len(rows), 22)
        self.assertEqual((rows[0]["ref"], rows[0]["title"], rows[0]["published_on"]),
                         ("G00472026", "Titulado/a superior Depuración", "2026-10-07"))
        self.assertEqual(rows[0]["calendar"], canal.HOST + "/calendario-251")

    def test_admision_del_calendario(self):
        self.assertEqual(canal.parse_calendar(fixture("canal-calendario.html")), ("2026-10-07", "2026-10-26"))

    def test_solo_las_recientes_y_en_plazo(self):
        http = Http()
        (offer,) = canal.CanalSource(NOW).list_offers(http)
        self.assertEqual((offer.ref, offer.opens_on, offer.deadline, offer.deadline_time, offer.kind),
                         ("G00472026", "2026-10-07", "2026-10-26", None, None))
        self.assertEqual(len(http.urls), 4)  # tabla y las tres de los últimos 60 días

    def test_hoy_ninguna(self):
        now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
        self.assertEqual(canal.CanalSource(now).list_offers(Http()), [])

    def test_demasiadas_recientes_se_detiene(self):
        with mock.patch.object(canal, "MAX_CALENDARS", 2), self.assertRaises(SourceLayoutError):
            canal.CanalSource(NOW).list_offers(Http())

    def test_sin_tabla_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            canal.parse_list("<p>Procesos selectivos</p>")


if __name__ == "__main__":
    unittest.main()
