import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.areas import project_category
from empleo.model import SourceLayoutError
from empleo.sources import uhu

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Http:
    """El índice real del 2026-11-15; con `old_pages`, de la página 1 en adelante, el mismo con las fechas
    de 2025 (fuera del horizonte). Las 6 fichas en plazo reales y la de «Suelos regenerados»; para las otras
    tres vencidas, la del proyecto DGP_PIDI_2024_01054."""

    FICHAS = {"proyecto-epit1162023": "uhu-ficha-epit.html", "fin-feder-programa": "uhu-ficha-itaca.html",
              "proyecto-suelos-regenerados": "uhu-ficha-suelos.html", "ramon-y-cajal": "uhu-ficha-ryc.html",
              "finla-ayuda-cns2024": "uhu-ficha-cns.html", "proyecto-pcl2024": "uhu-ficha-pcl.html"}

    def __init__(self, old_pages=True):
        self.asked = []
        self.old_pages = old_pages

    def get(self, url):
        self.asked.append(url)
        if url.startswith(uhu.SITE + "/personal-tecnico-apoyo/convocatorias?"):
            html = fixture("uhu-convocatorias.html")
            return html.replace("/2026", "/2025") if self.old_pages and "&page=" in url else html
        return fixture(next((name for part, name in self.FICHAS.items() if part in url), "uhu-ficha-dgp.html"))


class List(unittest.TestCase):
    def test_tarjetas_con_ruta_fecha_titulo_y_plazo(self):
        rows = uhu.parse_list(fixture("uhu-convocatorias.html"))
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0], {
            "ref": "conv-pca-cttacion-tituladoa-grado-superior-cofin-ayudas-ramon-y-cajal-convocatoria",
            "url": "https://www.uhu.es/personal-tecnico-apoyo/convocatorias/"
                   "conv-pca-cttacion-tituladoa-grado-superior-cofin-ayudas-ramon-y-cajal-convocatoria",
            "title": "CONV PCA CTTACIÓN TITULADO/A GRADO SUPERIOR, COFIN.: AYUDAS RAMON Y CAJAL CONVOCATORIA 2023 Y "
                     "LA EPIT 2026. PROY “QUÍMICA ORGANOMETÁLICA Y SUPRAMOLECULAR DE METALES DE GRUPOS PRINCIPALES”, "
                     "(IP: D. ª MARÍA ÁNGELES FUENTES DOMÍNGUEZ).",
            "published_on": "2026-11-04", "opens_on": "2026-11-05", "deadline": "2026-11-18",
        })
        self.assertEqual([row["deadline"] for row in rows[-4:]], ["2026-11-05"] * 4)

    def test_enlace_cargar_mas(self):
        self.assertEqual(uhu.next_page(fixture("uhu-convocatorias.html"), uhu.INDEX),
                         uhu.INDEX + "&page=1")
        self.assertIsNone(uhu.next_page("<main><p>Nada</p></main>", uhu.INDEX))

    def test_plazos_contradictorios_detienen_la_fuente(self):
        html = fixture("uhu-convocatorias.html")
        twice = html.replace(">Application<", ">Solicitud (del 05/11/2026 al 30/11/2026)<", 1)
        reversed_ = html.replace("Solicitud (del 05/11/2026 al 18/11/2026)", "Solicitud (del 25/11/2026 al 18/11/2026)", 1)
        for broken in (twice, reversed_):
            with self.assertRaises(SourceLayoutError):
                uhu.parse_list(broken)

    def test_tarjeta_sin_plazo_se_queda_sin_fechas(self):
        html = fixture("uhu-convocatorias.html").replace("Solicitud (del 05/11/2026 al 18/11/2026)", "Solicitud", 1)
        rows = uhu.parse_list(html)
        self.assertEqual((rows[0]["opens_on"], rows[0]["deadline"]), (None, None))
        self.assertEqual(rows[1]["deadline"], "2026-11-18")

    def test_indice_sin_tarjetas_o_sin_plazos_o_tarjeta_rota_detienen_la_fuente(self):
        html = fixture("uhu-convocatorias.html")
        for broken in ("<main><p>Nada</p></main>", html.replace("Solicitud (del", "Impreso (del"),
                       html.replace("<span>04/11/2026</span>", "<span>4 nov</span>", 1),
                       html.replace('about="/personal-tecnico-apoyo/convocatorias/', 'about="/otra/', 1)):
            with self.assertRaises(SourceLayoutError):
                uhu.parse_list(broken)


