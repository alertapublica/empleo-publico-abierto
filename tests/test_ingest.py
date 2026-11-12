import re
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

from empleo import feeds, ingest, store
from empleo.model import Announcement, ListedOffer, OfferDetail, SourceLayoutError
from empleo.sources.base import Source

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def listed(ref="1", deadline="2026-11-20", positions=2, title="Oferta (Madrid)", published_on=None):
    return ListedOffer(ref=ref, title=title, company="Empresa", url=f"https://a/{ref}",
                       apply_url=f"https://a/i/{ref}", positions=positions, deadline=deadline,
                       published_on=published_on)


class FakeSource(Source):
    """Hace el papel de Enusa: otra empresa sin nada común con Tragsa."""

    id = "enusa"
    name = "Enusa"
    homepage = "https://example.org"

    def __init__(self, offers, detail=None, extra=None, fail_extra=False):
        self.offers, self.detail, self.extra, self.fail_extra = offers, detail, extra, fail_extra
        self.detail_calls = 0
        self.enrich_calls = 0

    def list_offers(self, http):
        return self.offers

    def fetch_detail(self, http, offer):
        self.detail_calls += 1
        return self.detail

    def enrich(self, http):
        self.enrich_calls += 1
        if self.fail_extra:
            raise RuntimeError("portal caído")
        return self.extra or {}

    def list_announcements(self, http):
        return [Announcement("2026-11-01", "Proceso", "Bases", "https://a/p")]


