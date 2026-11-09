import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import etsa

FIXTURES = Path(__file__).parent / "fixtures"
URLS = {
    "https://www.etsa.es/conductor-a-repartidor-a-de-vehiculos-ligeros-con-adr/": "etsa-ficha-1.html",
    "https://www.etsa.es/conductor-a-internacional-de-vehiculos-articulados-con-adr/": "etsa-ficha-2.html",
    "https://www.etsa.es/administrativo-a-logistica-temporal/": "etsa-ficha-3.html",
}


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("etsa-listado.html" if url == etsa.PAGE else URLS[url])


class Listing(unittest.TestCase):
    def test_lee_fecha_referencia_titulo_y_enlace(self):
        entries = etsa.parse_listing(fixture("etsa-listado.html"))
        self.assertEqual([e["ref"] for e in entries], ["RH2026045", "RH2026040", "RH2026036"])
        self.assertEqual(entries[0]["date"], "2026-10-28")
        self.assertEqual(entries[0]["title"], "Conductor/a repartidor/a de vehículos ligeros con ADR")
        self.assertEqual(set(e["url"] for e in entries), set(URLS))

    def test_pagina_inesperada_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            etsa.parse_listing("<h1>Mantenimiento</h1>")

    def test_entrada_sin_referencia_no_se_interpreta(self):
        with self.assertRaises(SourceLayoutError):
            etsa.parse_listing(fixture("etsa-listado.html").replace("Referencia:", "Ref:"))


class Ficha(unittest.TestCase):
    def test_con_plazo_trae_bases_y_correo(self):
        ficha = etsa.parse_ficha(fixture("etsa-ficha-1.html"))
        self.assertEqual(ficha["deadline"], "2026-11-11")
        self.assertEqual(ficha["deadline_time"], "15:00")
        self.assertEqual([label for label, _ in ficha["documents"]],
                         ["Bases de convocatoria", "Anexo Protección Datos"])
        self.assertIn("candidaturas@etsa.es", ficha["html"])
        self.assertNotIn("<script", ficha["html"])
        self.assertNotIn("<!--", ficha["html"])

    def test_sin_plazo_solo_enlaza_el_resultado(self):
        ficha = etsa.parse_ficha(fixture("etsa-ficha-2.html"))
        self.assertIsNone(ficha["deadline"])
        self.assertEqual([label for label, _ in ficha["documents"]], ["Listado definitivo de admitidos/as"])

    def test_ficha_sin_contenido_no_se_interpreta(self):
        with self.assertRaises(SourceLayoutError):
            etsa.parse_ficha("<p>404</p>")


class Source(unittest.TestCase):
    def setUp(self):
        self.source, self.http = etsa.EtsaSource(), FakeHttp()
        self.offers = self.source.list_offers(self.http)

    def test_solo_la_entrada_con_plazo_es_oferta(self):
        (offer,) = self.offers
        self.assertEqual((offer.ref, offer.deadline, offer.deadline_time, offer.kind),
                         ("RH2026045", "2026-11-11", "15:00", "indefinido"))

    def test_las_demas_son_anuncios_por_documento(self):
        items = self.source.list_announcements(self.http)
        self.assertEqual(sorted(i.title for i in items),
                         ["Listado definitivo de admitidos/as", "Resultado fase final concurso"])
        self.assertEqual({i.date for i in items}, {"2026-10-14", "2026-09-22"})
        self.assertTrue(all(i.url.endswith(".pdf") for i in items))

    def test_ingesta_completa(self):
        offers = {}
        now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        events = ingest.reconcile(offers, self.source.list_offers(self.http), "etsa", now)
        ingest.fetch_details(self.source, self.http, offers, events)
        ingest.apply_enrichment(self.source, self.http, offers)
        record = offers["RH2026045"]
        self.assertEqual(record["published_on"], "2026-10-28")
        self.assertEqual(record["sections"][0]["title"], "Cómo presentar la candidatura")


if __name__ == "__main__":
    unittest.main()