class Project(unittest.TestCase):
    def test_codigo_delante_detras_o_dentro_de_las_comillas(self):
        cases = {
            "PARA EL DESARROLLO DEL PROYECTO “DGP_PIDI_2024_01054 ESTIMULACIÓN MECÁNICA EN OSTEOPOROSIS”, (ORDEN":
                ("Estimulación mecánica en osteoporosis", "DGP_PIDI_2024_01054"),
            'PARA EL DESARROLLO DEL PROYECTO EPIT1162023 “BIOESPUMAS PARA EDIFICIOS (MBIOF4BEES)", FINANCIADO POR':
                ("Bioespumas para edificios (MBIOF4BEES)", "EPIT1162023"),
            'PARA EL DESARROLLO DEL PROYECTO "NITROSOFT: MODELADO DE SUELOS (CNS2025-166171)". (INVESTIGADOR':
                ("Nitrosoft: modelado de suelos", "CNS2025-166171"),
            "para el desarrollo del Proyecto ITACA: Inteligencia Tecnológica (0369_ITACA_5_E), (INVESTIGADOR/A":
                ("ITACA: Inteligencia Tecnológica", "0369_ITACA_5_E"),
            "PARA EL DESARROLLO DEL PROYECTO VALORIZACIÓN DE RESIDUOS (VALORMINE) (REF.: DGP_PIDI_2024_00331), FIN":
                ("Valorización de residuos (VALORMINE)", "DGP_PIDI_2024_00331"),
            "PARA EL DESARROLLO DEL PROYECTO “QUÍMICA ORGANOMETÁLICA”, (INVESTIGADOR/A PRINCIPAL":
                ("Química organometálica", None),
        }
        for text, expected in cases.items():
            self.assertEqual(uhu.project_of(text), expected, text)

    def test_un_numero_sin_letras_no_es_codigo(self):
        self.assertEqual(uhu.project_of("PARA EL DESARROLLO DEL PROYECTO “2030 AGENDA”, FINANCIADO POR"),
                         ("2030 agenda", None))

    def test_descripcion_en_minusculas(self):
        self.assertEqual(uhu.project_of('para el desarrollo del proyecto epit1162023 “Bioespumas (MBIOF4BEES)", '
                                        'financiado por'), ("Bioespumas (MBIOF4BEES)", "epit1162023"))

    def test_sin_proyecto_unico_y_legible_no_hay_titulo(self):
        for text in ("POR LA QUE SE ANUNCIA CONVOCATORIA PÚBLICA",
                     "PARA EL DESARROLLO DEL PROYECTO “SUELOS REGENERADOS, FINANCIADO POR CONVENIO EN EL PROYECTO “SUELOS”",
                     "PARA EL DESARROLLO DEL PROYECTO “A”, Y PARA EL DESARROLLO DEL PROYECTO “B”, (IP: X)",
                     "PARA EL DESARROLLO DEL PROYECTO EPIT1162023 “BIOESPUMAS, (IP: X)",
                     "PARA EL DESARROLLO DEL PROYECTO “A”, (IP: X). PARA EL DESARROLLO DEL PROYECTO “B, (IP: Y)",
                     "PARA EL DESARROLLO DEL PROYECTO EUROPEO “BIOESPUMAS”, (IP: X)",
                     "PARA EL DESARROLLO DEL PROYECTO EPIT1162023 “BIOESPUMAS (CNS2025-166171)”, (IP: X)"):
            self.assertIsNone(uhu.project_of(text), text)


class Ficha(unittest.TestCase):
    def test_categoria_proyecto_resolucion_y_documentos(self):
        ficha = uhu.parse_ficha(fixture("uhu-ficha-dgp.html"))
        self.assertEqual(ficha["category"], "Técnico Grado Medio")
        self.assertEqual(ficha["project"], ("Estimulación mecánica en osteoporosis: estudio in vivo e in sílico de su "
                                            "potencial", "DGP_PIDI_2024_01054"))
        self.assertTrue(ficha["body"].startswith("<p>RESOLUCIÓN DE FECHA 3 DE NOVIEMBRE DE 2026"))
        self.assertEqual([label for label, _ in ficha["documents"]],
                         ["Convocatoria", "Solicitud (del 05/11/2026 al 18/11/2026)", "Application", "Job offer Euraxess"])
        self.assertEqual(ficha["documents"][0][1],
                         "https://tablon.uhu.es/alfrescoDocDownloader/download/7fe4b8f5-b4db-4342-93e1-8223eb6611e6")

    def test_ficha_sin_descripcion_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            uhu.parse_ficha(fixture("uhu-ficha-dgp.html").replace("field--name-body", "field--name-otro"))


