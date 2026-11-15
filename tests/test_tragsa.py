import unittest
import warnings
from datetime import date, datetime, timezone
from pathlib import Path

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import tragsa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Listing(unittest.TestCase):
    def test_lee_las_filas_reales(self):
        offers = tragsa.parse_listing(fixture("listado.html"), "temporal")
        self.assertEqual(len(offers), 3)
        first = offers[0]
        self.assertTrue(first.ref.isdigit())
        self.assertRegex(first.deadline, r"^\d{4}-\d{2}-\d{2}$")
        self.assertIn(first.company, ("Tragsa", "Tragsatec"))
        self.assertIn(f"jobid={first.ref}", first.url)
        self.assertIn(f"portal-empleo-acceso.aspx?jobid={first.ref}", first.apply_url)

    def test_tabla_con_fila_informativa_es_lista_vacia(self):
        self.assertEqual(tragsa.parse_listing(fixture("tabla-vacia.html"), "practicas"), [])

    def test_pagina_sin_tabla_con_aviso_es_lista_vacia(self):
        html = "<p>No se han encontrado resultados.</p>"
        self.assertEqual(tragsa.parse_listing(html, "bolsa"), [])

    def test_pagina_inesperada_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            tragsa.parse_listing("<h1>Mantenimiento</h1>", "temporal")

    def test_columnas_cambiadas_no_se_interpretan(self):
        html = fixture("listado.html").replace("Código oferta", "Referencia")
        with self.assertRaises(SourceLayoutError):
            tragsa.parse_listing(html, "temporal")


class Calls(unittest.TestCase):
    """Tabla por fases de incendios y bolsas (BRIF 2026, ID 56263)."""

    def test_fila_con_inscripcion_abierta_es_oferta(self):
        [offer] = tragsa.parse_listing(fixture("tragsa-convocatorias.html"), "temporal")
        self.assertEqual(offer.ref, "56263")
        self.assertTrue(offer.title.startswith("Capataz/a BRIF 2026_Cobertura"))
        self.assertTrue(offer.title.endswith("Pinofranqueado (Cáceres)"))
        self.assertEqual((offer.published_on, offer.opens_on), ("2026-11-13", "2026-11-13"))
        self.assertIn("ficha-oferta-empleo.aspx?tipo=CTI&jobid=56263", offer.url)
        self.assertIn("portal-empleo-acceso.aspx?jobid=56263", offer.apply_url)

    def test_hasta_a_las_cero_horas_es_el_final_del_dia_anterior(self):
        # Listado: «Hasta: 20/11/2026 00:00 h»; ficha: «se cerrará el día 19/11/2026 (23:59…)».
        [offer] = tragsa.parse_listing(fixture("tragsa-convocatorias.html"), "temporal")
        self.assertEqual((offer.deadline, offer.deadline_time), ("2026-11-19", "23:59"))

    def test_hasta_con_hora_se_respeta(self):
        html = fixture("tragsa-convocatorias.html").replace("Hasta: 20/11/2026 00:00 h", "Hasta: 20/11/2026 14:00 h")
        [offer] = tragsa.parse_listing(html, "temporal")
        self.assertEqual((offer.deadline, offer.deadline_time), ("2026-11-20", "14:00"))

    def test_otras_fases_no_son_ofertas(self):
        html = fixture("tragsa-convocatorias.html").replace(
            "Abierto plazo inscripción", "Publicación de candidaturas admitidas y no admitidas provisional")
        self.assertEqual(tragsa.parse_listing(html, "temporal"), [])

    def test_tabla_vacia_es_lista_vacia(self):
        self.assertEqual(tragsa.parse_listing(fixture("tragsa-convocatorias-vacia.html"), "bolsa"), [])

    def test_inscripcion_abierta_sin_fecha_final_no_pasa(self):
        html = fixture("tragsa-convocatorias.html").replace("Hasta:", "Fin:")
        with self.assertRaises(SourceLayoutError):
            tragsa.parse_listing(html, "temporal")

    def test_columnas_cambiadas_no_se_interpretan(self):
        html = fixture("tragsa-convocatorias.html").replace("Información sobre la fase", "Estado")
        with self.assertRaises(SourceLayoutError):
            tragsa.parse_listing(html, "temporal")


