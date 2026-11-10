import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import enresa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("enresa-empleo.html")


class Listing(unittest.TestCase):
    def setUp(self):
        self.rows = enresa.parse_listing(fixture("enresa-empleo.html"))

    def test_lee_todas_las_convocatorias_con_su_estado(self):
        self.assertEqual([r["state"] for r in self.rows],
                         ["abierta", "abierta", "proceso", "proceso", "cerrada", "cerrada", "cerrada", "cerrada"])

    def test_codigo_del_titulo_o_de_los_documentos(self):
        self.assertEqual(self.rows[0]["ref"], "DO-DE-26-028")
        self.assertEqual(self.rows[1]["ref"], "DO-DE-26-048")  # solo figura en el nombre de los anexos

    def test_titulo_corto_plazas_y_centro(self):
        first, second = self.rows[:2]
        self.assertEqual(first["job"], "PERSONAL TITULADO DEL DEPARTAMENTO DE PROYECTOS DE CLAUSURA")
        self.assertEqual(second["job"], "PERSONAL DE OFICIOS EN EL SERVICIO DE MANTENIMIENTO DEL C.A. EL CABRIL")
        self.assertEqual(second["centre"], "El Cabril")
        self.assertEqual(self.rows[6]["positions"], 3)

    def test_plazo_de_presentacion(self):
        self.assertEqual(self.rows[0]["period"], (date(2026, 11, 4), date(2026, 11, 17)))
        self.assertEqual(self.rows[1]["period"], (date(2026, 10, 27), date(2026, 11, 7)))

    def test_plazo_que_cruza_de_ano(self):
        text = "Plazo de presentación de candidaturas del 20 de Diciembre al 10 de Enero de 2027"
        self.assertEqual(enresa._period(text), (date(2026, 12, 20), date(2027, 1, 10)))

    def test_contrato_temporal_solo_si_el_titulo_lo_dice(self):
        self.assertEqual([r["kind"] for r in self.rows[4:6]], ["temporal", "indefinido"])

    def test_documentos_con_enlace_absoluto(self):
        label, url = self.rows[0]["documents"][-1]
        self.assertEqual(label, "Convocatoria de proceso selectivo")
        self.assertEqual(url, "https://www.enresa.es/documentos/Convocatoria_externa_P._Titulado_Proyectos_de_Clausura_DO-DE-26-028.pdf")

    def test_pagina_sin_lista_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            enresa.parse_listing("<h1>Mantenimiento</h1>")

    def test_convocatoria_sin_estado_no_se_interpreta(self):
        with self.assertRaises(SourceLayoutError):
            enresa.parse_listing('<div id="listado-empleo"><section estado="abierta"><h3>X</h3></section></div>')


class Offers(unittest.TestCase):
    def setUp(self):
        self.source = enresa.EnresaSource(today=date(2026, 11, 7))
        self.http = FakeHttp()
        self.offers = {o.ref: o for o in self.source.list_offers(self.http)}

    def test_solo_los_abiertos_son_ofertas(self):
        self.assertEqual(sorted(self.offers), ["DO-DE-26-028", "DO-DE-26-048"])
        offer = self.offers["DO-DE-26-028"]
        self.assertEqual((offer.kind, offer.positions, offer.deadline), ("indefinido", 1, "2026-11-17"))
        self.assertEqual(offer.opens_on, "2026-11-04")
        self.assertTrue(offer.apply_url.endswith("DO-DE-26-028.pdf"))  # la convocatoria, no un anexo

    def test_ficha_con_documentos_y_centro(self):
        detail = self.source.fetch_detail(self.http, self.offers["DO-DE-26-048"])
        self.assertEqual(detail.location, "El Cabril")
        self.assertEqual([s["title"] for s in detail.sections], ["Convocatoria", "Documentos de la convocatoria"])
        self.assertIn("del 27/10/2026 al 07/11/2026", detail.sections[0]["html"])

    def test_cerrados_recientes_son_anuncios_con_la_fecha_de_fin(self):
        items = [i for i in self.source.list_announcements(self.http) if i.state == "finalizado"]
        self.assertEqual(sorted(i.date for i in items), ["2026-08-13", "2026-08-16", "2026-08-23", "2026-10-22"])
        self.assertTrue(all(i.title == "Proceso finalizado" for i in items))
        self.assertEqual(len({i.key for i in items}), 4)

    def test_los_procesos_en_curso_se_anuncian_sin_fecha(self):
        items = [i for i in self.source.list_announcements(self.http) if i.state == "curso"]
        self.assertEqual(len(items), 2)
        self.assertTrue(all(i.date == "" and "Proceso en curso" in i.title for i in items))
        self.assertTrue(all(i.access == "libre" for i in items))

    def test_los_procesos_llevan_su_centro_si_el_puesto_lo_nombra(self):
        locations = {i.process: i.location for i in self.source.list_announcements(self.http)}
        self.assertEqual(locations["3 puestos en la I.N. Santa María de Garoña (DO-DE-26-031)"], "Santa María de Garoña")
        self.assertIn(None, locations.values())

    def test_puestos_sin_nombre_y_titulo_repetido(self):
        title = ("CONVOCATORIA DE PROCESO SELECTIVO PARA LA COBERTURA DE VACANTE DE 3 PUESTOS DE TRABAJO "
                 "EN LA I.N. SANTA MARÍA DE GAROÑA MEDIANTE ACCESO LIBRE EN LA EMPRESA NACIONAL")
        job = enresa._job(title)
        self.assertEqual(job, "3 puestos EN LA I.N. SANTA MARÍA DE GAROÑA")
        name = enresa._process_name({"job": job, "centre": enresa._centre(job), "ref": "DO-DE-26-031"})
        self.assertEqual(name, "3 puestos en la I.N. Santa María de Garoña (DO-DE-26-031)")
        doubled = "VACANTE DE UN PUESTO DE TRABAJO DE TRABAJO DE PERSONAL TITULADO EN EL DEPARTAMENTO X (DO-DE-25-016)"
        self.assertEqual(enresa._job(doubled), "PERSONAL TITULADO EN EL DEPARTAMENTO X")

    def test_los_cerrados_antiguos_no_entran(self):
        source = enresa.EnresaSource(today=date(2027, 6, 1))
        source.list_offers(self.http)
        self.assertEqual([i.state for i in source.list_announcements(self.http)], ["curso", "curso"])

    def test_ingesta_completa(self):
        offers = {}
        now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        events = ingest.reconcile(offers, self.source.list_offers(self.http), "enresa", now)
        ingest.fetch_details(self.source, self.http, offers, events)
        record = offers["DO-DE-26-048"]
        self.assertEqual(record["id"], "enresa:DO-DE-26-048")
        self.assertEqual(record["location"], "El Cabril")
        self.assertEqual(record["deadline"], "2026-11-07")


if __name__ == "__main__":
    unittest.main()