class Source(unittest.TestCase):
    def test_solo_las_de_plazo_abierto_con_titulo_categoria_proyecto(self):
        http = Http()
        offers = uhu.UhuSource(now=at(11, 15)).list_offers(http)
        self.assertEqual(len(offers), 6)
        # Dos páginas del índice (la última tarjeta de la primera es de hace 25 días) y seis fichas.
        self.assertEqual(http.asked[:2], [uhu.INDEX, uhu.INDEX + "&page=1"])
        self.assertEqual(len(http.asked), 8)
        self.assertCountEqual([(offer.title, offer.code) for offer in offers], [
            ("Técnico Grado Medio · Estimulación mecánica en osteoporosis: estudio in vivo e in sílico de su potencial",
             "DGP_PIDI_2024_01054"),
            ("Titulado Grado Superior · Compuestos organometálicos sinergísticos en catálisis sostenible", "CNS2024-154163"),
            ("Titulado Grado Superior · ITACA: Inteligencia Tecnológica Ambiental para Circularidad en la Agricultura",
             "0369_ITACA_5_E"),
            ("Titulado Grado Superior · Innovative copper slag processing for raw material supply", "PCL2024-153497"),
            ("Titulado Grado Superior · Química organometálica y supramolecular de metales de grupos principales", None),
            ("Titulado Grado Superior Doctor · Bioespumas multifuncionales diseñadas para mejorar la eficiencia "
             "energética y sostenibilidad de edificios (MBIOF4BEES)", "EPIT1162023"),
        ])
        epit = next(offer for offer in offers if "epit1162023" in offer.ref)
        self.assertEqual(epit.title, "Titulado Grado Superior Doctor · Bioespumas multifuncionales diseñadas para mejorar "
                                     "la eficiencia energética y sostenibilidad de edificios (MBIOF4BEES)")
        self.assertEqual((epit.code, epit.category, epit.kind, epit.contract), ("EPIT1162023", "Titulado Grado Superior Doctor", None, None))
        self.assertEqual((epit.published_on, epit.opens_on, epit.deadline, epit.deadline_time),
                         ("2026-11-04", "2026-11-05", "2026-11-18", None))
        self.assertTrue(epit.source_title.startswith("CONV PCA CONTCIÓN TITULADO/A GRADO SUPERIOR DOCTOR"))
        url = ("https://www.uhu.es/personal-tecnico-apoyo/convocatorias/"
               "conv-pca-contcion-tituladoa-grado-superior-doctor-proyecto-epit1162023-bioespumas")
        self.assertEqual((epit.url, epit.apply_url, epit.company), (url, url, "Universidad de Huelva"))
        self.assertEqual(project_category(epit.title, "uhu"), "Titulado Grado Superior Doctor")
        itaca = next(offer for offer in offers if "fin-feder-programa" in offer.ref)
        self.assertEqual((itaca.title, itaca.code), ("Titulado Grado Superior · ITACA: Inteligencia Tecnológica Ambiental "
                                                     "para Circularidad en la Agricultura", "0369_ITACA_5_E"))

    def test_el_ultimo_dia_cuenta_entero(self):
        self.assertEqual(len(uhu.UhuSource(now=at(11, 18, 22)).list_offers(Http())), 6)  # 23:00 en Madrid
        self.assertEqual(uhu.UhuSource(now=at(11, 18, 23)).list_offers(Http()), [])

    def test_ficha_que_no_encaja_sale_con_el_titulo_de_la_tarjeta_y_avisa(self):
        http, source = Http(), uhu.UhuSource(now=at(11, 1))
        offers = source.list_offers(http)
        self.assertEqual(len(offers), 10)  # las del 21/10 en plazo y las del 4/11, por abrir
        suelos = next(offer for offer in offers if "suelos-regenerados" in offer.ref)
        self.assertTrue(suelos.title.startswith("Conv Pca Cttcion Titulado/A Grado Superior Doctor/A."))
        self.assertEqual((suelos.code, suelos.source_title, suelos.category),
                         (None, None, "Titulado Grado Superior Doctor"))
        with self.assertRaises(SourceLayoutError):
            source.fetch_detail(http, suelos)

    def test_ficha_con_la_resolucion_y_los_documentos(self):
        http, source = Http(), uhu.UhuSource(now=at(11, 15))
        offer = next(offer for offer in source.list_offers(http) if "dgppidi" in offer.ref)
        detail = source.fetch_detail(http, offer)
        self.assertEqual([section["title"] for section in detail.sections], ["La convocatoria", "Documentos"])
        self.assertIn("ESTIMULACIÓN MECÁNICA EN OSTEOPOROSIS", detail.sections[0]["html"])
        self.assertIn('<a href="https://euraxess.ec.europa.eu/jobs/477659">Job offer Euraxess</a>', detail.sections[1]["html"])
        self.assertIsNone(detail.location)

    def test_con_paginas_recientes_sin_fin_se_detiene(self):
        http = Http(old_pages=False)
        with self.assertRaises(SourceLayoutError):
            uhu.UhuSource(now=at(11, 15)).list_offers(http)
        self.assertEqual(len([url for url in http.asked if "?" in url]), uhu.MAX_PAGES)

    def test_sin_cargar_mas_acaba_en_la_primera_pagina(self):
        class Last(Http):
            def get(self, url):
                return super().get(url).replace('rel="next"', 'rel="prev"')
        http = Last()
        self.assertEqual(len(uhu.UhuSource(now=at(11, 15)).list_offers(http)), 6)
        self.assertEqual(len([url for url in http.asked if "?" in url]), 1)

    def test_una_antigua_con_plazo_largo_en_la_pagina_siguiente_entra(self):
        class Long(Http):
            def get(self, url):
                html = super().get(url)
                return html.replace("al 05/11/2025)", "al 30/12/2026)", 1) if "&page=" in url else html
        offers = uhu.UhuSource(now=at(11, 15)).list_offers(Long())
        self.assertEqual(len(offers), 7)


if __name__ == "__main__":
    unittest.main()
