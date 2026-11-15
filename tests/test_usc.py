import re
import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import usc

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Http:
    """Las dos primeras páginas reales del 2026-11-15 y las fichas reales de la 13/2026, la 11/2026, la urgente
    12/2026 y la próxima 14/2026. Otra ficha no está: si se pide, falla la prueba."""

    FICHAS = {"-132026-": "usc-ficha-13.html", "-112026-": "usc-ficha-11.html",
              "urxente-122026-": "usc-ficha-12-urxente.html", "-142026-": "usc-ficha-14-proxima.html"}

    def __init__(self, index=None, ficha=None):
        self.asked = []
        self.index = index or fixture("usc-convocatorias.html")
        self.ficha = ficha

    def get(self, url):
        self.asked.append(url)
        if url == usc.INDEX:
            return self.index
        if url == usc.INDEX + "?page=1":
            return fixture("usc-convocatorias-p1.html")
        name = next(name for part, name in self.FICHAS.items() if part in url)
        return self.ficha or fixture(name)


def without_card(html, number):
    """Pone «----» en la fecha de una tarjeta (como la próxima convocatoria) para que no sea candidata."""
    start = html.index(f"Ordinaria {number} de contratración")
    day = re.compile(r"\d{2}/\d{2}/\d{4}").search(html, start)
    return html[:day.start()] + "----" + html[day.end():]


class List(unittest.TestCase):
    def test_tarjetas(self):
        rows = usc.parse_list(fixture("usc-convocatorias.html"))
        self.assertEqual(len(rows), 12)
        self.assertEqual(rows[0], {
            "ref": "convocatoria-publica-ordinaria-132026-contratracion-persoal-colaborar-actividades-proxectos-investigacion",
            "url": "https://www.usc.gal/gl/investigar-na-usc/convocatorias/convocatoria-publica-ordinaria-132026-"
                   "contratracion-persoal-colaborar-actividades-proxectos-investigacion",
            "title": "Convocatoria Pública Ordinaria 13/2026 de contratración de persoal para colaborar nas actividades "
                     "e proxectos de investigación",
            "date": "2026-10-26",
        })
        self.assertIsNone(rows[3]["date"])  # «----»: la próxima, todavía sin plazo
        self.assertIsNone(usc.parse_list(fixture("usc-convocatorias-p1.html"))[5]["date"])  # «Proceso cancelado»

    def test_pagina_siguiente(self):
        self.assertEqual(usc.next_page(fixture("usc-convocatorias.html"), usc.INDEX), usc.INDEX + "?page=1")


class Ficha(unittest.TestCase):
    def test_ordinaria(self):
        ficha = usc.parse_ficha(fixture("usc-ficha-13.html"))
        self.assertEqual((ficha["published_on"], ficha["opens_on"], ficha["deadline"]),
                         ("2026-10-19", "2026-10-20", "2026-10-26"))
        self.assertEqual(ficha["apply_url"], "https://sede.usc.es/formularios/solicitudes/contratacion.htm")
        self.assertEqual([label for label, _ in ficha["documents"]], [
            "Convocatoria ordinaria. Data publicación: 19/10/2026. O prazo de presentación de solicitudes dende o "
            "20/10/2026 ata o 26/10/2026",
            "Corrección erros praza 2026-CE020. Data publicación: 20/10/2026",
            "Cambio comisión 2023-PN093. Data publicación: 04/11/2026",
        ])  # sin las listas de admitidos

    def test_urgente_manda_el_documento_y_no_el_campo(self):
        ficha = usc.parse_ficha(fixture("usc-ficha-12-urxente.html"))  # el campo dice 10/09/2026
        self.assertEqual((ficha["published_on"], ficha["opens_on"], ficha["deadline"]), ("2026-09-09", None, "2026-09-14"))

    def test_campo_fuera_del_plazo_detiene(self):
        html = fixture("usc-ficha-13.html").replace("<dd>26/10/2026</dd>", "<dd>27/10/2026</dd>")
        with self.assertRaises(SourceLayoutError):
            usc.parse_ficha(html)

    def test_correccion_que_amplia_el_plazo_detiene(self):
        html = fixture("usc-ficha-13.html").replace(
            "Corrección erros praza 2026-CE020.",
            "Corrección erros praza 2026-CE020. O prazo de presentación de solicitudes dende o día 21/10/2026 ata o 30/10/2026.")
        with self.assertRaises(SourceLayoutError):
            usc.parse_ficha(html)

    def test_inicio_despues_del_fin_detiene(self):
        html = fixture("usc-ficha-13.html").replace("dende o 20/10/2026", "dende o 27/10/2026")
        with self.assertRaises(SourceLayoutError):
            usc.parse_ficha(html)

    def test_plazo_de_tarjeta_desconocido_detiene(self):
        html = fixture("usc-convocatorias.html").replace("26/10/2026", "26/10/2026 23:59", 1)
        with self.assertRaises(SourceLayoutError):
            usc.parse_list(html)

    def test_proxima_sin_plazo_detiene(self):
        with self.assertRaises(SourceLayoutError):
            usc.parse_ficha(fixture("usc-ficha-14-proxima.html"))