class Reconcile(unittest.TestCase):
    def setUp(self):
        self.offers = {}
        ingest.reconcile(self.offers, [listed()], "s", NOW)

    def kinds(self, listing, now=NOW):
        return [e["kind"] for e in ingest.reconcile(self.offers, listing, "s", now)]

    def test_oferta_nueva_lleva_identificador_con_fuente(self):
        self.assertEqual(self.offers["1"]["id"], "s:1")
        self.assertEqual(self.offers["1"]["status"], "open")

    def test_sin_cambios_no_hay_eventos(self):
        self.assertEqual(self.kinds([listed()]), [])

    def test_cambio_de_plazo_y_plazas_no_es_oferta_nueva(self):
        kinds = self.kinds([listed(deadline="2026-11-30", positions=5)])
        self.assertEqual(kinds, ["deadline_changed", "positions_changed"])
        self.assertEqual(self.offers["1"]["deadline"], "2026-11-30")
        self.assertFalse(self.offers["1"]["detail_ok"])

    def test_un_fallo_puntual_no_cierra_y_tres_si(self):
        self.assertEqual(self.kinds([listed("2")]), ["new"])
        self.assertEqual(self.offers["1"]["status"], "open")
        self.assertEqual(self.kinds([listed("2")]), [])
        self.assertEqual(self.offers["1"]["status"], "open")
        self.assertEqual(self.kinds([listed("2")]), ["closed"])
        self.assertEqual(self.offers["1"]["status"], "closed")

    def test_reaparecer_entre_lecturas_reinicia_la_cuenta(self):
        self.kinds([listed("2")])
        self.kinds([listed("1"), listed("2")])
        self.assertEqual(self.offers["1"]["missed_runs"], 0)

    def test_plazo_vencido_cierra_aunque_siga_listada(self):
        later = NOW + timedelta(days=30)
        self.assertEqual(self.kinds([listed()], later), ["closed"])

    def test_el_plazo_vive_hasta_el_final_del_dia_en_madrid(self):
        last_day = datetime(2026, 11, 20, 22, 30, tzinfo=timezone.utc)
        self.assertEqual(self.kinds([listed()], last_day), [])
        # 23:30 UTC ya es día 21 en Madrid en invierno.
        next_day = datetime(2026, 11, 20, 23, 30, tzinfo=timezone.utc)
        self.assertEqual(self.kinds([listed()], next_day), ["closed"])

    def test_con_hora_cierra_a_esa_hora_en_madrid(self):
        offers = {}
        at_eight = replace(listed(), deadline_time="08:00")
        ingest.reconcile(offers, [at_eight], "s", NOW)
        # 06:30 UTC son las 07:30 en Madrid: sigue abierta.
        before = datetime(2026, 11, 20, 6, 30, tzinfo=timezone.utc)
        self.assertEqual(ingest.reconcile(offers, [at_eight], "s", before), [])
        after = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)
        self.assertEqual([e["kind"] for e in ingest.reconcile(offers, [at_eight], "s", after)], ["closed"])
        # Cerrada por la hora, la siguiente lectura no la reabre.
        later = datetime(2026, 11, 20, 8, 0, tzinfo=timezone.utc)
        self.assertEqual(ingest.reconcile(offers, [at_eight], "s", later), [])

    def test_hora_leida_en_la_ficha_tambien_cierra(self):
        self.offers["1"]["deadline_time"] = "08:00"  # el listado no la trae
        after = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)
        self.assertEqual(self.kinds([listed()], after), ["closed"])
        self.assertEqual(self.kinds([listed()], after + timedelta(hours=1)), [])

    def test_ampliacion_a_otro_dia_reabre_aunque_hubiera_hora(self):
        self.offers["1"]["deadline_time"] = "08:00"
        after = datetime(2026, 11, 20, 7, 0, tzinfo=timezone.utc)
        self.kinds([listed()], after)
        kinds = self.kinds([listed(deadline="2026-11-21")], after)
        self.assertEqual(kinds, ["reopened", "deadline_changed"])
        # La hora del plazo anterior no se arrastra al nuevo día.
        self.assertIsNone(self.offers["1"]["deadline_time"])
        last_day = datetime(2026, 11, 21, 7, 0, tzinfo=timezone.utc)
        self.assertEqual(self.kinds([listed(deadline="2026-11-21")], last_day), [])

    def test_ampliacion_con_hora_nueva_la_guarda(self):
        self.offers["1"]["deadline_time"] = "08:00"
        self.kinds([replace(listed(deadline="2026-11-21"), deadline_time="14:00")])
        self.assertEqual(self.offers["1"]["deadline_time"], "14:00")

    def test_reabierta_con_nuevo_plazo(self):
        self.kinds([listed("2")])
        self.kinds([listed("2")])
        self.kinds([listed("2")])
        kinds = self.kinds([listed("1", deadline="2026-12-01"), listed("2")])
        self.assertEqual(kinds, ["reopened", "deadline_changed"])
        self.assertEqual(self.offers["1"]["status"], "open")
        self.assertIsNone(self.offers["1"]["closed_at"])

    def test_cerrada_sin_plazo_en_el_listado_no_se_reabre_si_el_de_la_ficha_vencio(self):
        self.offers["1"].update(deadline="2026-11-05", status="closed", closed_at="x")  # plazo de la ficha
        self.assertEqual(self.kinds([listed(deadline=None)]), [])
        self.assertEqual(self.offers["1"]["closed_at"], "x")

    def test_si_desaparece_casi_todo_se_aborta_sin_tocar_datos(self):
        offers = {}
        ingest.reconcile(offers, [listed(str(i)) for i in range(30)], "s", NOW)
        with self.assertRaises(SourceLayoutError):
            ingest.reconcile(offers, [listed("0")], "s", NOW)
        self.assertTrue(all(o["status"] == "open" and o["missed_runs"] == 0 for o in offers.values()))


class PublishedDate(unittest.TestCase):
    class Portal(FakeSource):
        def enrich(self, http):
            raise AssertionError("no hay nada pendiente: el portal no debe consultarse")

    def test_fecha_del_listado_evita_consultar_el_portal(self):
        offers = {}
        ingest.reconcile(offers, [listed(published_on="2026-10-26")], "enusa", NOW)
        self.assertEqual(offers["1"]["published_on"], "2026-10-26")
        ingest.apply_enrichment(self.Portal([]), None, offers)

    def test_completa_la_oferta_guardada_sin_fecha(self):
        offers = {}
        ingest.reconcile(offers, [listed()], "enusa", NOW)
        self.assertIsNone(offers["1"]["published_on"])
        ingest.reconcile(offers, [listed(published_on="2026-10-26")], "enusa", NOW)
        self.assertEqual(offers["1"]["published_on"], "2026-10-26")
        ingest.apply_enrichment(self.Portal([]), None, offers)


