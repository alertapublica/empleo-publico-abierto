import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import zarzuela

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("zarzuela-informacion.html")


def bases(http, url, what):
    return fixture("zarzuela-bases-apuestas.txt" if ("Apuestas" in url or "Accesos" in url) else "zarzuela-bases-tic.txt")


class Page(unittest.TestCase):
    def test_procesos_y_documentos_posteriores(self):
        processes = {p["process"]: p["later"] for p in zarzuela.parse_page(fixture("zarzuela-informacion.html"))}
        self.assertEqual(processes["Administrativo_a financiero_a"], 6)  # ya con listados y adjudicación
        self.assertEqual(processes["Responsable TIC"], 0)
        self.assertEqual(processes["Modalidad fija discontinua. Taquillero/a apuestas"], 0)

    def test_pagina_sin_la_seccion_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            zarzuela.parse_page("<h2>Otra cosa</h2>")


class Source(unittest.TestCase):
    def offers(self, today=date(2026, 11, 7)):
        source = zarzuela.ZarzuelaSource(today=today)
        with mock.patch.object(zarzuela, "read_pdf", bases):
            return source, source.list_offers(FakeHttp())

    def test_solo_los_procesos_sin_listados_y_con_plazo_vigente(self):
        _, offers = self.offers()
        self.assertEqual(sorted(o.title for o in offers), [
            "Control accesos (fijo discontinuo)", "Responsable TIC", "Taquillero/a apuestas (fijo discontinuo)"])

    def test_datos_de_las_bases(self):
        _, offers = self.offers()
        tic = next(o for o in offers if o.title == "Responsable TIC")
        self.assertEqual((tic.deadline, tic.positions, tic.kind, tic.category),
                         ("2026-11-16", 1, "indefinido", "Tasa de reposición"))
        betting = next(o for o in offers if o.title.startswith("Taquillero"))
        self.assertEqual((betting.deadline, betting.positions), ("2026-11-13", 7))

    def test_vencido_el_plazo_ya_no_es_oferta(self):
        _, offers = self.offers(today=date(2026, 11, 14))
        self.assertEqual([o.title for o in offers], ["Responsable TIC"])  # los otros dos cerraron el 13

    def test_fecha_de_publicacion(self):
        source, _ = self.offers()
        self.assertEqual(sorted(v["published_on"] for v in source.enrich(FakeHttp()).values()),
                         ["2026-10-16", "2026-11-03", "2026-11-03"])

    def test_bases_sin_plazo_detienen_la_fuente(self):
        source = zarzuela.ZarzuelaSource(today=date(2026, 11, 7))
        with mock.patch.object(zarzuela, "read_pdf", lambda *a: "Convocatoria sin fecha"):
            with self.assertRaises(SourceLayoutError):
                source.list_offers(FakeHttp())

    def test_ingesta_completa(self):
        source, offers = self.offers()
        records = {}
        now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        events = ingest.reconcile(records, offers, "zarzuela", now)
        ingest.fetch_details(source, FakeHttp(), records, events)
        self.assertEqual({r["region"] for r in records.values()}, {"Comunidad de Madrid"})