class Detail(unittest.TestCase):
    def test_lee_la_ficha_real(self):
        detail = tragsa.parse_detail(fixture("ficha.html"))
        self.assertEqual(detail.location, "València/Valencia")
        self.assertEqual(detail.parent_ref, "58241")
        titles = [section["title"] for section in detail.sections]
        self.assertIn("Funciones y Tareas", titles)
        self.assertNotIn("Título Oferta", titles)
        levels = {section["title"]: section["level"] for section in detail.sections}
        self.assertEqual(levels["Requisitos Específicos"], 2)
        self.assertEqual(levels["Titulación"], 3)

    def test_plazo_de_la_ficha_con_inicio_y_hora(self):
        detail = tragsa.parse_detail(fixture("ficha.html"))
        self.assertEqual((detail.opens_on, detail.deadline, detail.deadline_time),
                         ("2026-11-04", "2026-11-10", "23:59"))

    def test_entre_listado_y_ficha_manda_la_fecha_mayor(self):
        class Http:
            def get(self, url):
                return fixture("ficha.html")
        offer = tragsa.ListedOffer(ref="58644", title="t", company="Tragsa", url="https://x/ficha", apply_url="u",
                                   deadline="2026-11-09")
        detail = tragsa.TragsaSource().fetch_detail(Http(), offer)
        self.assertEqual((detail.deadline, detail.deadline_time), ("2026-11-10", "23:59"))
        offer.deadline = "2026-11-12"  # el listado da una fecha posterior: la ficha no la acorta
        detail = tragsa.TragsaSource().fetch_detail(Http(), offer)
        self.assertEqual((detail.deadline, detail.deadline_time, detail.opens_on), (None, None, "2026-11-04"))

    def test_empresa_y_vacantes_de_la_ficha(self):
        detail = tragsa.parse_detail(fixture("ficha.html"))
        self.assertEqual((detail.company, detail.positions), ("Tragsatec", 3))
        self.assertFalse({"Empresa", "Vacantes Previstas"} & {s["title"] for s in detail.sections})
        self.assertIsNone(detail.published_before)

    def test_el_listado_manda_en_empresa_y_vacantes_salvo_en_la_tabla_por_fases(self):
        class Http:
            def get(self, url):
                return fixture("ficha.html")
        source = tragsa.TragsaSource()
        offer = tragsa.ListedOffer(ref="58644", title="t", company="Tragsa", positions=1, url="https://x/ficha",
                                   apply_url="u", deadline="2026-11-09")
        detail = source.fetch_detail(Http(), offer)
        self.assertEqual((detail.company, detail.positions), (None, None))
        [fases] = tragsa.parse_listing(fixture("tragsa-convocatorias.html"), "temporal")  # 56263
        self.assertEqual((fases.company, fases.positions), (None, None))
        detail = source.fetch_detail(Http(), fases)
        self.assertEqual((detail.company, detail.positions), ("Tragsatec", 3))
        sin_empresa = fixture("ficha.html").replace("<p>Tragsatec</p>", "<p></p>")
        detail = source.fetch_detail(type("H", (), {"get": lambda self, url: sin_empresa})(), fases)
        self.assertEqual(detail.company, "Grupo Tragsa")

    def test_ampliacion_de_plazo_cita_la_publicacion_original(self):
        # 57867: el portal da la fecha de la ampliación (12/11); la ficha, la de la publicación.
        frase = ("En relación al proceso publicado el pasado 30/10/2026 se amplía el plazo de recepción de "
                 "candidaturas desde el 12/11/2026 hasta el 17/11/2026 a las 23:59 (hora peninsular).")
        html = fixture("ficha.html").replace("desde hoy día", frase + " desde hoy día", 1)
        self.assertIn(frase, html)
        self.assertEqual(tragsa.parse_detail(html).published_before, "2026-10-30")
        # Dos ampliaciones (57934): la cita es de la primera; el texto original conserva su «desde hoy día».
        segunda = html.replace("30/10/2026", "06/11/2026", 1)
        self.assertEqual(tragsa.parse_detail(segunda).published_before, "2026-11-04")

    def test_relectura_sustituye_el_grupo_guardado_por_la_empresa_de_la_ficha(self):
        # 56263 se guardó con «Grupo Tragsa» antes de leer la empresa en la ficha; el registro
        # reconstruye el ListedOffer con ese valor.
        class Http:
            def get(self, url):
                return fixture("ficha.html")
        [fases] = tragsa.parse_listing(fixture("tragsa-convocatorias.html"), "temporal")
        record = ingest._record("tragsa", fases, "2026-11-13T00:00:00+00:00")
        record.update(company="Grupo Tragsa", detail_ok=True, detail_version=2, location="Cáceres")
        offers = {"56263": record}
        ingest.fetch_details(tragsa.TragsaSource(), Http(), offers, [])
        self.assertEqual((record["company"], record["positions"]), ("Tragsatec", 3))
        ingest.reconcile(offers, [fases], "tragsa", datetime(2026, 11, 14, tzinfo=timezone.utc))
        self.assertEqual(record["company"], "Tragsatec")  # la siguiente lectura del listado no la borra

    def test_ficha_vaciada_al_cerrar(self):
        self.assertIsNone(tragsa.parse_detail("<section>sin datos</section>"))


