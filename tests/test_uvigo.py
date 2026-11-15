import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import uvigo

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Http:
    """El taboleiro «Investigar» real del 2026-11-15 y las fichas del 14/26 (abierto) y del 13/26 (cerrado)."""

    def __init__(self, index=None, ficha=None):
        self.asked = []
        self.index = index or fixture("uvigo-investigar.html")
        self.ficha = ficha

    def get(self, url):
        self.asked.append(url)
        if url == uvigo.INDEX:
            return self.index
        if self.ficha:
            return self.ficha
        return fixture("uvigo-ficha-1426.html" if url.endswith("/1955") else "uvigo-ficha-1326.html")


class List(unittest.TestCase):
    def test_tarjetas(self):
        rows = uvigo.parse_list(fixture("uvigo-investigar.html"))
        self.assertEqual(len(rows), 20)
        self.assertEqual(rows[1], {
            "ref": "1955", "url": "https://secretaria.uvigo.gal/uv/web/convocatoria/public/show/1955",
            "title": "CONCURSO PÚBLICO DE MÉRITOS 14/26 PARA A CONTRATACIÓN DE PERSOAL DE INVESTIGACIÓN",
            "own": True, "opens_on": "2026-11-05", "deadline": "2026-11-18",
        })
        self.assertFalse(rows[2]["own"])  # convoca el Ministerio

    def test_vacio_detiene(self):
        with self.assertRaises(SourceLayoutError):
            uvigo.parse_list("<main><p>Nada</p></main>")


class Ficha(unittest.TestCase):
    def test_abierta(self):
        ficha = uvigo.parse_ficha(fixture("uvigo-ficha-1426.html"), "https://secretaria.uvigo.gal/x")
        self.assertEqual((ficha["code"], ficha["opens_on"], ficha["deadline"], ficha["deadline_time"]),
                         ("14/26_CONC", "2026-11-05", "2026-11-18", "23:59"))
        self.assertEqual(ficha["apply_url"], "https://sede.uvigo.gal/public/catalog-detail/27660208")
        self.assertEqual([title for title, _ in ficha["sections"]], ["Descripción", "Requisitos", "Documentación"])
        self.assertEqual([label for label, _ in ficha["documents"]], ["Bases do concurso", "Declaración responsable editable"])

    def test_hora_en_observaciones(self):
        ficha = uvigo.parse_ficha(fixture("uvigo-ficha-1326.html"), "https://secretaria.uvigo.gal/x")
        self.assertEqual((ficha["deadline"], ficha["deadline_time"]), ("2026-10-21", "23:59"))
        self.assertIn("Observaciones", [title for title, _ in ficha["sections"]])

    def test_hora_de_otro_dia_detiene(self):
        html = fixture("uvigo-ficha-1426.html").replace("23:59 horas do 18 de novembro", "23:59 horas do 19 de novembro")
        with self.assertRaises(SourceLayoutError):
            uvigo.parse_ficha(html, "https://secretaria.uvigo.gal/x")

    def test_sin_fechas_detiene(self):
        html = fixture("uvigo-ficha-1426.html").replace("Data fin solicitudes", "Fin")
        with self.assertRaises(SourceLayoutError):
            uvigo.parse_ficha(html, "https://secretaria.uvigo.gal/x")


class Source(unittest.TestCase):
    def test_solo_el_concurso_en_plazo(self):
        http = Http()
        offers = uvigo.UvigoSource(now=at(11, 15)).list_offers(http)
        self.assertEqual([(o.ref, o.deadline, o.deadline_time, o.opens_on, o.code) for o in offers],
                         [("1955", "2026-11-18", "23:59", "2026-11-05", "14/26_CONC")])
        self.assertEqual(offers[0].apply_url, "https://sede.uvigo.gal/public/catalog-detail/27660208")
        self.assertEqual(http.asked, [uvigo.INDEX, offers[0].url])  # FPI, Juan de la Cierva…: ni se abren

    def test_cerrado_al_dia_siguiente(self):
        self.assertEqual(uvigo.UvigoSource(now=datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)).list_offers(Http()), [])

    def test_ficha_en_gallego_y_sin_fases_posteriores(self):
        source = uvigo.UvigoSource(now=at(11, 15))
        http = Http()
        offer = source.list_offers(http)[0]
        detail = source.fetch_detail(http, offer)
        self.assertEqual([s["title"] for s in detail.sections], ["Descripción", "Requisitos", "Documentación", "Documentos"])
        self.assertTrue(all(s["lang"] == "gl" for s in detail.sections))
        self.assertIn("Bases do concurso", detail.sections[-1]["html"])
        self.assertEqual(len(http.asked), 2)  # la ficha ya leída en el listado no se repite

    def test_plazo_distinto_en_tarjeta_y_ficha_detiene(self):
        ficha = fixture("uvigo-ficha-1426.html").replace("05/11/2026", "06/11/2026")
        with self.assertRaises(SourceLayoutError):
            uvigo.UvigoSource(now=at(11, 15)).list_offers(Http(ficha=ficha))

    def test_ultima_tarjeta_en_plazo_detiene(self):
        index = fixture("uvigo-investigar.html").replace("25/03/2026 - 15/04/2026", "25/03/2026 - 15/12/2026")
        with self.assertRaises(SourceLayoutError):
            uvigo.UvigoSource(now=at(11, 15)).list_offers(Http(index=index))


if __name__ == "__main__":
    unittest.main()