class Source(unittest.TestCase):
    def test_tanda_en_plazo(self):
        http = Http()
        offers = usc.UscSource(now=at(10, 22)).list_offers(http)
        self.assertEqual([(o.ref[:37], o.published_on, o.opens_on, o.deadline, o.kind) for o in offers],
                         [("convocatoria-publica-ordinaria-132026", "2026-10-19", "2026-10-20", "2026-10-26", None)])
        self.assertEqual(offers[0].title, "Convocatoria Pública Ordinaria 13/2026 de contratración de persoal para "
                                          "colaborar nas actividades e proxectos de investigación")
        self.assertEqual(offers[0].apply_url, "https://sede.usc.es/formularios/solicitudes/contratacion.htm")
        # También se abre la de la 11/2026 (01/10, de los últimos 30 días), ya vencida.
        self.assertEqual(http.asked[:3], [usc.INDEX, usc.INDEX + "?page=1", offers[0].url])
        self.assertEqual(len(http.asked), 4)

    def test_urgente_abierta_aunque_el_campo_haya_pasado(self):
        index = fixture("usc-convocatorias.html")
        for number in ("13/2026", "11/2026", "10/2026"):  # aún no existían el 12/09 (y la 10/2026 no tiene ficha aquí)
            index = without_card(index, number)
        offers = usc.UscSource(now=at(9, 12)).list_offers(Http(index=index))
        self.assertEqual([(o.deadline, o.opens_on) for o in offers], [("2026-09-14", None)])

    def test_hoy_ninguna(self):
        http = Http()
        self.assertEqual(usc.UscSource(now=at(11, 15)).list_offers(http), [])
        self.assertEqual(http.asked[:2], [usc.INDEX, usc.INDEX + "?page=1"])
        self.assertEqual(len(http.asked), 3)  # la ficha de la 13/2026 (26/10), vencida

    def test_ficha_en_gallego(self):
        source = usc.UscSource(now=at(10, 22))
        http = Http()
        detail = source.fetch_detail(http, source.list_offers(http)[0])
        self.assertEqual([(s["title"], s["lang"]) for s in detail.sections], [("La convocatoria", "gl"), ("Documentos", "gl")])
        self.assertIn("O obxecto da presente convocatoria", detail.sections[0]["html"])
        self.assertIn('href="https://assets.usc.gal/', detail.sections[1]["html"])
        self.assertEqual(len(http.asked), 4)  # listado (2), fichas 13 y 11: la de la 13 no se repite

    def test_lee_dos_paginas_aunque_la_primera_sea_antigua(self):
        old = fixture("usc-convocatorias-p1.html")
        class Swapped(Http):
            def get(self, url):
                self.asked.append(url)
                if url == usc.INDEX:
                    return old.replace('href="?page=2"', 'href="?page=1"')
                if url == usc.INDEX + "?page=1":
                    return fixture("usc-convocatorias.html").replace('href="?page=1"', 'href="?page=2"')
                if url == usc.INDEX + "?page=2":
                    return old.replace('rel="next"', "")
                return fixture("usc-ficha-11.html" if "-112026-" in url else "usc-ficha-13.html")
        http = Swapped()
        offers = usc.UscSource(now=at(10, 22)).list_offers(http)
        self.assertEqual([o.deadline for o in offers], ["2026-10-26"])

    def test_demasiadas_paginas_detiene(self):
        class Endless(Http):
            def get(self, url):
                self.asked.append(url)
                return fixture("usc-convocatorias.html")
        with self.assertRaises(SourceLayoutError):
            usc.UscSource(now=at(11, 15)).list_offers(Endless())


if __name__ == "__main__":
    unittest.main()
