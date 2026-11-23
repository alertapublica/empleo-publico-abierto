import unittest
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path

from bs4 import BeautifulSoup

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import ineco

FIXTURES = Path(__file__).parent / "fixtures"
TODAY = date(2026, 11, 16)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def processes(items):
    return {i.process: (i.state, i.deadline, i.deadline_time) for i in items}


class FakeHttp:
    def __init__(self, ordinaria="ineco-ordinaria.html"):
        self.pages = {ineco.ORDINARIA: ordinaria, ineco.ESPECIFICA: "ineco-especifica.html"}

    def get(self, url):
        return fixture(self.pages[url])


class Hoy(unittest.TestCase):
    """Páginas del 16/11/2026: ningún bloque en plazo."""

    def setUp(self):
        self.ordinaria = ineco.parse_page(fixture("ineco-ordinaria.html"), ineco.ORDINARIA, TODAY)
        self.especifica = ineco.parse_page(fixture("ineco-especifica.html"), ineco.ESPECIFICA, TODAY)

    def test_un_proceso_por_seccion_de_comunicados(self):
        self.assertEqual(processes(self.ordinaria), {
            "Tasa de reposición ordinaria 2026 (TRO26)": ("curso", None, None),
            "Tasa de reposición ordinaria 2025 (TRO25)": ("finalizado", None, None),
        })
        self.assertEqual(processes(self.especifica), {
            "Tasa de reposición específica 2026 (TRE26)": ("curso", None, None),
            # «COMUNICADOS TR-REPESCA» toma el estado del bloque «TR-REPESCA 2 – ENERO».
            "Repesca de tasas de reposición (TR-REPESCA)": ("curso", None, None),
            "Tasa de reposición específica 2024 (TRE24)": ("finalizado", None, None),
            "Tasa de reposición específica 2023 (TRE23)": ("finalizado", None, None),
        })

    def test_datos_del_proceso(self):
        for item in self.ordinaria + self.especifica:
            self.assertEqual((item.via, item.access, item.contract, item.system),
                             ("tasa", "libre", "indefinido", "concurso-oposicion"))
            self.assertIsNone(item.apply_url)
        self.assertEqual({i.process_url for i in self.especifica}, {ineco.ESPECIFICA})
        self.assertEqual({i.url for i in self.especifica if "TRE26" in i.process}, {f"{ineco.ESPECIFICA}#section-9"})

    def test_cada_rotulo_de_una_entrada_es_un_comunicado(self):
        del_dia = [i.title for i in self.ordinaria if i.date == "2026-11-16"]
        self.assertEqual(len(del_dia), 3)
        self.assertTrue(del_dia[0].startswith("PUBLICACIÓN DEL LISTADO CON LAS CALIFICACIONES DEFINITIVAS"))
        self.assertTrue(del_dia[1].startswith("PUBLICACIÓN DE LA RELACIÓN DE PERSONAS CANDIDATAS QUE OBTIENEN PLAZA"))
        self.assertTrue(del_dia[2].startswith("PUESTOS DEL BLOQUE 4"))

    def test_las_frases_del_cuerpo_en_negrita_no_son_comunicados(self):
        titles = [i.title for i in self.ordinaria + self.especifica]
        self.assertFalse([t for t in titles if t.startswith("Se recuerda")])

    def test_entrada_sin_rotulo_usa_su_primer_parrafo(self):
        (item,) = [i for i in self.ordinaria if i.date == "2026-06-04"]
        self.assertTrue(item.title.startswith("Se informa a las personas participantes"))
        self.assertIn("TRO26-OPS-006", item.title)

    def test_fecha_con_anyo_de_dos_cifras(self):
        self.assertIn("PUBLICACIÓN DE CORRECCIÓN DE ERRORES EN EL ANEXO TRO26-XO-005 DEL BLOQUE 1 DE LA TASA DE "
                      "REPOSICIÓN ORDINARIA 2026 EN LA EMPRESA INECO.",
                      [i.title for i in self.ordinaria if i.date == "2026-02-25"])

    def test_el_contenedor_de_la_seccion_no_repite_el_primer_comunicado(self):
        keys = Counter(i.key for i in self.ordinaria + self.especifica)
        self.assertEqual([k for k, n in keys.items() if n > 1], [])


