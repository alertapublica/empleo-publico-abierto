import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo import areas
from empleo.model import SourceLayoutError
from empleo.sources import unileon

FIXTURES = Path(__file__).parent / "fixtures"
# Listado filtrado por PTGAS laboral + personal investigador con inicio desde el 01-09-2026 (2026-11-16): dos páginas
PAGE_1 = (FIXTURES / "unileon-lista.html").read_text(encoding="utf-8")
PAGE_2 = (FIXTURES / "unileon-lista-p2.html").read_text(encoding="utf-8")
FICHA = (FIXTURES / "unileon-ficha-ag433.html").read_text(encoding="utf-8")  # 12/11–26/11, «hasta las 12:00 horas»
PTGAS = (FIXTURES / "unileon-ficha-ptgas.html").read_text(encoding="utf-8")  # sin hora en el cuerpo
AG433 = "convocatoria-de-plaza-de-personal-con-cargo-al-proyecto-ag433-personal"


def at(year, month, day, hour=10, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


class Http:
    """Primera página para cualquier URL del listado sin `page=1`; la ficha AG433 para la suya y la de PTGAS
    (sin hora ni fecha en el cuerpo) para las demás."""

    def __init__(self, page_1=PAGE_1, ficha=FICHA):
        self.asked, self.page_1, self.ficha = [], page_1, ficha

    def get(self, url):
        self.asked.append(url)
        if "?" in url:
            return PAGE_2 if "page=1" in url else self.page_1
        return self.ficha if url.endswith(AG433) else PTGAS


def row(title, kind="Personal Investigador"):
    return {"kind": kind, "title": title}


class List(unittest.TestCase):
    def test_tarjetas_y_siguiente_pagina(self):
        rows, following = unileon.parse_list(PAGE_1)
        self.assertEqual(len(rows), 20)
        self.assertIn("&page=1", following)
        self.assertTrue(following.startswith(unileon.LIST + "?"))
        first = next(r for r in rows if r["ref"] == AG433)
        self.assertEqual((first["kind"], first["access"], first["opens_on"], first["deadline"]),
                         ("Personal Investigador", "Libre", "2026-11-12", "2026-11-26"))
        self.assertEqual(first["url"], f"{unileon.LIST}/{AG433}")
        self.assertEqual({r["access"] for r in rows}, {"Libre", "Bolsa", "Consurso de Traslados"})
        rows, following = unileon.parse_list(PAGE_2)
        self.assertEqual((len(rows), following), (18, None))

    def test_pide_por_tipo_y_fecha_de_inicio(self):
        url = unileon.index_url(at(2026, 11, 16))
        self.assertEqual(url, unileon.LIST + "?field_tipo_de_plaza_target_id%5B1028%5D=1028"
                         "&field_tipo_de_plaza_target_id%5B1029%5D=1029&field_fecha_de_inicio_value=19-07-2026")

    def test_tipo_o_sistema_desconocidos_detienen(self):
        with self.assertRaisesRegex(SourceLayoutError, "tipo de plaza inesperado"):
            unileon.parse_list(PAGE_1.replace('hreflang="es">Personal Investigador</a>', 'hreflang="es">PDI Laboral</a>', 1))
        with self.assertRaisesRegex(SourceLayoutError, "sistema de acceso desconocido"):
            unileon.parse_list(PAGE_1.replace("<span>Libre</span>", "<span>Reingreso</span>", 1))
        with self.assertRaisesRegex(SourceLayoutError, "no es el listado"):
            unileon.parse_list("<html><body><p>Mantenimiento</p></body></html>")


class Labels(unittest.TestCase):
    def test_categoria_y_proyecto(self):
        found = unileon.labels(row("Convocatoria de Plaza de Personal con cargo al Proyecto AG433. Personal Técnico"))
        self.assertEqual(found, {"title": "Personal técnico · Proyecto AG433", "category": "Personal técnico",
                                 "code": "AG433", "positions": None,
                                 "source_title": "Convocatoria de Plaza de Personal con cargo al Proyecto AG433. "
                                                 "Personal Técnico"})
        found = unileon.labels(row("Convocatoria de Plaza de Personal con cargo al Proyecto AM250. Personal Técnico "
                                   "(TP 20 horas - 5 plazas)"))
        self.assertEqual((found["title"], found["positions"]),
                         ("Personal técnico (TP 20 horas - 5 plazas) · Proyecto AM250", 5))
        found = unileon.labels(row("Convocatoria de 2 Plazas de Personal con cargo al Proyecto AM275. Personal Técnico "
                                   "(10 Horas)"))
        self.assertEqual((found["title"], found["positions"], found["code"]),
                         ("Personal técnico (10 Horas) · Proyecto AM275", 2, "AM275"))
        found = unileon.labels(row("Convocatoria de Plaza de Personal con cargo al Proyecto Ñ79 - TP7,5. Personal Técnico"))
        self.assertEqual((found["title"], found["code"]), ("Personal técnico · Proyecto Ñ79 - TP7,5", "Ñ79 - TP7,5"))

    def test_formato_largo_de_mayo(self):
        found = unileon.labels(row("CONVOCATORIA PÚBLICA PARA LA CONTRATACIÓN DE PERSONAL INVESTIGADOR Y TÉCNICO DE LA "
                                   "UNIVERSIDAD DE LEÓN CON CARGO A CONVENIOS, CONTRATOS  DEL ART.60 DE LA L.O.S.U. Y "
                                   "PROYECTOS DE INVESTIGACIÓN, CLAVE AG424_II"))
        self.assertEqual((found["title"], found["category"], found["code"]),
                         ("Personal investigador y técnico · Clave AG424_II", "Personal investigador y técnico",
                          "AG424_II"))

    def test_ptgas_literal(self):
        found = unileon.labels(row("CONVOCATORIA CONCURSO-OPOSICIÓN LIBRE. PERSONAL LABORAL GRUPOS II, III y IVA",
                                   kind="PTGAS Laboral"))
        self.assertNotIn(" · ", found["title"])
        self.assertIsNone(found["code"])
        self.assertEqual(found["source_title"], "CONVOCATORIA CONCURSO-OPOSICIÓN LIBRE. PERSONAL LABORAL GRUPOS II, "
                                                "III y IVA")

    def test_investigacion_por_el_titulo(self):
        self.assertEqual(areas.project_category("Personal técnico · Proyecto AG433", "unileon"), "Personal técnico")
        self.assertEqual(areas.classify("Personal técnico · Proyecto AG433", source="unileon",
                                        group="universidades")[0][0], "investigacion")


class Ficha(unittest.TestCase):
    def test_hora_publicacion_y_adjuntos(self):
        ficha = unileon.parse_ficha(FICHA, "2026-11-26")
        self.assertEqual((ficha["deadline_time"], ficha["published_on"]), ("12:00", "2026-11-12"))
        self.assertIn("hasta las 12:00 horas del día 26 de noviembre de 2026", ficha["html"])
        self.assertIn('<a href="https://script.google.com/', ficha["html"])
        self.assertIn('<li><a href="http://www.unileon.es/files/2026-11/convocatoria_ag433_20261112nw.pdf">'
                      'Convocatoria (12/11/2026)</a></li>', ficha["html"])
        self.assertNotIn("<table", ficha["html"])

    def test_ptgas_sin_hora_ni_fecha_de_convocatoria(self):
        ficha = unileon.parse_ficha(PTGAS, "2026-05-19")
        self.assertEqual((ficha["deadline_time"], ficha["published_on"]), (None, None))
        self.assertIn("por el sistema general de acceso libre", ficha["html"])
        self.assertIn("BOE-A-2026-9344.pdf</a></li>", ficha["html"])

    def test_otro_fin_de_plazo_detiene(self):
        with self.assertRaisesRegex(SourceLayoutError, "otro fin de plazo"):
            unileon.parse_ficha(FICHA, "2026-11-27")
        with self.assertRaisesRegex(SourceLayoutError, "ficha sin título"):
            unileon.parse_ficha("<html><body><p>Error</p></body></html>", "2026-11-26")


class Offers(unittest.TestCase):
    def test_hoy_solo_ag433(self):
        http = Http()
        source = unileon.UnileonSource(now=at(2026, 11, 16))
        [offer] = source.list_offers(http)
        self.assertEqual((offer.ref, offer.title, offer.code, offer.category, offer.kind),
                         (AG433, "Personal técnico · Proyecto AG433", "AG433", "Personal técnico", None))
        self.assertEqual((offer.published_on, offer.opens_on, offer.deadline, offer.deadline_time),
                         ("2026-11-12", "2026-11-12", "2026-11-26", "12:00"))
        self.assertEqual(offer.apply_url, offer.url)
        self.assertEqual(len(http.asked), 3)  # dos páginas y la ficha; bolsa y traslados abiertos, sin ficha
        detail = source.fetch_detail(Http(page_1="sin uso"), offer)
        self.assertEqual((detail.deadline_time, detail.sections[0]["title"]), ("12:00", "La convocatoria"))
        self.assertIn("Formulario de Solicitud", detail.sections[0]["html"])

    def test_el_ultimo_dia_hasta_las_doce(self):
        self.assertEqual(len(unileon.UnileonSource(now=at(2026, 11, 26, 10, 59)).list_offers(Http())), 1)
        self.assertEqual(unileon.UnileonSource(now=at(2026, 11, 26, 11, 0)).list_offers(Http()), [])  # 12:00 en Madrid

    def test_bolsa_con_acceso_libre_fuera(self):
        # El 25/10: «Convocatoria Bolsa Sucesiva…» (22/10–28/10, acceso «Libre»), cinco plazas en plazo y cinco que
        # aún no han abierto (también salen)
        offers = unileon.UnileonSource(now=at(2026, 10, 25)).list_offers(Http())
        self.assertEqual(len(offers), 10)
        self.assertEqual(sum(o.opens_on > "2026-10-25" for o in offers), 5)
        self.assertFalse(any("bolsa" in o.title.lower() for o in offers))
        self.assertTrue(all(" · Proyecto " in o.title for o in offers))

    def test_demasiadas_paginas_detiene(self):
        class Endless(Http):
            def get(self, url):
                self.asked.append(url)
                return PAGE_1
        with self.assertRaisesRegex(SourceLayoutError, "más de 10 páginas"):
            unileon.UnileonSource(now=at(2026, 11, 16)).list_offers(Endless())


if __name__ == "__main__":
    unittest.main()