class Announcements(unittest.TestCase):
    class Fixed(Source):
        id, name, homepage = "x", "X", "https://x"

        def __init__(self, items):
            self.items = items

        def list_offers(self, http):
            return []

        def list_announcements(self, http):
            return self.items

    def item(self, process="P", title="T", **extra):
        return Announcement("2026-11-01", process, title, "https://a", **extra)

    def sync(self, known, *items, at=NOW):
        ingest.sync_announcements(self.Fixed(list(items)), None, known, at)
        return known

    def test_actualiza_el_proceso_y_conserva_la_primera_vista(self):
        known = self.sync({}, self.item(state="abierto", deadline="2026-11-10"))
        later = NOW + timedelta(days=5)
        self.sync(known, self.item(state="curso"), self.item(title="Nuevo", state="curso"), at=later)
        self.assertEqual(len(known), 2)
        self.assertEqual({r["state"] for r in known.values()}, {"curso"})
        self.assertEqual({r["deadline"] for r in known.values()}, {None})
        self.assertIn(NOW.isoformat(timespec="seconds"), {r["first_seen"] for r in known.values()})

    def test_pasada_la_hora_de_cierre_la_inscripcion_no_sigue_abierta(self):
        open_item = self.item(state="abierto", deadline="2026-11-10", deadline_time="14:00", apply_url="https://i")
        # 12:30 UTC son las 13:30 en Madrid: sigue abierta.
        known = self.sync({}, open_item, at=datetime(2026, 11, 10, 12, 30, tzinfo=timezone.utc))
        self.assertEqual(next(iter(known.values()))["state"], "abierto")
        self.sync(known, open_item, at=datetime(2026, 11, 10, 13, 0, tzinfo=timezone.utc))
        record = next(iter(known.values()))
        self.assertEqual((record["state"], record["deadline"], record["apply_url"]), ("curso", None, None))

    def test_todos_los_comunicados_toman_los_datos_actuales_del_proceso(self):
        known = self.sync({}, self.item(title="Viejo", via="otro"), self.item(title="Otro", via="otro"))
        self.sync(known, self.item(title="Viejo", via="tasa"))
        self.assertEqual({r["via"] for r in known.values()}, {"tasa"})

    def test_proceso_que_desaparece_queda_sin_novedades_y_puede_volver(self):
        known = self.sync({}, self.item("A"), self.item("B", state="finalizado"), self.item("C"))
        self.sync(known, self.item("C"))
        states = {r["process"]: r["state"] for r in known.values()}
        self.assertEqual(states, {"A": "retirado", "B": "finalizado", "C": "curso"})
        self.sync(known, self.item("A"), self.item("C"))
        self.assertEqual({r["process"]: r["state"] for r in known.values()}["A"], "curso")

    def test_una_lectura_vacia_no_retira_nada(self):
        known = self.sync({}, self.item("A"))
        self.sync(known)
        self.assertEqual(next(iter(known.values()))["state"], "curso")

    def test_procesos_sin_final_en_la_fuente_quedan_sin_novedades(self):
        source = self.Fixed([Announcement("", "Viejo", "T", "https://a")])
        source.stale_after_days = 30
        known = {}
        ingest.sync_announcements(source, None, known, NOW)  # primera lectura: ya estaban
        source.items = [Announcement("", "Viejo", "T", "https://a"), Announcement("", "Nuevo", "T", "https://b")]
        later = datetime(2026, 11, 10, 23, 30, tzinfo=timezone.utc)
        ingest.sync_announcements(source, None, known, later)
        records = {r["process"]: r for r in known.values()}
        self.assertEqual(records["Viejo"]["state"], "retirado")
        self.assertEqual((records["Nuevo"]["state"], records["Nuevo"]["date"]), ("curso", ""))  # sin fecha inventada
        self.assertEqual(feeds.announcement_items([records["Viejo"]]), [])
        ingest.sync_announcements(source, None, known, later + timedelta(days=29))
        self.assertEqual({r["process"]: r["state"] for r in known.values()}["Nuevo"], "curso")
        ingest.sync_announcements(source, None, known, later + timedelta(days=30))
        self.assertEqual({r["process"]: r["state"] for r in known.values()}["Nuevo"], "retirado")

    def test_sin_fecha_no_se_inventa_y_lo_de_la_primera_lectura_no_es_novedad(self):
        viejo, con_fecha = Announcement("", "P", "Viejo", "https://a"), self.item("P", "Con fecha")
        known = self.sync({}, viejo, con_fecha)
        nuevo_con_fecha = self.item("P", "Nuevo con fecha")
        self.sync(known, Announcement("", "P", "Nuevo", "https://b"), viejo, con_fecha, nuevo_con_fecha,
                  at=NOW + timedelta(hours=1))
        records = {r["title"]: r for r in known.values()}
        self.assertEqual(records["Viejo"]["date"], "")
        self.assertTrue(records["Viejo"]["baseline"])  # y lo sigue siendo en las lecturas siguientes
        self.assertTrue(records["Con fecha"]["baseline"])  # con fecha tampoco: sería avisar del histórico
        self.assertNotIn("baseline", records["Nuevo"])
        self.assertNotIn("baseline", records["Nuevo con fecha"])
        self.assertEqual((records["Nuevo"]["position"], records["Viejo"]["position"]), (0, 1))
        self.assertNotIn("position", records["Con fecha"])
        self.assertEqual({i["text"] for i in feeds.announcement_items(list(known.values()))},
                         {"Nuevo", "Nuevo con fecha"})

    def test_el_formato_anterior_se_sustituye(self):
        known = {"x:viejo": {"date": "2026-11-01", "process": "A", "title": "Corta", "url": "u", "source": "x",
                             "first_seen": "2026-11-07T00:00:00+00:00"}}
        self.sync(known, self.item("A", title="Completa"))
        self.assertEqual([r["title"] for r in known.values()], ["Completa"])