class Portal(unittest.TestCase):
    def test_lee_filas_y_fecha_americana(self):
        rows = tragsa.parse_portal_rows(fixture("portal.html"))
        self.assertEqual(len(rows), 2)
        row = rows["58599"]
        self.assertEqual(row["published_on"], "2026-11-06")  # 11/06/2026 = 6 de noviembre
        self.assertEqual(row["location"], "Las Palmas")
        self.assertEqual(row["family"], "Apoyo Administrativo")

    def test_respuesta_ajax_con_cdata(self):
        html = "<![CDATA[" + fixture("portal.html") + "]]>"
        self.assertEqual(len(tragsa.parse_portal_rows(html)), 2)

    def test_la_paginacion_en_xml_no_ensucia_el_registro(self):
        html = '<?xml version="1.0"?><PAGE id="x"><FIELD><![CDATA[' + fixture("portal.html") + "]]></FIELD></PAGE>"
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            self.assertEqual(len(tragsa.parse_portal_rows(html)), 2)
        self.assertEqual(caught, [])

    def test_portal_sin_filas_es_un_fallo_no_una_lista_vacia(self):
        class Http:
            def get(self, url):
                return "<html><body>Mantenimiento</body></html>"
        with self.assertRaises(SourceLayoutError):
            tragsa.TragsaSource().enrich(Http())


class FakeHttp:
    def get(self, url):
        if url == tragsa.HUB:
            return '<a href="/es/x/ofertas-empleo-indefinido/tasas-tre/Paginas/default.aspx">tre</a>'
        if "ofertas-empleo-indefinido/tasas-tre" in url:
            return fixture("tragsa-proceso.html")
        return "<p>No se han encontrado resultados.</p>"