class EnPlazo(unittest.TestCase):
    """Captura de la Wayback del 7/6/2026: bloque 3 de la TRO26 abierto hasta las 11:59 del 12/6."""

    def parse(self, today):
        return ineco.parse_page(fixture("ineco-ordinaria-junio.html"), ineco.ORDINARIA, today)

    def test_abierto_con_fecha_y_hora_de_la_cabecera(self):
        items = self.parse(date(2026, 6, 7))
        self.assertEqual(processes(items)["Tasa de reposición ordinaria 2026 (TRO26)"], ("abierto", "2026-06-12", "11:59"))
        self.assertEqual({i.apply_url for i in items if "TRO26" in i.process}, {ineco.ORDINARIA})

    def test_pasado_el_dia_la_cabecera_atrasada_no_lo_reabre(self):
        items = self.parse(date(2026, 6, 13))
        self.assertEqual(processes(items)["Tasa de reposición ordinaria 2026 (TRO26)"], ("curso", None, None))

    def test_el_motor_cierra_a_la_hora(self):
        source, known = ineco.InecoSource(), {}
        source.list_announcements = lambda http: self.parse(date(2026, 6, 12))
        ingest.sync_announcements(source, None, known, datetime(2026, 6, 12, 9, 0, tzinfo=timezone.utc))  # 11:00
        self.assertEqual({r["state"] for r in known.values() if "TRO26" in r["process"]}, {"abierto"})
        ingest.sync_announcements(source, None, known, datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc))  # 12:00
        self.assertEqual({r["state"] for r in known.values() if "TRO26" in r["process"]}, {"curso"})


class Cabeceras(unittest.TestCase):
    def test_sin_anyo_toma_el_mas_cercano_a_hoy(self):
        label = "INSCRIPCIÓN HASTA 11:59 DEL 5 DE ENERO INCLUIDO – CLIQUE AQUÍ PARA INSCRIBIRSE"
        self.assertEqual(ineco._deadline(label, date(2026, 12, 20)), ("2027-01-05", "11:59"))
        self.assertEqual(ineco._deadline(label, date(2027, 1, 2)), ("2027-01-05", "11:59"))

    def test_sin_hora(self):
        self.assertEqual(ineco._deadline("INSCRIPCIÓN HASTA EL 19 DE OCTUBRE DE 2026", TODAY), ("2026-10-19", None))

    def page(self, header):
        return f"""<section id="section-5"><h2>Inscríbete</h2>
<div class="panel-title"><a>{header}</a></div></section>
<section id="section-7"><h2>Comunicados TRO26</h2><div class="no-col-sm-12">
<div class="col-sm-12"><p><strong>01/06/2026 (CONVOCATORIA TRO26 BLOQUE 3)</strong></p><p><strong>ABIERTO EL PLAZO</strong></p></div>
</div></section>
<section id="section-9"><h2>Listados TRO26</h2><div class="col-sm-12"><p><strong>02/06/2026 (TRO26 BLOQUE 3)</strong></p>
<p><strong>RELACIÓN PROVISIONAL DE PERSONAS ADMITIDAS</strong></p></div></section>"""

    def test_los_listados_no_se_leen(self):
        items = ineco.parse_page(self.page("CONVOCATORIA TRO26 - BLOQUE 3 JUNIO (RESUELTO)"), ineco.ORDINARIA, TODAY)
        self.assertEqual([(i.date, i.title, i.state) for i in items], [("2026-06-01", "ABIERTO EL PLAZO", "finalizado")])

    def test_estado_desconocido_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            ineco.parse_page(self.page("CONVOCATORIA TRO26 - BLOQUE 5 (PRÓXIMAMENTE)"), ineco.ORDINARIA, TODAY)

    def test_plazo_ilegible_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            ineco.parse_page(self.page("CONVOCATORIA TRO26 - BLOQUE 5 (INSCRIPCIÓN ABIERTA)"), ineco.ORDINARIA, TODAY)

    def test_cabecera_con_otra_forma_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            ineco.parse_page(self.page("BLOQUE 5 TRO26"), ineco.ORDINARIA, TODAY)

    def test_pagina_sin_comunicados_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            ineco.parse_page("<h1>Mantenimiento</h1>", ineco.ORDINARIA, TODAY)

    def test_comunicado_sin_fecha_detiene_la_fuente(self):
        html = self.page("CONVOCATORIA TRO26 - BLOQUE 3 JUNIO (RESUELTO)").replace("01/06/2026 ", "")
        with self.assertRaises(SourceLayoutError):
            ineco.parse_page(html, ineco.ORDINARIA, TODAY)


class Fuente(unittest.TestCase):
    def test_lee_las_dos_landings(self):
        items = ineco.InecoSource().list_announcements(FakeHttp(), now=datetime(2026, 11, 16, 12, tzinfo=timezone.utc))
        self.assertEqual(len({i.process for i in items}), 6)


LISTA = "ineco-epreselec-lista.html"
FICHA = "ineco-epreselec-ficha.html"
TECNICO, BECA, PERU = "3363422", "3256126", "3378652"


