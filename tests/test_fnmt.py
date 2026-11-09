import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import fnmt

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
AVISO = (FIXTURES / "fnmt-aviso-oe-26-26.txt").read_text(encoding="utf-8")


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """26/26 en convocatoria; 25/26 (con la ficha de 07/26) ya en otras fases."""

    def __init__(self, fichas=None):
        self.urls = []
        self.fichas = fichas or {"12334086": "fnmt-oe-26-26.html"}

    def get(self, url):
        self.urls.append(url)
        if url == fnmt.PAGE:
            return fixture("fnmt-oep.html")
        return fixture(next((f for key, f in self.fichas.items() if url.endswith(key)), "fnmt-oe-07-26.html"))


def pdf(text=AVISO):
    return mock.patch.object(fnmt, "read_pdf", lambda http, url, what: text)


class Fnmt(unittest.TestCase):
    def test_listado_por_alta(self):
        rows = fnmt.parse_list(fixture("fnmt-oep.html"))
        self.assertEqual(len(rows), 20)
        self.assertEqual([r["title"][:8] for r in rows[:3]], ["OE 26/26", "OE 25/26", "FC 05/26"])

    def test_ficha(self):
        ficha = fnmt.parse_ficha(fixture("fnmt-oe-26-26.html"))
        self.assertEqual(ficha["contract"], "contrato laboral en la modalidad de fijo")
        self.assertEqual([(d["label"], d["date"].isoformat()) for d in ficha["documents"]],
                         [("Aviso de convocatoria", "2026-10-26"), ("Bases del proceso de selección", "2026-10-26")])

    def test_detalle_con_el_parrafo_de_la_ficha(self):
        http = Http()
        with pdf():
            (offer,) = fnmt.FnmtSource(NOW).list_offers(http)
        (section,) = fnmt.FnmtSource(NOW).fetch_detail(http, offer).sections
        self.assertEqual(section["title"], "Convocatoria")
        self.assertTrue(section["html"].startswith("<p><strong>La Fábrica Nacional de Moneda y Timbre"))
        self.assertIn("en el Departamento de Informática", section["html"])

    def test_solo_la_que_sigue_en_convocatoria(self):
        http = Http()
        with pdf():
            (offer,) = fnmt.FnmtSource(NOW).list_offers(http)
        self.assertEqual((offer.ref, offer.title, offer.deadline, offer.deadline_time, offer.published_on),
                         ("12334086", "OE 26/26 - Analista Senior", "2026-11-18", None, "2026-10-26"))
        self.assertEqual(offer.contract, "contrato laboral en la modalidad de fijo")
        self.assertEqual(len(http.urls), 3)  # listado, 26/26 y 25/26, donde para

    def test_plazo_vencido(self):
        late = datetime(2026, 11, 18, 23, 30, tzinfo=timezone.utc)
        with pdf():
            self.assertEqual(fnmt.FnmtSource(late).list_offers(Http()), [])

    def test_plazo_fuera_de_margen_no_se_ofrece(self):
        with pdf(AVISO.replace("de 2026.", "de 2027.")):
            self.assertEqual(fnmt.FnmtSource(NOW).list_offers(Http()), [])

    def test_si_todas_siguen_en_convocatoria_se_detiene(self):
        fichas = {str(r["id"]): "fnmt-oe-26-26.html" for r in fnmt.parse_list(fixture("fnmt-oep.html"))}
        with pdf(), self.assertRaises(SourceLayoutError):
            fnmt.FnmtSource(NOW).list_offers(Http(fichas))

    def test_sin_tabla_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fnmt.parse_list("<h1>Ofertas de Empleo Público</h1>")


if __name__ == "__main__":
    unittest.main()