class Process(unittest.TestCase):
    URL = "https://www.tragsa.es/es/x/ofertas-empleo-indefinido/Paginas/default.aspx"

    def read(self, today):
        return tragsa.parse_process(fixture("tragsa-proceso.html"), self.URL, today)

    def test_lee_el_plazo_del_cuerpo_del_comunicado(self):
        process = self.read(date(2026, 11, 7))
        self.assertTrue(process["open"])
        self.assertEqual(process["deadline"], "2026-11-10")  # no el de alegaciones, 30 de noviembre
        self.assertEqual(process["deadline_time"], "23:59")
        self.assertEqual(process["apply_url"], "https://grupotragsatre2026.iformalia.es")
        self.assertTrue(process["partial"])
        self.assertIn("bloques 5 y 7", process["notice_html"])

    def test_el_ultimo_dia_sigue_abierto_y_el_siguiente_no(self):
        self.assertTrue(self.read(date(2026, 11, 10))["open"])
        closed = self.read(date(2026, 11, 11))
        self.assertFalse(closed["open"])
        self.assertEqual({i.state for i in closed["items"]}, {"curso"})
        self.assertEqual({i.deadline for i in closed["items"]}, {None})

    def test_datos_del_proceso_y_direccion_propia(self):
        item = self.read(date(2026, 11, 7))["items"][0]
        self.assertEqual((item.via, item.access, item.contract, item.system, item.state),
                         ("tasa", "libre", "indefinido", "concurso-oposicion", "abierto"))
        self.assertTrue(item.url.endswith("tasas-reposicion-especifica-2025-2026/Paginas/tre-2026-grupo-tragsa.aspx"))
        self.assertTrue(item.url.startswith("https://www.tragsa.es/"))

    def test_proceso_con_plazo_abierto_es_oferta_indefinida_con_su_ficha(self):
        source, http = tragsa.TragsaSource(today=date(2026, 11, 7)), FakeHttp()
        offers = source.list_offers(http)
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual((offer.kind, offer.deadline, offer.company), ("indefinido", "2026-11-10", "Grupo Tragsa"))
        self.assertEqual(offer.published_on, "2026-10-26")  # no depende del portal de candidatos
        self.assertIn("solo los bloques corregidos", offer.title)
        self.assertEqual(offer.apply_url, "https://grupotragsatre2026.iformalia.es")
        detail = source.fetch_detail(http, offer)
        self.assertEqual(detail.location, "Varias comunidades")
        self.assertIn("exclusivamente para estos bloques", detail.sections[0]["html"])
        self.assertEqual(len(source.list_announcements(http)), 3)

    def test_vencido_el_plazo_deja_de_ser_oferta(self):
        source = tragsa.TragsaSource(today=date(2026, 11, 11))
        self.assertEqual(source.list_offers(FakeHttp()), [])


class Announcements(unittest.TestCase):
    def setUp(self):
        self.items = tragsa.parse_announcements(fixture("anuncios.html"), "https://x/y")

    def test_extrae_fecha_proceso_y_titulo(self):
        self.assertEqual(len(self.items), 2)
        self.assertEqual(self.items[0].date, "2026-11-05")
        self.assertEqual(self.items[0].process, "Tasa de ejemplo")
        self.assertEqual(self.items[1].date, "2026-10-08")

    def test_no_copia_el_cuerpo_ni_codigos_de_candidatura(self):
        joined = " ".join(item.title for item in self.items)
        self.assertNotIn("Texto largo", joined)
        self.assertNotIn("HMV5428795", joined)
        self.assertIn("[código omitido]", joined)
        self.assertIn("TRO26-TRAGSATEC-184", joined)

    def test_descubre_solo_procesos_en_curso(self):
        html = """
        <a href="/es/x/ofertas-empleo-indefinido/tasa-a/Paginas/default.aspx">a</a>
        <a href="/es/x/ofertas-empleo-indefinido/tasas-cerradas/tasa-b/Paginas/default.aspx">b</a>
        <a href="/es/x/ofertas-empleo-indefinido/Paginas/ofertas-especificas.aspx">c</a>
        <a href="/es/x/ofertas-empleo-indefinido/tasa-a/Paginas/puestos-ofertados.aspx">d</a>"""
        urls = tragsa.discover_processes(html)
        self.assertEqual(len(urls), 1)
        self.assertIn("tasa-a/Paginas/default.aspx", urls[0])
