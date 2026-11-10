import unittest
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import puertos

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://www.puertos.es/institucional/recursos-humanos/ofertas-de-empleo/"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def get(self, url):
        if url == puertos.LISTING:
            return fixture("puertos-listado.html")
        if url == puertos.AUTHORITIES:
            return fixture("puertos-autoridades.html")
        name = {
            "responsable-de-estadistica": "puertos-ficha-abierta.html",
            "tecnicoa-de-medio-ambiente-0": "puertos-ficha-cerrada.html",
        }.get(puertos.slug_of(url), "puertos-ficha-aviso.html")
        return fixture(name)


class Lectura(unittest.TestCase):
    def test_listado_incluye_avisos_y_convocatorias_internas(self):
        entries = puertos.parse_list(fixture("puertos-listado.html"))
        self.assertEqual(len(entries), 12)
        self.assertEqual(entries[0]["url"], BASE + "responsable-de-estadistica")

    def test_ficha_abierta(self):
        detail = puertos.parse_detail(fixture("puertos-ficha-abierta.html"))
        self.assertEqual(detail["deadline"], "2026-11-26")
        self.assertEqual(detail["positions"], 1)
        self.assertEqual(detail["agreement"], "Dentro de Convenio")
        self.assertEqual(detail["location"], "Madrid")
        self.assertEqual(len(detail["documents"]), 5)

    def test_ficha_cerrada_no_enlaza_listas_de_personas(self):
        detail = puertos.parse_detail(fixture("puertos-ficha-cerrada.html"))
        self.assertEqual(detail["deadline"], "2026-10-13")
        self.assertIsNone(detail["location"])
        labels = " ".join(label for label, _ in detail["documents"])
        self.assertNotIn("Admitidas", labels)
        self.assertIn("Bases", labels)

    def test_una_modificacion_de_una_lista_de_personas_no_se_enlaza(self):
        html = """<div class="field--name-body"><ul><li>1 plaza</li></ul></div>
        <div class="field--name-field-document-list">
        <a href="/a.pdf">Modificación de la Relación de Personas Admitidas</a>
        <a href="/b.pdf">Modificación de las Bases</a></div>"""
        self.assertEqual([label for label, _ in puertos.parse_detail(html)["documents"]],
                         ["Modificación de las Bases"])

    def test_fecha_limite_con_dia_de_la_semana(self):
        html = """<div class="field--name-body"><ul><li>1 plaza</li>
        <li>Fecha límite de presentación: Miércoles 17/06/2026</li></ul></div>"""
        self.assertEqual(puertos.parse_detail(html)["deadline"], "2026-06-17")

    def test_un_aviso_no_tiene_plazo(self):
        self.assertIsNone(puertos.parse_detail(fixture("puertos-ficha-aviso.html"))["deadline"])

    def test_pagina_sin_ofertas_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            puertos.parse_list("<h1>Mantenimiento</h1>")


class Seleccion(unittest.TestCase):
    def test_descarta_vencidas_avisos_e_internas(self):
        entries = [
            {"title": "Abierta", "deadline": "2026-11-26"},
            {"title": "Vencida", "deadline": "2026-10-13"},
            {"title": "Aviso", "deadline": None},
            {"title": "Jefe - Convocatoria Intraportuaria", "deadline": "2026-11-26"},
            {"title": "Sub - Convocatoria Intraadministrativa", "deadline": "2026-11-26"},
        ]
        self.assertEqual([e["title"] for e in puertos.select_offers(entries, "2026-11-07")], ["Abierta"])

    def test_vence_hoy_sigue_abierta(self):
        entries = [{"title": "Última", "deadline": "2026-11-07"}]
        self.assertEqual(len(puertos.select_offers(entries, "2026-11-07")), 1)

    def test_ninguna_ficha_con_plazo_es_un_cambio_de_pagina(self):
        with self.assertRaises(SourceLayoutError):
            puertos.select_offers([{"title": "x", "deadline": None}], "2026-11-07")

    def test_detalle_guarda_documentos_y_sede_sin_mas_peticiones(self):
        source = puertos.PuertosSource()
        with mock.patch.object(puertos, "today_madrid", return_value="2026-11-07"):
            listed = source.list_offers(FakeHttp())
        self.assertEqual([o.ref for o in listed], ["responsable-de-estadistica"])
        self.assertEqual(listed[0].deadline, "2026-11-26")
        self.assertEqual(listed[0].positions, 1)
        self.assertEqual(listed[0].category, "Dentro de Convenio")
        detail = source.fetch_detail(None, listed[0])
        self.assertEqual(detail.location, "Madrid")
        self.assertIn("Bases", detail.sections[0]["html"])


class AutoridadesPortuarias(unittest.TestCase):
    def test_son_procesos_sin_plazo_con_su_autoridad(self):
        items = puertos.PuertosSource().list_announcements(FakeHttp())
        self.assertEqual(len(items), 10)  # 12 menos 2 intraportuarias
        first = items[0]
        self.assertEqual(first.process, "Responsable de Operaciones y Servicios Portuarios (Digitalización) "
                                        "(Autoridad Portuaria: Bahía de Algeciras)")
        self.assertEqual((first.date, first.state, first.deadline), ("", "curso", None))
        self.assertEqual(first.location, "Bahía de Algeciras")  # la autoridad, tal cual
        self.assertEqual(first.process_url, BASE + "responsable-de-operaciones-y-servicios-portuarios-digitalizacion")
        self.assertFalse(any("Intraportuaria" in item.process for item in items))

    def test_sin_autoridad_es_un_cambio_de_pagina(self):
        html = """<article class="node--type-job-offer"><h2 class="offer__title">Policía Portuario</h2>
        <a class="offer__link--item" href="/x">Saber más</a></article>"""
        http = mock.Mock(get=lambda url: html)
        with self.assertRaises(SourceLayoutError):
            puertos.PuertosSource().list_announcements(http)
