import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import tmb

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def get(self, url):
        return fixture("tmb-ofertes.html" if url == tmb.PAGE else "tmb-ficha.html")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def test_tarjetas_con_plazo_y_referencia(self):
        rows = tmb.parse_page(fixture("tmb-ofertes.html"))
        self.assertEqual(len(rows), 4)
        row = next(r for r in rows if r["ref"] == "10242")
        self.assertEqual((row["opens_on"], row["deadline"]), ("2026-11-07", "2026-11-16"))
        self.assertEqual(row["title"], "Responsable de Sistemes Tecnològics de Xarxes i Telecomunicacions")

    def test_sin_tarjetas_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            tmb.parse_page("<main>Treball i pràctiques</main>")


class Detail(unittest.TestCase):
    def test_descripcion_plazas_contrato_y_bases(self):
        detail = tmb.parse_detail(fixture("tmb-ficha.html"))
        sections = {s["title"]: s["html"] for s in detail.sections}
        self.assertIn("concurs-oposició", sections["Descripció"])
        self.assertNotIn("style=", sections["Descripció"])
        self.assertIn(".pdf", sections["Bases de la convocatòria"])
        self.assertEqual((detail.positions, detail.kind, detail.location), (1, "indefinido", "Barcelona"))


    def test_enlace_de_las_bases_solo_http(self):
        html = fixture("tmb-ficha.html")
        start = html.index('href="/documents/')
        end = html.index('"', start + 6)
        detail = tmb.parse_detail(html[:start] + 'href="javascript:alert(document.domain)//bases.pdf' + html[end:])
        self.assertNotIn("javascript:", " ".join(s["html"] for s in detail.sections))


class Source(unittest.TestCase):
    def test_solo_las_que_siguen_en_plazo(self):
        offers = tmb.TmbSource(now=at(11, 11)).list_offers(Http())
        self.assertEqual([o.ref for o in offers], ["10242"])
        self.assertEqual((offers[0].deadline, offers[0].opens_on), ("2026-11-16", "2026-11-07"))
        self.assertEqual(tmb.TmbSource(now=at(11, 17)).list_offers(Http()), [])


if __name__ == "__main__":
    unittest.main()
