import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import cetarsa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("cetarsa-empleo.html")


class Page(unittest.TestCase):
    def setUp(self):
        self.items = cetarsa.parse_page(fixture("cetarsa-empleo.html"))

    def test_secciones_y_estado(self):
        sections = {(i["section"], i["active"], i["internal"], i["bank"]) for i in self.items}
        self.assertIn(("Ofertas de Empleo Activas – Convocatoria Libre", True, False, False), sections)
        self.assertIn(("Ofertas de Empleo Activas – Promoción Interna", True, True, False), sections)
        self.assertTrue(any(i["bank"] and i["active"] for i in self.items))
        self.assertTrue(any(not i["active"] for i in self.items))

    def test_puesto_y_plazas_del_titulo(self):
        first = next(i for i in self.items if i["section"].endswith("Convocatoria Libre"))
        self.assertEqual(first["job"], "Técnico/a de Producción Agrícola- Clasificador/a Industrial")
        self.assertEqual(first["positions"], 2)

    def test_plazo_de_solicitudes(self):
        first = next(i for i in self.items if i["section"].endswith("Convocatoria Libre"))
        self.assertEqual(first["deadline"], date(2026, 11, 16))  # «hasta el 16 de Noviembre las 14:00 horas del 2026»

    def test_la_fila_de_reclamaciones_no_cuenta_como_plazo(self):
        rows = [{"date": "2026-10-20", "text": "Se establece plazo de reclamaciones hasta el 23 de Octubre a las 12:00 horas del 2026"}]
        self.assertEqual(cetarsa._deadline(rows), (None, None))

    def test_ampliacion_del_plazo_vale_la_fecha_mayor(self):
        rows = [
            {"date": "2026-10-01", "text": "Se establece plazo de solicitudes hasta el 14 de Octubre a las 14:00 horas del 2026"},
            {"date": "2026-10-10", "text": "AMPLIACIÓN DEL PLAZO DE PRESENTACIÓN DE SOLICITUDES hasta el 28 de Octubre de 2026"},
        ]
        # La hora de las bases (14:00) era del plazo anterior: la ampliación no la da.
        self.assertEqual(cetarsa._deadline(rows), (date(2026, 10, 28), None))

    def test_la_hora_va_con_el_dia(self):
        rows = [{"date": "2026-10-01", "text": "Se establece plazo de solicitudes hasta el 16 de Noviembre las 14:00 horas del 2026"}]
        self.assertEqual(cetarsa._deadline(rows), (date(2026, 11, 16), "14:00"))

    def test_pagina_sin_contenido_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            cetarsa.parse_page("<h1>Mantenimiento</h1>")

    def test_fila_sin_fecha_no_se_interpreta(self):
        html = fixture("cetarsa-empleo.html").replace("2026-10-26", "sin fecha", 1)
        with self.assertRaises(SourceLayoutError):
            cetarsa.parse_page(html)


class Source(unittest.TestCase):
    def setUp(self):
        self.source, self.http = cetarsa.CetarsaSource(today=date(2026, 11, 7)), FakeHttp()
        self.offers = self.source.list_offers(self.http)

    def test_solo_son_ofertas_las_convocatorias_libres_con_plazo_abierto(self):
        self.assertEqual(sorted(o.title for o in self.offers),
                         ["Operador/a Informática", "Técnico/a de Producción Agrícola- Clasificador/a Industrial"])
        self.assertTrue(all(o.deadline == "2026-11-16" and o.kind == "indefinido" for o in self.offers))

    def test_las_bolsas_con_plazo_vencido_no_son_ofertas(self):
        self.assertFalse(any(o.kind == "bolsa" for o in self.offers))

    def test_una_bolsa_con_plazo_abierto_seria_oferta(self):
        source = cetarsa.CetarsaSource(today=date(2026, 10, 10))
        offers = source.list_offers(self.http)
        self.assertEqual(sorted(o.kind for o in offers).count("bolsa"), 2)

    def test_la_promocion_interna_no_es_oferta_sino_anuncio(self):
        items = self.source.list_announcements(self.http)
        self.assertTrue(any("Promoción interna" in i.process for i in items))
        self.assertFalse(any("Promoción interna" in o.category for o in self.offers))

    def test_todos_los_comunicados_con_el_texto_completo(self):
        items = self.source.list_announcements(self.http)
        rrhh = [i for i in items if i.process.startswith("Técnico de Recursos Humanos")]
        self.assertGreater(len(rrhh), 1)
        latest = max(rrhh, key=lambda i: i.date)
        self.assertEqual(latest.date, "2026-11-06")
        self.assertIn("AVISO IMPORTANTE", latest.title)
        self.assertGreater(len(latest.title), 240)  # el cambio de fecha va al final del aviso
        self.assertEqual(len({i.key for i in items}), len(items))

    def test_acceso_via_y_sistema_de_cada_convocatoria(self):
        items = self.source.list_announcements(self.http)
        internal = next(i for i in items if "Promoción interna" in i.process)
        self.assertEqual((internal.access, internal.via, internal.contract), ("interna", "otro", "indefinido"))
        bank = next(i for i in items if "Bolsa temporal" in i.process)
        self.assertEqual((bank.access, bank.via, bank.contract), (None, "bolsa", "temporal"))
        self.assertTrue(any(i.system == "concurso-oposicion" for i in items))

    def test_ingesta_completa(self):
        offers = {}
        now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        events = ingest.reconcile(offers, self.source.list_offers(self.http), "cetarsa", now)
        ingest.fetch_details(self.source, self.http, offers, events)
        self.assertEqual(len(offers), 2)
        record = next(iter(offers.values()))
        self.assertEqual([s["title"] for s in record["sections"]],
                         ["Convocatoria", "Documentos publicados", "Cómo presentar la candidatura"])


if __name__ == "__main__":
    unittest.main()