class RunSource(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.data = Path(self.tmp.name)

    def stored(self, name="offers.json"):
        return store.load(self.data / "enusa" / name, {})

    def test_una_segunda_empresa_entra_sin_cambiar_el_motor(self):
        detail = OfferDetail(sections=[{"title": "Funciones", "level": 2, "html": "<p>x</p>"}],
                             location="Salamanca")
        extra = {"1": {"published_on": "2026-11-02", "family": "Técnica", "location": "Salamanca"}}
        ingest.run_source(FakeSource([listed()], detail, extra), None, self.data, NOW)
        record = self.stored()["1"]
        self.assertEqual(record["id"], "enusa:1")
        self.assertEqual(record["source"], "enusa")
        self.assertEqual(record["region"], "Castilla y León")
        self.assertEqual(record["published_on"], "2026-11-02")
        self.assertTrue(record["detail_ok"])
        self.assertEqual(len(self.stored("announcements.json")), 1)

    def test_comunidad_desconocida_se_recalcula_con_la_tabla_actual(self):
        detail = OfferDetail(location="Juzbado")
        ingest.run_source(FakeSource([listed(title="Oferta")], detail), None, self.data, NOW)
        records = self.stored()
        records["1"]["region"] = "Sin ubicación"  # lo que se guardó antes de conocer Juzbado
        store.save(self.data / "enusa" / "offers.json", records)
        ingest.run_source(FakeSource([listed(title="Oferta")], detail), None, self.data, NOW)
        self.assertEqual(self.stored()["1"]["region"], "Castilla y León")

    def test_sin_ubicacion_vale_la_comunidad_de_la_fuente(self):
        source = FakeSource([listed(title="Oferta")], OfferDetail())
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual(self.stored()["1"]["region"], "Sin ubicación")  # fuente estatal
        source.scope = "Aragón"
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual((self.stored()["1"]["location"], self.stored()["1"]["region"]), ("Aragón", "Aragón"))
        concreta = FakeSource([listed(ref="2", title="Oferta")], OfferDetail(location="Huesca"))
        concreta.scope = "Aragón"
        ingest.run_source(concreta, None, self.data, NOW)
        self.assertEqual(self.stored()["2"]["location"], "Huesca")

    def test_parentesis_del_titulo_que_no_es_un_lugar_no_es_la_ubicacion(self):
        source = FakeSource([listed(title="Ingeniero/a de Plataformas (2026-T00434)")], OfferDetail())
        ingest.run_source(source, None, self.data, NOW)
        self.assertIsNone(self.stored()["1"]["location"])
        records = self.stored()
        records["1"]["location"] = "2026-T00434"  # lo que se guardó antes del arreglo
        store.save(self.data / "enusa" / "offers.json", records)
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual((self.stored()["1"]["location"], self.stored()["1"]["region"]),
                         (None, "Sin ubicación"))

    def test_el_codigo_sale_del_titulo_al_leer_y_en_lo_ya_guardado(self):
        source = FakeSource([listed(ref="2", title="OE 25/26 - Médico de Empresa")], OfferDetail())
        source.title_code = re.compile(r"(?P<code>OE\s+\d+/\d+)\s*-\s*(?P<title>.+)")
        ingest.run_source(source, None, self.data, NOW)
        record = self.stored()["2"]
        self.assertEqual((record["title"], record["code"], record["source_title"]),
                         ("Médico de Empresa", "OE 25/26", "OE 25/26 - Médico de Empresa"))
        # Guardada antes de separar el código, ya cerrada: se corrige una vez sin volver a leerla.
        records = self.stored()
        records["9"] = {**record, "ref": "9", "id": "enusa:9", "status": "closed",
                        "title": "OE 24/26 - Analista", "detail_ok": True}
        del records["9"]["code"], records["9"]["source_title"]
        store.save(self.data / "enusa" / "offers.json", records)
        ingest.run_source(source, None, self.data, NOW)
        old = self.stored()["9"]
        self.assertEqual((old["title"], old["code"], old["source_title"]),
                         ("Analista", "OE 24/26", "OE 24/26 - Analista"))
        self.assertEqual(self.stored("events.json")[-1]["kind"], "new")  # sin eventos por el cambio

    def test_el_titulo_literal_que_ya_da_la_fuente_se_respeta(self):
        offer = replace(listed(ref="2", title="Titulado/a Graduado/a I · PROMODAS"),
                        code="081/2026", source_title="1.2 3 Titulado/a Graduado/a I")
        ingest.run_source(FakeSource([offer], OfferDetail()), None, self.data, NOW)
        record = self.stored()["2"]
        self.assertEqual((record["title"], record["code"], record["source_title"]),
                         ("Titulado/a Graduado/a I · PROMODAS", "081/2026", "1.2 3 Titulado/a Graduado/a I"))

    def test_el_plazo_vencido_de_la_ficha_cierra_en_la_misma_lectura(self):
        ingest.run_source(FakeSource([listed(deadline=None)], OfferDetail(deadline="2026-11-06")), None, self.data, NOW)
        self.assertEqual(self.stored()["1"]["status"], "closed")
        self.assertEqual([e["kind"] for e in self.stored("events.json")], ["new", "closed"])

    def test_una_fecha_imposible_no_se_guarda(self):
        with self.assertRaises(SourceLayoutError):
            ingest.run_source(FakeSource([listed(deadline="2027-02-31")]), None, self.data, NOW)
        self.assertEqual(self.stored(), {})
        # En la ficha solo se descarta esa ficha.
        ingest.run_source(FakeSource([listed()], OfferDetail(deadline="2026-13-01")), None, self.data, NOW)
        self.assertEqual((self.stored()["1"]["deadline"], self.stored()["1"]["detail_ok"]), ("2026-11-20", False))

    def test_ficha_no_disponible_se_reintenta(self):
        ingest.run_source(FakeSource([listed()], None), None, self.data, NOW)
        self.assertFalse(self.stored()["1"]["detail_ok"])
        source = FakeSource([listed()], OfferDetail(location="Madrid"))
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual(source.detail_calls, 1)
        self.assertTrue(self.stored()["1"]["detail_ok"])
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual(source.detail_calls, 1)

    def test_nueva_version_de_la_ficha_la_relee_en_las_abiertas(self):
        def ficha(hour):
            return OfferDetail(deadline_time=hour)
        source = FakeSource([listed()], ficha(None))
        ingest.run_source(source, None, self.data, NOW)
        records = self.stored()
        del records["1"]["detail_version"]  # guardada antes de que existiera la versión
        store.save(self.data / "enusa" / "offers.json", records)
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual(source.detail_calls, 1)
        source.detail_version, source.detail = 2, ficha("12:00")  # p. ej., la hora de las bases
        ingest.run_source(source, None, self.data, NOW)
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual(source.detail_calls, 2)
        self.assertEqual((self.stored()["1"]["deadline_time"], self.stored()["1"]["detail_version"]), ("12:00", 2))

    def test_el_portal_caido_no_bloquea(self):
        source = FakeSource([listed()], OfferDetail(), fail_extra=True)
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual(self.stored()["1"]["status"], "open")
        self.assertEqual(self.stored()["1"]["region"], "Comunidad de Madrid")  # del título

    def test_el_portal_no_se_consulta_sin_necesidad_ni_sin_limite(self):
        extra = {"1": {"published_on": "2026-11-02"}}
        source = FakeSource([listed()], OfferDetail(), extra)
        ingest.run_source(source, None, self.data, NOW)
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual(source.enrich_calls, 1)
        ausente = FakeSource([listed("2")], OfferDetail(), {})
        for _ in range(ingest.MAX_PORTAL_TRIES + 2):
            ingest.run_source(ausente, None, self.data, NOW)
        self.assertEqual(ausente.enrich_calls, ingest.MAX_PORTAL_TRIES)

    def test_contrato_y_fechas_de_la_ficha_se_conservan_si_el_listado_no_los_trae(self):
        detail = OfferDetail(contract="Modalidad de contratación: Temporal", opens_on="2026-11-02",
                             deadline_time="13:00")
        ingest.run_source(FakeSource([listed()], detail), None, self.data, NOW)
        record = self.stored()["1"]
        self.assertEqual((record["contract"], record["opens_on"], record["deadline_time"]),
                         ("Modalidad de contratación: Temporal", "2026-11-02", "13:00"))
        ingest.run_source(FakeSource([listed()], OfferDetail()), None, self.data, NOW)
        self.assertEqual(self.stored()["1"]["contract"], "Modalidad de contratación: Temporal")

    def test_tipo_de_contrato_que_solo_da_la_ficha(self):
        sin_tipo = listed()
        sin_tipo.kind = None
        ingest.run_source(FakeSource([sin_tipo], OfferDetail(kind="temporal")), None, self.data, NOW)
        ingest.run_source(FakeSource([sin_tipo], OfferDetail()), None, self.data, NOW)
        self.assertEqual(self.stored()["1"]["kind"], "temporal")

    def test_el_listado_actualiza_contrato_y_fechas(self):
        first = ListedOffer(ref="1", title="Oferta", company="E", url="https://a/1", apply_url="https://a/i/1",
                            deadline="2026-11-20", contract="Temporal", opens_on="2026-11-03")
        ingest.run_source(FakeSource([first], OfferDetail()), None, self.data, NOW)
        first.opens_on, first.contract = "2026-11-05", "Indefinido"
        ingest.run_source(FakeSource([first], OfferDetail()), None, self.data, NOW)
        record = self.stored()["1"]
        self.assertEqual((record["contract"], record["opens_on"]), ("Indefinido", "2026-11-05"))

    def test_registros_anteriores_a_los_campos_nuevos_siguen_funcionando(self):
        ingest.run_source(FakeSource([listed()], None), None, self.data, NOW)
        records = self.stored()
        for field in ("contract", "opens_on", "deadline_time"):
            del records["1"][field]  # como los guardados antes de existir estos campos
        store.save(self.data / "enusa" / "offers.json", records)
        ingest.run_source(FakeSource([listed()], OfferDetail(contract="Temporal")), None, self.data, NOW)
        self.assertEqual(self.stored()["1"]["contract"], "Temporal")

    def test_la_ficha_corrige_el_plazo_del_listado_sin_oscilar(self):
        source = FakeSource([listed(deadline="2026-11-08")], OfferDetail(deadline="2026-11-09", deadline_time="23:59"))
        ingest.run_source(source, None, self.data, NOW)
        ingest.run_source(source, None, self.data, NOW)
        record = self.stored()["1"]
        self.assertEqual((record["deadline"], record["deadline_time"]), ("2026-11-09", "23:59"))
        self.assertEqual(source.detail_calls, 1)
        self.assertEqual([e["kind"] for e in self.stored("events.json")], ["new"])
        # Si el listado cambia su fecha, vale la nueva y se vuelve a leer la ficha.
        source.offers, source.detail = [listed(deadline="2026-11-20")], OfferDetail()
        ingest.run_source(source, None, self.data, NOW)
        record = self.stored()["1"]
        self.assertEqual((record["deadline"], record["deadline_time"], source.detail_calls), ("2026-11-20", None, 2))

    def test_plazas_de_la_ficha_si_el_listado_no_las_trae(self):
        source = FakeSource([listed(positions=None)], OfferDetail(positions=4))
        ingest.run_source(source, None, self.data, NOW)
        ingest.run_source(source, None, self.data, NOW)
        self.assertEqual(self.stored()["1"]["positions"], 4)
        self.assertEqual([e["kind"] for e in self.stored("events.json")], ["new"])

    def test_republicacion_se_marca_como_tal(self):
        detail = OfferDetail(parent_ref="99")
        ingest.run_source(FakeSource([listed()], detail), None, self.data, NOW)
        self.assertEqual(self.stored("events.json")[0]["kind"], "republished")


class Chosen(unittest.TestCase):
    def test_sin_ids_todas(self):
        from empleo.sources import ACTIVE
        self.assertEqual(ingest.chosen([]), ACTIVE)

    def test_solo_las_pedidas_en_orden_del_catalogo(self):
        self.assertEqual([s.id for s in ingest.chosen(["fundesalud", "tragsa"])], ["tragsa", "fundesalud"])

    def test_id_desconocido_es_error(self):
        with self.assertRaises(SystemExit):
            ingest.chosen(["fundesalu"])


class AnnouncementId(unittest.TestCase):
    def test_dos_comunicados_que_empiezan_igual_no_comparten_id(self):
        # Cetarsa: el mismo día, dos exámenes que solo difieren en la sede, más allá de 80 caracteres.
        start = "Examen de FASE II – Oposición 10 de Noviembre de 2026 – 10.00h en el Centro de CETARSA en "
        items = [{"source": "cetarsa", "process": "Técnico", "date": "2026-11-05", "title": start + place,
                  "url": "https://a", "first_seen": "2026-11-05T10:00:00+00:00"}
                 for place in ("Talayuela", "Navalmoral de la Mata")]
        self.assertEqual(len({feeds.announcement_id(i) for i in items}), 2)
        self.assertEqual(len({i["guid"] for i in feeds.announcement_items(items)}), 2)
        other = {**items[0], "source": "enusa"}
        self.assertNotEqual(feeds.announcement_id(other), feeds.announcement_id(items[0]))
