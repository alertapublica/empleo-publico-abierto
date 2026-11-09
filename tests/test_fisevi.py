import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import fisevi

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, entries=None):
        self.urls = []
        self.entries = entries or {"297-26": "fisevi-abierta.html", "296-26": "fisevi-anio-equivocado.html"}

    def get(self, url):
        self.urls.append(url)
        if url.startswith(fisevi.API):
            return fixture("fisevi-posts.json")
        name = next((f for key, f in self.entries.items() if key in url), "fisevi-cerrada.html")
        return fixture(name)


class Fisevi(unittest.TestCase):
    def test_listado_de_la_api(self):
        posts = fisevi.parse_posts(fixture("fisevi-posts.json"))
        self.assertEqual(len(posts), 4)
        self.assertEqual((posts[0]["ref"], posts[0]["published_on"]), ("18518", "2026-11-04"))
        self.assertTrue(posts[0]["title"].startswith("Titulación Universitaria de la rama de Ciencias"))

    def test_plazo_y_contrato_literal(self):
        e = fisevi.parse_entry(fixture("fisevi-abierta.html"))
        self.assertEqual((e["deadline"].isoformat(), e["deadline_time"]), ("2026-11-13", "23:59"))
        self.assertTrue(e["contract"].startswith("Contrato indefinido de actividades científico-técnicas (art. 23 bis"))

    def test_solo_la_abierta_y_se_descarta_el_anio_equivocado(self):
        http = Http()
        (offer,) = fisevi.FiseviSource(NOW).list_offers(http)
        self.assertEqual((offer.ref, offer.deadline, offer.deadline_time, offer.published_on, offer.kind),
                         ("18518", "2026-11-13", "23:59", "2026-11-04", None))
        self.assertEqual(len(http.urls), 5)
        self.assertTrue(http.urls[0].endswith("after=2026-10-24T00:00:00"))

    def test_plazo_demasiado_lejano_no_se_ofrece(self):
        page = fixture("fisevi-abierta.html").replace("de 2026.", "de 2027.")
        self.assertEqual(fisevi.FiseviSource(NOW).list_offers(_Pages(page)), [])

    def test_anulada_no_se_ofrece(self):
        page = fixture("fisevi-abierta.html").replace("Descargar CV", "Resolución anulación convocatoria")
        self.assertIsNone(fisevi.parse_entry(page))

    def test_cierra_a_su_hora(self):
        late = datetime(2026, 11, 13, 22, 59, tzinfo=timezone.utc)  # 23:59 en Madrid
        self.assertEqual(fisevi.FiseviSource(late).list_offers(Http()), [])

    def test_sin_la_frase_del_plazo_se_detiene(self):
        page = fixture("fisevi-abierta.html").replace("Antes de las", "Hasta las")
        with self.assertRaises(SourceLayoutError):
            fisevi.FiseviSource(NOW).list_offers(_Pages(page))

    def test_api_cambiada_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fisevi.parse_posts('{"code": "rest_no_route"}')


class _Pages:
    """Todas las entradas con la misma página."""

    def __init__(self, page):
        self.page = page

    def get(self, url):
        return fixture("fisevi-posts.json") if url.startswith(fisevi.API) else self.page


if __name__ == "__main__":
    unittest.main()
