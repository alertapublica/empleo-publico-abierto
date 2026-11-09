import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import cofivacasa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("cofivacasa-empleo.html")


class Page(unittest.TestCase):
    def test_lee_los_procesos_con_mes_y_estado(self):
        processes = cofivacasa.parse_page(fixture("cofivacasa-empleo.html"))
        self.assertEqual(len(processes), 9)
        self.assertEqual([p["state"] for p in processes].count("abierto"), 1)
        self.assertEqual({p["state"] for p in processes}, {"abierto", "cerrado", "desistido", "concluido"})
        first = processes[0]
        self.assertEqual((first["month"], first["year"]), (10, 2026))
        self.assertEqual(first["title"], "Director/a del área jurídica y responsable de cumplimiento")
        self.assertTrue(first["bases"].endswith("tasa-reposicion-octubre-2026_.pdf"))

    def test_comunicados_de_un_proceso_cerrado(self):
        processes = cofivacasa.parse_page(fixture("cofivacasa-empleo.html"))
        labels = [label for label, _ in processes[1]["documents"]]
        self.assertIn("Resolución candidaturas admitidas", labels)

    def test_pagina_sin_procesos_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            cofivacasa.parse_page("<h1>Mantenimiento</h1>")

    def test_bloques_que_no_son_procesos_no_pasan_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            cofivacasa.parse_page('<div class="fusion-text"><p>Texto cualquiera</p></div>')


class Source(unittest.TestCase):
    def test_solo_el_proceso_abierto_es_oferta(self):
        source = cofivacasa.CofivacasaSource()
        (offer,) = source.list_offers(FakeHttp())
        self.assertEqual(offer.title, "Director/a del área jurídica y responsable de cumplimiento")
        self.assertEqual((offer.kind, offer.category, offer.deadline), ("indefinido", "Tasa de reposición", None))
        self.assertTrue(offer.apply_url.startswith("https://cofivacasa.com/wp-content/uploads/2026/10/"))

    def test_ingesta_completa(self):
        source, http, offers = cofivacasa.CofivacasaSource(), FakeHttp(), {}
        now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        events = ingest.reconcile(offers, source.list_offers(http), "cofivacasa", now)
        ingest.fetch_details(source, http, offers, events)
        (record,) = offers.values()
        self.assertEqual(record["region"], "Comunidad de Madrid")
        self.assertEqual(record["category"], "Tasa de reposición")


if __name__ == "__main__":
    unittest.main()
