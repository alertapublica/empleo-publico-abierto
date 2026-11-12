import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import emasesa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, procesos=None):
        self.procesos = procesos

    def get(self, url):
        if url == emasesa.CONCURSOS:
            return fixture("emasesa-concursos.html")
        return self.procesos or fixture("emasesa-procesos.html")


def at(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Emasesa(unittest.TestCase):
    def test_tabla_de_concursos(self):
        rows = emasesa.parse_concursos(fixture("emasesa-concursos.html"))
        self.assertEqual(rows[0], {"title": "CONCURSO PÚBLICO ESPECIALISTA EN DELINEACIÓN", "deadline": "2026-10-19"})
        self.assertEqual(rows[-1], {"title": "BOLSAS EXTERNAS EN VIGOR", "deadline": "2017-01-20"})

    def test_todo_cerrado_no_da_ofertas(self):
        self.assertEqual(emasesa.EmasesaSource(at(2026, 11, 12, 12, 0)).list_offers(Http()), [])

    def test_un_concurso_abierto_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError) as caught:
            emasesa.EmasesaSource(at(2026, 10, 19, 12, 0)).list_offers(Http())
        self.assertIn("ESPECIALISTA EN DELINEACIÓN", str(caught.exception))

    def test_un_proceso_de_seleccion_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            emasesa.EmasesaSource(at(2026, 11, 12, 12, 0)).list_offers(Http("<h1>Procesos selección</h1><table></table>"))

    def test_sin_tabla_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            emasesa.parse_concursos("<html><body>Mantenimiento</body></html>")

    def test_tabla_sin_filas_se_detiene(self):
        page = fixture("emasesa-concursos.html")
        header = page[:page.index("</tr>") + 5] + "</tbody></table></main></body></html>"
        with self.assertRaises(SourceLayoutError):
            emasesa.parse_concursos(header)


if __name__ == "__main__":
    unittest.main()
