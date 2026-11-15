import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import ifapa

FIXTURES = Path(__file__).parent / "fixtures"
NODE = ifapa.SITE + "/agriculturaypesca/ifapa/web/node/"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    """Listado real del 2026-11-15; las fichas 65479 y 65478 son reales, el resto copia la 65479."""

    def __init__(self, pages=None, ficha=None):
        self.asked, self.pages, self.ficha = [], pages or {}, ficha

    def get(self, url):
        self.asked.append(url)
        if url.startswith(ifapa.PAGE):
            return self.pages.get(url) or fixture("ifapa-empleo.html")
        if self.ficha:
            return self.ficha
        return fixture("ifapa-ficha-65478.html" if url.endswith("/65478") else "ifapa-ficha-65479.html")


def at(month, day, year=2026):
    return datetime(year, month, day, 10, 0, tzinfo=timezone.utc)


class Listing(unittest.TestCase):
    def test_diez_filas_con_plazo(self):
        rows = ifapa.parse_list(fixture("ifapa-empleo.html"))
        self.assertEqual(len(rows), 10)
        self.assertEqual((rows[0]["ref"], rows[0]["opens_on"], rows[0]["deadline"]), ("65480", "2026-11-16", "2026-11-27"))
        self.assertEqual(rows[0]["type"], "Contratos Específicos de I+D+F")
        self.assertTrue(rows[1]["title"].startswith("Convocatoria de contratos laborales"))

    def test_sin_filas_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            ifapa.parse_list("<div class='view-empleo-publico'></div>")


class Ficha(unittest.TestCase):
    def test_categoria_y_proyecto_con_su_codigo(self):
        ficha = ifapa.parse_ficha(fixture("ifapa-ficha-65479.html"))
        self.assertEqual(ficha["published_on"], "2026-11-13")
        self.assertEqual(ficha["contract"], {
            "title": "Técnico Superior · Innovación y fomento de una acuicultura de moluscos sostenible en el litoral sur atlántico andaluz (MOLUSOS)",
            "code": "PR.FEMPA.DIP2023A.003", "positions": 1, "location": "IFAPA Centro Agua del Pino (Cartaya - Huelva)"})
        self.assertIn("24:00 horas", ficha["body"])
        self.assertNotIn("No puede garantizarse", ficha["body"])

    def test_codigo_entre_parentesis(self):
        contract = ifapa.parse_ficha(fixture("ifapa-ficha-65478.html"))["contract"]
        self.assertEqual(contract["code"], "PR.INTC.ATIDRAI26.004")
        self.assertTrue(contract["title"].startswith("Titulado Superior · (ATIDRAI_AGRO) Alianza estratégica"))
        self.assertEqual(contract["location"], "IFAPA Centro Camino de Purchil (Granada)")

    def test_otras_formas_del_codigo_y_de_la_categoria(self):
        # Como la 65470 y la 65480 del 2026-11-15.
        html = fixture("ifapa-ficha-65479.html")
        for written, code in (("CAICEM 192/2025 ", "CAICEM 192/2025"), ("(CAICEM 2025-180) ", "CAICEM 2025-180")):
            contract = ifapa.parse_ficha(html.replace("PR.FEMPA.DIP2023A.003&nbsp;", written))["contract"]
            self.assertEqual(contract["code"], code)
            self.assertTrue(contract["title"].startswith("Técnico Superior · Innovación y fomento"))
        medio = html.replace("Técnico Superior: Personal técnico", "Titulado Grado Medio. Ingeniería Técnica")
        self.assertTrue(ifapa.parse_ficha(medio)["contract"]["title"].startswith("Titulado Grado Medio · Innovación"))

    def test_dos_bloques_de_proyecto_no_se_adivinan(self):
        html = fixture("ifapa-ficha-65479.html")
        start = html.index('<ul class="list-shadow"><li>') + len('<ul class="list-shadow">')
        block = html[start:html.index("</li>", start) + 5]
        self.assertIn("Proyecto IDF", block)
        self.assertIsNone(ifapa.parse_ficha(html.replace(block, block * 2))["contract"])


class Source(unittest.TestCase):
    def test_seis_en_plazo_con_una_sola_pagina(self):
        http = Http()
        offers = ifapa.IfapaSource(now=at(11, 15)).list_offers(http)
        self.assertEqual([o.ref for o in offers], ["65480", "65479", "65478", "65469", "65470", "65471"])
        self.assertEqual(http.asked[0], ifapa.PAGE)
        self.assertEqual(len(http.asked), 1 + 6)  # la última fila ya está cerrada: no se pasa de página
        second = offers[1]
        self.assertEqual(second.title[:17], "Técnico Superior ")
        self.assertEqual((second.code, second.positions, second.opens_on, second.deadline, second.published_on),
                         ("PR.FEMPA.DIP2023A.003", 1, "2026-11-16", "2026-11-27", "2026-11-13"))
        self.assertTrue(second.source_title.startswith("Convocatoria de contratos laborales"))
        self.assertEqual((second.contract, second.kind), ("Contratos Específicos de I+D+F", None))

    def test_manda_la_fecha_y_no_el_estado(self):
        # La 65480 dice «En plazo de presentación»; el 28/11 ya ha acabado.
        self.assertEqual(ifapa.IfapaSource(now=at(11, 28)).list_offers(Http()), [])

    def test_pasa_de_pagina_mientras_la_ultima_siga_en_plazo(self):
        http = Http()
        with self.assertRaises(SourceLayoutError):
            ifapa.IfapaSource(now=at(9, 30)).list_offers(http)
        self.assertEqual(http.asked[:3], [ifapa.PAGE, ifapa.PAGE + "?page=1", ifapa.PAGE + "?page=2"])

    def test_ficha_rara_sale_con_el_titulo_del_portal_y_avisa(self):
        source = ifapa.IfapaSource(now=at(11, 15))
        http = Http(ficha=fixture("ifapa-ficha-65479.html").replace("Proyecto IDF", "Proyecto"))
        offer = source.list_offers(http)[0]
        self.assertTrue(offer.title.startswith("Convocatoria de contratos laborales"))
        self.assertIsNone(offer.source_title)
        with self.assertRaises(SourceLayoutError):
            source.fetch_detail(http, offer)

    def test_ficha_con_convocatoria_y_boja(self):
        source = ifapa.IfapaSource(now=at(11, 15))
        offer = source.list_offers(Http())[2]
        detail = source.fetch_detail(Http(), offer)
        self.assertEqual(detail.location, "IFAPA Centro Camino de Purchil (Granada)")
        self.assertEqual([s["title"] for s in detail.sections], ["La convocatoria", "Publicación oficial"])
        self.assertIn("BOJA núm 218", detail.sections[1]["html"])

    def test_enlaces_saneados(self):
        html = fixture("ifapa-ficha-65479.html").replace('href="https://juntadeandalucia.es/eboja/', 'href="javascript:alert(1)//')
        source = ifapa.IfapaSource(now=at(11, 15))
        offer = source.list_offers(Http(ficha=html))[0]
        self.assertNotIn("javascript:", " ".join(s["html"] for s in source.fetch_detail(Http(ficha=html), offer).sections))


if __name__ == "__main__":
    unittest.main()
