import re
import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import iisaragon

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Listado real; toda entrada devuelve la ficha real de RRHH-26/049 (fin: 13/11/2026 23:59)."""

    def __init__(self):
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        if url == iisaragon.PAGE:
            return fixture("iisaragon-empleo.html")
        if "/page/" in url:  # la página 2: las mismas entradas, un año antes
            return re.sub(r"(\d{2}-\d{2})-2026", r"\1-2025", fixture("iisaragon-empleo.html"))
        return fixture("iisaragon-ficha.html")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def test_entradas_con_referencia_y_avisos_sin_ella(self):
        rows = iisaragon.parse_page(fixture("iisaragon-empleo.html"))
        self.assertEqual(len(rows), 10)
        self.assertIsNone(rows[0]["ref"])  # aviso general de las comisiones
        self.assertEqual((rows[1]["ref"], rows[1]["published"]), ("RRHH-26/049", date(2026, 10, 22)))


class Detail(unittest.TestCase):
    def test_plazo_con_hora_y_sin_formulario(self):
        detail = iisaragon.parse_detail(fixture("iisaragon-ficha.html"))
        self.assertEqual((detail["opens_on"], detail["deadline"], detail["deadline_time"]),
                         ("2026-10-22", "2026-11-13", "23:59"))
        html = detail["sections"][0]["html"]
        self.assertIn("RRHH-26/049", html)
        self.assertNotIn("Curriculum", html)

    def test_sin_plazo_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            iisaragon.parse_detail('<div class="the_content_wrapper"><p>Texto</p></div>')


class Source(unittest.TestCase):
    def test_lee_solo_las_entradas_recientes_con_referencia(self):
        http = Http()
        offers = iisaragon.IisAragonSource(now=at(11, 11)).list_offers(http)
        # Últimos 60 días (desde el 12/9): las nueve con referencia de la página 1; la última entrada es
        # del 30/9, dentro del margen, así que se mira la 2, que ya es de 2025. El aviso no se lee.
        self.assertEqual(len(http.asked), 2 + 9)
        self.assertEqual(len({o.ref for o in offers}), 9)
        source = iisaragon.IisAragonSource(now=at(11, 11))
        offer = source.list_offers(Http())[0]
        labels = source.labels(offer.title, offer.ref)
        self.assertEqual((labels["title"], labels["code"]), ("Director/a Ejecutivo/a", "RRHH-26/049"))
        self.assertEqual((offer.deadline, offer.deadline_time), ("2026-11-13", "23:59"))

    def test_hora_de_una_cifra(self):
        html = fixture("iisaragon-ficha.html").replace("23:59 horas del viernes", "9:00 horas del viernes")
        self.assertEqual(iisaragon.parse_detail(html)["deadline_time"], "09:00")

    def test_pasada_la_hora_ya_no_es_oferta(self):
        self.assertEqual(iisaragon.IisAragonSource(now=at(11, 13, 23)).list_offers(Http()), [])  # 00:00 del 14


if __name__ == "__main__":
    unittest.main()
