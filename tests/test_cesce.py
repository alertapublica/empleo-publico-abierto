import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import cesce

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        return fixture("cesce-trabaja.html")


def pdfs(http, url, what):
    if "TCF2" in url:
        return fixture("cesce-convocatoria-tcf2.txt")
    raise AssertionError(f"PDF no esperado: {url}")


def at(day):
    return datetime(2026, 11, day, 10, 0, tzinfo=timezone.utc)


class Page(unittest.TestCase):
    def setUp(self):
        self.items = cesce.parse_page(fixture("cesce-trabaja.html"))

    def test_solo_el_listado_de_empleo(self):
        # El de agentes mediadores («Agentes Exclusivos Cesce», también «Abierta») no se lee.
        self.assertEqual(len(self.items), 3)
        self.assertTrue(all(i["title"].startswith("CONVOCATORIA DEL") for i in self.items))

    def test_estado_y_documentos_con_su_fecha(self):
        first = self.items[0]
        self.assertEqual(first["state"], "abierto")
        self.assertEqual(first["ref"], "19939583")
        self.assertEqual(first["documents"][0]["label"], "Convocatoria")
        self.assertEqual(first["documents"][0]["date"], "2026-11-10")
        self.assertTrue(first["documents"][0]["url"].startswith("https://www.cesce.es/documents/"))
        self.assertEqual([i["state"] for i in self.items], ["abierto", "curso", "curso"])

    def test_estado_desconocido_detiene_la_fuente(self):
        html = fixture("cesce-trabaja.html").replace("Abierta", "Suspendida", 1)
        with self.assertRaises(SourceLayoutError):
            cesce.parse_page(html)

    def test_pagina_sin_listado(self):
        with self.assertRaises(SourceLayoutError):
            cesce.parse_page("<p>Trabaja con nosotros</p>")


class Deadlines(unittest.TestCase):
    def test_sin_anio_vale_el_de_la_publicacion(self):
        found = cesce.deadlines_in(fixture("cesce-convocatoria-tcf2.txt"), date(2026, 11, 10))
        self.assertEqual(found, [(date(2026, 11, 22), None)])

    def test_sin_anio_y_antes_de_publicar_es_el_siguiente(self):
        text = "El plazo de admisión de solicitudes será desde el día 28 de diciembre hasta el día 8 de enero."
        self.assertEqual(cesce.deadlines_in(text, date(2026, 12, 28)), [(date(2027, 1, 8), None)])

    def test_ampliacion_con_anio(self):
        found = cesce.deadlines_in(fixture("cesce-ampliacion-ps4.txt"), date(2026, 10, 9))
        self.assertEqual(found, [(date(2026, 10, 25), None)])

    def test_frase_literal_del_plazo(self):
        self.assertEqual(cesce.sentences_of(fixture("cesce-convocatoria-tcf2.txt")), [
            "El plazo de admisión de solicitudes será desde el día 10 de noviembre hasta el día 22 de "
            "noviembre, ambos incluidos."])
        self.assertEqual(cesce.sentences_of(fixture("cesce-ampliacion-ps4.txt")), [
            "Informamos de la ampliación del plazo de admisión de solicitudes para el siguiente proceso "
            "hasta el 25 de octubre de 2026."])

    def test_otros_plazos_no_cuentan(self):
        # «Se respetarán 3 días… para posibles subsanaciones»: no es el plazo de solicitudes.
        self.assertEqual(cesce.deadlines_in(fixture("cesce-convocatoria-ps4.txt"), date(2026, 9, 28)),
                         [(date(2026, 10, 11), None)])


class Source(unittest.TestCase):
    def read(self, now):
        source = cesce.CesceSource(now=now)
        with mock.patch.object(cesce, "read_pdf", pdfs):
            offers = source.list_offers(FakeHttp())
            notices = source.list_announcements(FakeHttp())
            details = [source.fetch_detail(FakeHttp(), offer) for offer in offers]
        return offers, notices, details

    def test_abierta_con_plazo_es_oferta(self):
        offers, notices, details = self.read(at(11))
        (offer,) = offers
        self.assertEqual(offer.title, "Técnico comercial de financiación")
        self.assertEqual((offer.deadline, offer.kind, offer.positions), ("2026-11-22", "indefinido", 1))
        self.assertEqual(offer.published_on, "2026-11-10")
        self.assertNotIn(offer.ref, {n.process for n in notices})
        sections = {s["title"]: s["html"] for s in details[0].sections}
        self.assertIn("hasta el día 22 de noviembre", sections["Plazo"])
        self.assertIn("Anexo I. Perfil del puesto", sections["Documentos de la convocatoria"])

    def test_las_demas_son_procesos_sin_anexos(self):
        _, notices, _ = self.read(at(11))
        self.assertEqual({n.process[:40] for n in notices},
                         {"CONVOCATORIA DEL 28 DE OCTUBRE DE 2026 D", "CONVOCATORIA DEL 28 DE SEPTIEMBRE DE 202"})
        titles = [n.title for n in notices if "SEPTIEMBRE" in n.process]
        self.assertEqual(titles, ["Convocatoria", "Ampliación del plazo de admisión de solicitudes",
                                  "Listado de Admitidos", "Valoración fase concurso"])
        listado = next(n for n in notices if n.title == "Listado de Admitidos" and "SEPTIEMBRE" in n.process)
        self.assertEqual((listado.date, listado.state, listado.contract), ("2026-10-27", "curso", "temporal"))

    def test_vencido_el_plazo_pasa_a_proceso(self):
        offers, notices, _ = self.read(at(23))
        self.assertEqual(offers, [])
        abierta = [n for n in notices if "NOVIEMBRE" in n.process]
        self.assertEqual([n.title for n in abierta], ["Convocatoria"])
        self.assertEqual((abierta[0].state, abierta[0].via), ("curso", "tasa"))

    def test_el_ultimo_dia_sigue_abierta(self):
        offers, _, _ = self.read(at(22))
        self.assertEqual([o.deadline for o in offers], ["2026-11-22"])


if __name__ == "__main__":
    unittest.main()
