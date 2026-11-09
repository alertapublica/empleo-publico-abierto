import unittest
from datetime import date
from pathlib import Path

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import efe

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = "https://agenciaefe.es/empleo-efe-indefinido/"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def parse(name, today, kind="indefinido"):
    return efe.parse_listing(fixture(name), kind, "Oferta de empleo público", PAGE, date.fromisoformat(today))


class Listing(unittest.TestCase):
    def test_temporal_con_plazo_vigente_trae_todos_los_campos(self):
        (row,) = parse("efe-temporal.html", "2026-10-01", "temporal")
        self.assertEqual(row["ref"], "CT2026 10-01")
        self.assertEqual(row["title"], "Técnico de Administración Facturación")
        self.assertEqual(row["department"], "Dirección Económico Financiera")
        self.assertEqual(row["positions"], 1)
        self.assertEqual(row["location"], "Madrid")
        self.assertEqual(row["published_on"], "2026-09-15")
        self.assertEqual(row["deadline"], "2026-10-05")  # año de dos cifras
        self.assertTrue(row["url"].startswith("https://agenciaefe.es/wp-content/uploads/"))
        self.assertEqual(row["documents"][0][0], "Bases de la convocatoria")

    def test_abierto_con_plazo_vencido_no_es_oferta(self):
        self.assertEqual(parse("efe-temporal.html", "2026-11-07", "temporal"), [])

    def test_solo_hay_una_oferta_indefinida_con_plazo_a_7_de_noviembre(self):
        rows = parse("efe-indefinido.html", "2026-11-07")
        self.assertEqual([r["ref"] for r in rows], ["MI 2025-01-02"])
        self.assertEqual(rows[0]["deadline"], "2026-12-15")
        self.assertEqual(rows[0]["published_on"], "2026-10-27")

    def test_cerradas_y_desiertas_nunca_entran(self):
        rows = parse("efe-indefinido.html", "2020-01-01")
        refs = [r["ref"] for r in rows]
        self.assertNotIn("MI 2025-01", refs)  # «Desierto»
        self.assertEqual(len(rows), 17)  # todas las «Abiertas» de la tabla de convocatorias
        self.assertEqual(len(parse("efe-temporal.html", "2020-01-01", "temporal")), 1)  # 7 cerradas fuera

    def test_varias_referencias_en_una_fila_se_conservan(self):
        rows = {r["ref"]: r for r in parse("efe-indefinido.html", "2026-09-01")}
        self.assertIn("TRO2026 30-01-TRO2026 31-01", rows)
        self.assertEqual(rows["TRO2026 30-01-TRO2026 31-01"]["positions"], 2)

    def test_documentos_y_observaciones_de_ampliacion(self):
        rows = {r["ref"]: r for r in parse("efe-indefinido.html", "2026-09-01")}
        row = rows["TRO2026 38-01"]
        self.assertIn("Amplición", row["observations"])  # tal como lo publica EFE
        labels = [label for label, _ in row["documents"]]
        self.assertEqual(labels[0], "Bases de la convocatoria")
        self.assertTrue(len(labels) >= 2)
        self.assertTrue(all(url.startswith("https://") for _, url in row["documents"]))

    def test_pagina_sin_tabla_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            efe.parse_listing("<h1>Mantenimiento</h1>", "temporal", "x", PAGE, date(2026, 11, 7))

    def test_columnas_cambiadas_no_se_interpretan(self):
        html = fixture("efe-temporal.html").replace("Centro trabajo", "Sede")
        with self.assertRaises(SourceLayoutError):
            efe.parse_listing(html, "temporal", "x", PAGE, date(2026, 10, 1))


class FakeHttp:
    def get(self, url):
        return fixture("efe-temporal.html" if "temporal" in url else "efe-indefinido.html")


class EndToEnd(unittest.TestCase):
    def test_ingesta_completa_sin_peticiones_extra(self):
        from datetime import datetime, timezone
        source = efe.EfeSource(today=date(2026, 9, 20))
        http, offers = FakeHttp(), {}
        now = datetime(2026, 9, 20, 12, tzinfo=timezone.utc)
        events = ingest.reconcile(offers, source.list_offers(http), "efe", now)
        ingest.fetch_details(source, http, offers, events)
        ingest.apply_enrichment(source, http, offers)
        self.assertTrue(offers)
        record = offers["MI 2025-01-02"]
        self.assertEqual(record["id"], "efe:MI 2025-01-02")
        self.assertEqual(record["kind"], "indefinido")
        self.assertEqual(record["location"], "Madrid")
        self.assertEqual(record["region"], "Comunidad de Madrid")
        self.assertEqual(record["department"], "Auditoria Interna")
        self.assertEqual(record["published_on"], "2026-10-27")
        self.assertEqual({s["title"] for s in record["sections"]},
                         {"Documentos de la convocatoria", "Cómo presentar la candidatura"})
        self.assertTrue(all(e["kind"] == "new" for e in events))


class InProgress(unittest.TestCase):
    def test_procesos_con_plazo_vencido_siguen_en_tramitacion(self):
        html = fixture("efe-indefinido.html")
        rows = efe.parse_listing(html, "indefinido", "x", PAGE, date(2026, 11, 7), current=False)
        self.assertEqual(len(rows), 16)
        self.assertNotIn("MI 2025-01-02", [r["ref"] for r in rows])  # ese sí admite candidaturas

    def test_son_anuncios_de_oferta_de_empleo_publico_sin_peticiones_extra(self):
        source = efe.EfeSource(today=date(2026, 11, 7))
        source.list_offers(FakeHttp())
        items = source.list_announcements(FakeHttp())
        self.assertEqual(len(items), 16)  # solo indefinidos: el temporal vencido no entra
        self.assertEqual({i.via for i in items}, {"oep"})
        self.assertEqual({i.contract for i in items}, {"indefinido"})
        self.assertEqual(len({i.process for i in items}), 16)  # cada puesto es su propio proceso
        self.assertRegex(items[0].date, r"^\d{4}-\d{2}-\d{2}$")
        self.assertRegex(items[0].title, r"^Plazo de candidaturas finalizado el \d\d/\d\d/\d{4}")
        self.assertEqual(len({i.key for i in items}), 16)
