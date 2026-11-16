import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import upf

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Http:
    """El listado real del 2026-11-15 (100 filas) y las dos fichas guardadas: LNI02/2026 y la Fundació UPF."""

    def __init__(self, listing=None):
        self.asked = []
        self.listing = listing or fixture("upf-ofertes-pas.html")

    def get(self, url):
        self.asked.append(url)
        if url == upf.PAGE:
            return self.listing
        if "/gestor-a-de-practiques-academiques-externes/" in url:
            return fixture("upf-ficha-fundacio.html")
        if "/tecnic-a-de-laboratori-docencia-recerca-sala-disseccio/" in url:
            return fixture("upf-ficha-lni02.html")
        raise AssertionError(f"petición inesperada: {url}")


LNI02 = ("https://www.upf.edu/web/personal/ofertes-pas/-/asset_publisher/IRiYJaUWRmJS/content/"
         "tecnic-a-de-laboratori-docencia-recerca-sala-disseccio/213063326/maximized")


class List(unittest.TestCase):
    def test_filas_con_codigo_titulo_tipo_plazas_y_plazo(self):
        rows = upf.parse_list(fixture("upf-ofertes-pas.html"))
        self.assertEqual(len(rows), 100)
        self.assertEqual(rows[2], {
            "ref": "tecnic-a-de-laboratori-docencia-recerca-sala-disseccio", "url": LNI02, "code": "LNI02/2026",
            "title": "Tècnic/a de Laboratori (6 places): Docència, Recerca i Sala de Dissecció",
            "type": "PTGAS laboral - concurs de nou ingrés", "positions": 6, "deadline": "2026-11-18",
        })
        self.assertEqual(rows[5]["code"], "Fundació UPF")
        self.assertEqual(rows[-1]["deadline"], "2025-05-11")

    def test_todos_los_tipos_son_conocidos(self):
        types = {row["type"] for row in upf.parse_list(fixture("upf-ofertes-pas.html"))}
        self.assertEqual(types - set(upf.LABORAL) - set(upf.EXCLUDED), set())

    def test_listado_vacio_o_fila_sin_plazo_detiene(self):
        with self.assertRaises(SourceLayoutError):
            upf.parse_list("<main><p>Res</p></main>")
        broken = fixture("upf-ofertes-pas.html").replace("<strong>18/11/2026</strong>", "<strong>Pendent</strong>")
        with self.assertRaises(SourceLayoutError):
            upf.parse_list(broken)


class Ficha(unittest.TestCase):
    def test_datos_y_fases(self):
        ficha = upf.parse_ficha(fixture("upf-ficha-lni02.html"))
        self.assertEqual(ficha["published_on"], "2026-11-03")
        self.assertIn("Règim jurídic: Laboral", ficha["data"])
        self.assertIn("Grup i nivell: 3 M", ficha["data"])
        self.assertEqual([(p["label"], p["day"]) for p in ficha["phases"]], [
            ("Convocatòria LNI02/2026", "2026-11-03"), ("Termini de presentació de sol·licituds", "2026-11-18"),
            ("Consultes", None)])
        self.assertIn("upf2.convoca.online", ficha["phases"][0]["html"])

    def test_fundacio(self):
        ficha = upf.parse_ficha(fixture("upf-ficha-fundacio.html"))
        self.assertEqual(ficha["published_on"], "2026-10-21")
        self.assertIn("/documents/d/wiarhio/", ficha["phases"][0]["html"])

    def test_ficha_sin_bloque_detiene(self):
        with self.assertRaises(SourceLayoutError):
            upf.parse_ficha("<main><p>Res</p></main>")


class Source(unittest.TestCase):
    def test_solo_laborales_en_plazo(self):
        # El 15/11: en plazo LNI02 (laboral, nuevo ingreso) y tres funcionariales «altres ofertes» (fuera).
        http = Http()
        offers = upf.UpfSource(now=at(11, 15)).list_offers(http)
        self.assertEqual([(o.code, o.company, o.positions, o.deadline, o.published_on) for o in offers],
                         [("LNI02/2026", "Universitat Pompeu Fabra", 6, "2026-11-18", "2026-11-03")])
        self.assertEqual(offers[0].title, "Tècnic/a de Laboratori (6 places): Docència, Recerca i Sala de Dissecció")
        self.assertEqual(http.asked, [upf.PAGE, LNI02])

    def test_fundacio_con_su_nombre_y_sin_codigo(self):
        # El 05/11 está en plazo la de la Fundació UPF (hasta el 08/11); la de traslado (05/11) queda fuera.
        offers = upf.UpfSource(now=at(11, 5)).list_offers(Http())
        found = {o.ref: o for o in offers}
        self.assertEqual(set(found), {"tecnic-a-de-laboratori-docencia-recerca-sala-disseccio",
                                      "gestor-a-de-practiques-academiques-externes"})
        fundacio = found["gestor-a-de-practiques-academiques-externes"]
        self.assertEqual((fundacio.company, fundacio.code), ("Fundació Universitat Pompeu Fabra", None))

    def test_detalle_en_catalan_con_municipio(self):
        source = upf.UpfSource(now=at(11, 15))
        offer = source.list_offers(Http())[0]
        detail = source.fetch_detail(Http(), offer)
        self.assertEqual(detail.location, "Barcelona")
        self.assertEqual([(s["title"], s["lang"]) for s in detail.sections], [("La convocatoria", "ca"), ("Fases", "ca")])
        self.assertIn("<strong>Termini de presentació de sol·licituds</strong>: 18 nov. 2026", detail.sections[1]["html"])

    def test_tipo_desconocido_en_plazo_detiene(self):
        listing = fixture("upf-ofertes-pas.html").replace(
            "PTGAS laboral - concurs de nou ingrés\n", "PTGAS laboral - concurs nou\n", 1)
        with self.assertRaises(SourceLayoutError):
            upf.UpfSource(now=at(11, 15)).list_offers(Http(listing))

    def test_ultima_fila_en_plazo_detiene(self):
        listing = fixture("upf-ofertes-pas.html").replace("<strong>11/05/2025</strong>", "<strong>11/05/2027</strong>")
        with self.assertRaises(SourceLayoutError):
            upf.UpfSource(now=at(11, 15)).list_offers(Http(listing))


if __name__ == "__main__":
    unittest.main()
