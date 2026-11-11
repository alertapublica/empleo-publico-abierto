import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import veiasa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Listado real; toda convocatoria devuelve la real de los 55 inspectores (hasta el 11/11/2026 23:59)."""

    def __init__(self):
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        return fixture("veiasa-seleccion.html" if url == veiasa.PAGE else "veiasa-55-inspectores.html")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def test_solo_los_abiertos(self):
        rows = veiasa.parse_page(fixture("veiasa-seleccion.html"))
        self.assertEqual(len(rows), 8)
        self.assertTrue(rows[0]["title"].startswith("CONVOCATORIA DEL PROCESO DE SELECCIÓN PARA LA COBERTURA DE 55"))
        self.assertNotIn("?", rows[0]["url"])

    def test_sin_listas_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            veiasa.parse_page("<main>Selección de personal</main>")


class Deadline(unittest.TestCase):
    def test_las_formas_reales(self):
        casos = {
            "el plazo permanecerá abierto desde el 21 de octubre hasta el 11 de noviembre de 2026, a las 23:59 horas":
                (date(2026, 11, 11), "23:59"),
            "El plazo comenzará a las 00:00 horas del día 16 de abril de 2025 y finalizará a las 23:59 horas del día 2 de mayo de 2025.":
                (date(2025, 5, 2), "23:59"),
            "el nuevo plazo de presentación de solicitudes finaliza el 7 de mayo de 2025 a las 23:59 horas .":
                (date(2025, 5, 7), "23:59"),
            "El plazo de presentación de solicitudes permanecerá abierto hasta el DOMINGO 3 DE MAYO DE 2026 A LAS 23:59 HORAS .":
                (date(2026, 5, 3), "23:59"),
        }
        for text, expected in casos.items():
            self.assertEqual(veiasa.deadline_of(text), expected, text)

    def test_otros_plazos_no_cuentan(self):
        text = ("Se abre un plazo de 3 días hábiles siguientes a la fecha de publicación de este listado "
                "provisional, publicado el 20 de noviembre de 2026.")
        self.assertEqual(veiasa.deadline_of(text), (None, None))


class Source(unittest.TestCase):
    def test_sin_llamamientos_internos(self):
        http = Http()
        offers = veiasa.VeiasaSource(now=at(11, 11)).list_offers(http)
        asked = [u for u in http.asked if u != veiasa.PAGE]
        self.assertFalse(any("llamamiento" in u for u in asked))
        self.assertEqual(len(asked), 6)
        self.assertEqual((offers[0].deadline, offers[0].deadline_time), ("2026-11-11", "23:59"))

    def test_pasada_la_hora_no_hay_ofertas(self):
        self.assertEqual(veiasa.VeiasaSource(now=at(11, 11, 23)).list_offers(Http()), [])  # 00:00 del 12


if __name__ == "__main__":
    unittest.main()