class Epreselec(unittest.TestCase):
    def setUp(self):
        self.offers = ineco.parse_list(fixture(LISTA), "Ineco")
        self.by_ref = {o.ref: o for o in self.offers}

    def test_listado(self):
        self.assertEqual(len(self.offers), 7)
        tecnico = self.by_ref[TECNICO]
        self.assertEqual((tecnico.title, tecnico.company, tecnico.kind, tecnico.country, tecnico.published_on),
                         ("28942 - Técnico/a de Instalacions en Edificación de Cliente.", "Ineco", None, "España",
                          "2026-11-16"))
        url = "https://ineco.epreselec.com/Ofertas/Ofertas.aspx?Id_Oferta=3363422"
        self.assertEqual((tecnico.url, tecnico.apply_url), (url, url))
        self.assertIsNone(tecnico.deadline)  # ePreselec no da plazo

    def test_tipo_y_pais(self):
        self.assertEqual({o.ref: (o.kind, o.country) for o in self.offers}, {
            TECNICO: (None, "España"), BECA: ("beca", "España"), PERU: (None, "Perú"),
            "3364044": (None, "Costa Rica"), "3362430": ("beca", "España"), "3343119": (None, "Otros Países"),
            "3340991": ("beca", "México")})

    def test_codigo_con_y_sin_guion(self):
        source = ineco.InecoSource()
        self.assertEqual(source.labels(self.by_ref[BECA].title, BECA),
                         {"title": "Beca Ingeniero/a de Estructuras", "code": "27600",
                          "source_title": "27600- Beca Ingeniero/a de Estructuras"})
        self.assertEqual(source.labels(self.by_ref["3362430"].title, "3362430")["code"], "28943")

    def test_total_que_no_cuadra(self):
        with self.assertRaises(SourceLayoutError):
            ineco.parse_list(fixture(LISTA).replace("Total ofertas: 7", "Total ofertas: 8"), "Ineco")

    def test_pagina_de_imperva(self):
        with self.assertRaises(SourceLayoutError):
            ineco.parse_list("<title>Pardon Our Interruption</title>", "Ineco")

    def test_tipo_desconocido(self):
        with self.assertRaises(SourceLayoutError):
            ineco.parse_list(fixture(LISTA).replace("(BECA)", "(PRÁCTICAS)", 1), "Ineco")


class EpreselecHttp:
    """Listado en GET; con `?Id_Oferta=`, la ficha de la 28942 o, para otra oferta, el listado sin ficha."""

    def __init__(self):
        self.gets = []

    def get(self, url):
        self.gets.append(url)
        if url == ineco.offer_url(TECNICO):
            return fixture(FICHA)
        assert url == ineco.EPRESELEC or url.startswith(ineco.EPRESELEC + "?Id_Oferta=")
        return fixture(LISTA)


class EpreselecFicha(unittest.TestCase):
    def setUp(self):
        self.http = EpreselecHttp()
        self.source = ineco.InecoSource()
        self.offers = {o.ref: o for o in self.source.list_offers(self.http)}

    def test_ficha_por_id_oferta(self):
        detail = self.source.fetch_detail(self.http, self.offers[TECNICO])
        self.assertEqual(self.http.gets[-1], "https://ineco.epreselec.com/Ofertas/Ofertas.aspx?Id_Oferta=3363422")
        self.assertEqual([s["title"] for s in detail.sections],
                         ["Oficina", "Descripción", "Funciones", "Requisitos", "Se ofrece"])
        self.assertEqual(detail.sections[0]["html"], "<p>CIVIL</p>")
        self.assertIn("<br/>- Redacción de las Especificaciones Técnicas de Instalaciones.", detail.sections[2]["html"])
        self.assertEqual((detail.location, detail.positions), ("Madrid", 1))

    def test_si_no_vuelve_la_ficha_avisa(self):
        with self.assertRaisesRegex(SourceLayoutError, "no devuelve la ficha 3256126"):
            self.source.fetch_detail(self.http, self.offers[BECA])

    def test_tope_de_fichas_por_lectura(self):
        for _ in range(ineco.FICHAS_POR_LECTURA):
            self.assertIsNotNone(self.source.fetch_detail(self.http, self.offers[TECNICO]))
        self.assertIsNone(self.source.fetch_detail(self.http, self.offers[TECNICO]))
        self.assertEqual(len(self.http.gets), 1 + ineco.FICHAS_POR_LECTURA)
        self.source.list_offers(self.http)  # lectura nueva: vuelve a haber cupo
        self.assertIsNotNone(self.source.fetch_detail(self.http, self.offers[TECNICO]))

    def test_captcha_de_imperva_corta_las_fichas(self):
        self.http.get = lambda url: self.http.gets.append(url) or "<title>Pardon Our Interruption</title>"
        with self.assertRaisesRegex(SourceLayoutError, "Imperva"):
            self.source.fetch_detail(self.http, self.offers[TECNICO])
        self.assertIsNone(self.source.fetch_detail(self.http, self.offers[TECNICO]))
        self.assertEqual(len(self.http.gets), 2)  # el listado y la ficha con captcha: no sigue

    def test_ficha_sin_funciones(self):
        html = fixture(FICHA).replace('id="ctl00_CPH_Body_lFunciones"', 'id="otra"')
        with self.assertRaises(SourceLayoutError):
            ineco.parse_detail(BeautifulSoup(html, "html.parser"), TECNICO)


if __name__ == "__main__":
    unittest.main()
