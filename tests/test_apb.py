import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import apb

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Listado real; cada ficha, una de las tres reales según el nombre."""

    def get(self, url):
        if url == apb.PAGE:
            return fixture("apb-ofertas.html")
        if "sostenibilitat" in url or "topografia" in url:
            return fixture("apb-ficha-ampliada.html")
        if "domini" in url:
            return fixture("apb-ficha-bases.html")
        return fixture("apb-ficha-seguimiento.html")


def pdfs(http, url, what):
    return fixture("apb-bases.txt")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


def read(now):
    source = apb.ApbSource(now=now)
    with mock.patch.object(apb, "read_pdf", pdfs):
        offers = source.list_offers(Http())
        notices = source.list_announcements(Http())
        details = {o.ref: source.fetch_detail(Http(), o) for o in offers}
    return offers, notices, details


class Page(unittest.TestCase):
    def test_siete_ofertas_y_fichas_en_castellano(self):
        rows = apb.parse_page(fixture("apb-ofertas.html"))
        self.assertEqual(len(rows), 7)
        self.assertTrue(all("/es/web/" in r["url"] for r in rows))

    def test_listado_vacio_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            apb.parse_page("<ul><li>Ofertas</li></ul>")


class Detail(unittest.TestCase):
    def test_ampliacion_en_la_ficha(self):
        detail = apb.parse_detail(fixture("apb-ficha-ampliada.html"))
        self.assertEqual([(d.isoformat(), h) for d, h in detail["extended"]], [("2026-11-20", "12:00")])
        self.assertEqual(detail["notices"], [])
        self.assertEqual(detail["kind"], "indefinido")
        self.assertIn("Misión del puesto de trabajo", [s["title"] for s in detail["sections"]])

    def test_seguimiento_literal_del_mas_reciente_al_mas_antiguo(self):
        notices = apb.parse_detail(fixture("apb-ficha-seguimiento.html"))["notices"]
        self.assertEqual(len(notices), 4)
        self.assertTrue(notices[0]["title"].startswith("Os hacemos llegar el acta de resultados de la prueba de idiomas"))
        self.assertTrue(notices[-1]["title"].startswith("Os hacemos llegar la lista provisional"))
        self.assertTrue(notices[0]["url"].endswith("?t=1794233735113"))


class Source(unittest.TestCase):
    def test_ofertas_con_plazo_de_las_bases_o_de_la_ampliacion(self):
        offers, _, details = read(at(11, 11))
        by_ref = {o.ref: o for o in offers}
        self.assertEqual(len(offers), 4)  # dos ampliadas y dos solo con bases
        ampliada = next(o for o in offers if "sostenibilitat" in o.ref)
        self.assertEqual((ampliada.deadline, ampliada.deadline_time), ("2026-11-23", "13:00"))  # vale la mayor
        bases = next(o for o in offers if "domini-public" in o.ref)
        self.assertEqual((bases.deadline, bases.deadline_time, bases.kind), ("2026-11-23", "13:00", "indefinido"))
        self.assertEqual(details[bases.ref].location, "Barcelona")
        self.assertTrue(by_ref)

    def test_con_seguimiento_son_procesos(self):
        _, notices, _ = read(at(11, 11))
        self.assertEqual(len({n.process for n in notices}), 3)
        self.assertEqual({n.date for n in notices}, {""})
        self.assertEqual({n.state for n in notices}, {"curso"})

    def test_vencido_el_plazo_no_hay_ofertas(self):
        offers, _, _ = read(at(11, 23, 13))  # 14:00 en Madrid
        self.assertEqual(offers, [])


if __name__ == "__main__":
    unittest.main()
