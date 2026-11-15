import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import emacsa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Portada real del 2026-11-15; la 17 (cerrada) y la 28 (abierta) son reales, el resto copia la 28."""

    def __init__(self, page=None):
        self.asked, self.page = [], page

    def get(self, url):
        self.asked.append(url)
        if url == emacsa.PAGE:
            return self.page or fixture("emacsa-portada.html")
        return fixture("emacsa-ficha-cerrada.html" if url.endswith(("/17", "/18")) else "emacsa-ficha-abierta.html")


def at(month, day, year=2026):
    return datetime(year, month, day, 10, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def test_cinco_convocatorias_tambien_las_cerradas(self):
        rows = emacsa.parse_page(fixture("emacsa-portada.html"))
        self.assertEqual([r["ref"] for r in rows], ["28", "25", "27", "17", "18"])
        self.assertEqual((rows[0]["title"], rows[0]["period"]), ("Auxiliar Técnico Operaciones", "04 de noviembre - 30 de noviembre"))
        self.assertEqual(rows[0]["apply_url"], "https://cuestionarios.emacsa.es/inscripciones/28")

    def test_la_cerrada_toma_su_numero_del_menu(self):
        closed = emacsa.parse_page(fixture("emacsa-portada.html"))[3]
        self.assertEqual((closed["ref"], closed["apply_url"]), ("17", None))
        self.assertEqual(closed["url"], "https://cuestionarios.emacsa.es/convocatoria/17")

    def test_sin_tarjetas_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            emacsa.parse_page("<p>Ofertas de Empleo</p>")

    def test_mes_desconocido_detiene_la_fuente(self):
        html = fixture("emacsa-portada.html").replace("04 de noviembre", "04 de nobiembre")
        with self.assertRaises(SourceLayoutError):
            emacsa.parse_page(html)


class Detail(unittest.TestCase):
    def test_apartados_con_su_fecha(self):
        sections = emacsa.parse_detail(fixture("emacsa-ficha-cerrada.html"))
        self.assertEqual(len(sections), 7)
        self.assertEqual((sections[0]["title"], sections[0]["date"]), ("Convocatoria y bases", "2026-07-30"))
        self.assertEqual(sections[3]["date"], "2026-10-26")
        self.assertEqual(len(sections[3]["documents"]), 4)
        self.assertIn("ambos incluidos en el temario", sections[1]["text"])

    def test_sin_apartados_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            emacsa.parse_detail("<div class='container convocatoria'><h3>Auxiliar</h3></div>")


class Dates(unittest.TestCase):
    def test_el_año_lo_da_la_publicacion(self):
        row = {"start": (4, 11), "end": (30, 11)}
        self.assertEqual(emacsa.dates(row, "2026-11-03"), ("2026-11-04", "2026-11-30"))

    def test_plazo_que_cruza_el_año(self):
        self.assertEqual(emacsa.dates({"start": (20, 12), "end": (15, 1)}, "2026-12-19"), ("2026-12-20", "2027-01-15"))
        self.assertEqual(emacsa.dates({"start": (2, 1), "end": (20, 1)}, "2026-12-30"), ("2027-01-02", "2027-01-20"))


class Source(unittest.TestCase):
    def test_tres_abiertas_con_plazas_y_plazo(self):
        http = Http()
        offers = emacsa.EmacsaSource(now=at(11, 15)).list_offers(http)
        self.assertEqual(len(http.asked), 1 + 5)
        self.assertEqual([o.ref for o in offers], ["28", "25", "27"])
        first = offers[0]
        self.assertEqual((first.positions, first.opens_on, first.deadline, first.published_on),
                         (3, "2026-11-04", "2026-11-30", "2026-11-03"))
        self.assertEqual(first.apply_url, "https://cuestionarios.emacsa.es/inscripciones/28")
        self.assertIsNone(first.kind)

    def test_manda_la_fecha_y_no_la_etiqueta(self):
        # La portada dice «abierto», pero el plazo de la 28 acaba el 30/11.
        self.assertEqual(emacsa.EmacsaSource(now=at(12, 1)).list_offers(Http()), [])

    def test_ficha_con_plazo_y_bases(self):
        source = emacsa.EmacsaSource(now=at(11, 15))
        offer = source.list_offers(Http())[0]
        detail = source.fetch_detail(Http(), offer)
        self.assertEqual(detail.location, "Córdoba")
        self.assertEqual([s["title"] for s in detail.sections], ["Plazo de inscripción", "La convocatoria", "Convocatoria y bases"])
        self.assertIn("DescargarDoc.aspx", detail.sections[2]["html"])

    def test_enlaces_saneados(self):
        html = fixture("emacsa-ficha-abierta.html").replace("href='/convocatorias/", "href='javascript:alert(1)//")

        class Bad(Http):
            def get(self, url):
                return fixture("emacsa-portada.html") if url == emacsa.PAGE else html

        source = emacsa.EmacsaSource(now=at(11, 15))
        offer = source.list_offers(Bad())[0]
        self.assertNotIn("javascript:", " ".join(s["html"] for s in source.fetch_detail(Bad(), offer).sections))

    def test_cerrado_el_plazo_sus_apartados_son_comunicados(self):
        notices = emacsa.EmacsaSource(now=at(11, 15)).list_announcements(Http())
        mine = [n for n in notices if n.process_url.endswith("/17")]
        self.assertEqual(len(mine), 7)
        self.assertEqual((mine[2].date, mine[2].title), ("2026-10-02", "Lista provisional de personas admitidas y excluidas"))
        # Se enlaza la ficha, no los documentos (hay listas de personas).
        self.assertTrue(all(n.url == n.process_url for n in notices))
        self.assertFalse(any(n.process_url.endswith("/28") for n in notices))


if __name__ == "__main__":
    unittest.main()
