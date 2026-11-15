import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import udc

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


def old_page():
    """La página 2 real con los anuncios llevados a octubre y sin página siguiente: fin del recorrido."""
    html = fixture("udc-taboleiro-p2.html").replace('<span class="month">nov</span>', '<span class="month">out</span>')
    return html.replace("category/7?page=3", "category/7?page=x")


class Http:
    """Las dos primeras páginas reales de «Anuncios institucionais» del 2026-11-15 (gallego, como las lee el portal)
    y las fichas reales de 2026/CP/263 (10/11) y 2026/CP/259 (06/11). Las de 262, 261 y 260, del mismo día que la
    263, salen con la suya; cualquier otra, con la de la 259."""

    FICHAS = {"/011907": "udc-ficha-cp263.html", "/011906": "udc-ficha-cp263.html", "/011905": "udc-ficha-cp263.html",
              "/011904": "udc-ficha-cp263.html"}

    def __init__(self):
        self.asked = []

    def get(self, url):
        self.asked.append(url)
        if url == udc.INDEX:
            return fixture("udc-taboleiro.html")
        if url == udc.INDEX + "?page=2":
            return fixture("udc-taboleiro-p2.html")
        if url == udc.INDEX + "?page=3":
            return old_page()
        return fixture(next((name for end, name in self.FICHAS.items() if url.endswith(end)), "udc-ficha-cp259.html"))


class Calendar(unittest.TestCase):
    def test_cinco_habiles(self):
        self.assertEqual(udc.business_deadline(date(2026, 11, 10)), date(2026, 11, 17))  # sin festivos
        self.assertEqual(udc.business_deadline(date(2026, 11, 6)), date(2026, 11, 13))  # viernes: empieza el lunes
        # El Rosario (07/10, local de A Coruña) y el Pilar (12/10) no cuentan.
        self.assertEqual(udc.business_deadline(date(2026, 10, 5)), date(2026, 10, 14))

    def test_dias_dudosos_cuentan_como_habiles(self):
        # 24 y 31/12 (oficinas cerradas): hábiles; 25/12 festivo.
        self.assertEqual(udc.business_deadline(date(2026, 12, 21), 4), date(2026, 12, 28))

    def test_ano_sin_calendario_detiene(self):
        with self.assertRaises(SourceLayoutError):
            udc.business_deadline(date(2026, 12, 28))


class Board(unittest.TestCase):
    def test_anuncios_con_ano(self):
        rows = udc.parse_board(fixture("udc-taboleiro-p2.html"), date(2026, 11, 15))
        self.assertEqual(len(rows), 15)
        self.assertEqual(rows[0], {"date": date(2026, 11, 10), "title": "Conv. contrat. 2026/CP/263. Facultade de Dereito",
                                   "url": "https://sede.udc.gal/services/electronic_board/EXP2026/011907"})

    def test_mes_en_el_futuro_es_del_ano_anterior(self):
        rows = udc.parse_board(fixture("udc-taboleiro-p2.html"), date(2027, 1, 3))
        self.assertEqual(rows[0]["date"], date(2026, 11, 10))

    def test_paginas(self):
        self.assertEqual(udc.next_page(fixture("udc-taboleiro.html"), 1), udc.INDEX + "?page=2")
        self.assertIsNone(udc.next_page(old_page(), 2))


class Ficha(unittest.TestCase):
    def test_categoria_y_pdf(self):
        ficha = udc.parse_ficha(fixture("udc-ficha-cp263.html"))
        self.assertEqual((ficha["published_on"], ficha["heading"], ficha["category"]),
                         ("2026-11-10", "Conv. contrat. 2026/CP/263. Facultade de Dereito",
                          "Colaborador de investigación a tempo completo"))
        self.assertIn("documentCsv=", ficha["pdf"])
        self.assertEqual([label for label, _ in ficha["documents"]], ["Anuncio GL [pdf]", "Anuncio ES [pdf]"])
        self.assertTrue(ficha["pdf"] == ficha["documents"][1][1])  # el castellano

    def test_categoria_tras_coma(self):
        ficha = udc.parse_ficha(fixture("udc-ficha-cp259.html"))
        self.assertEqual(ficha["category"], "Técnico de Apoio á Investigación a tempo completo")

    def test_pdf_de_las_dos_plantillas(self):
        self.assertEqual(udc.parse_pdf(fixture("udc-anuncio-cp263.txt")), {
            "days": 5, "rule": udc.RULE,
            "project": "ENACT- Regulatory Attenuation: local non application-erodes EU environmental objectives"})
        latex = udc.parse_pdf(fixture("udc-anuncio-cp249-latex.txt"))  # «d ´ ıas h´ abiles»
        self.assertEqual((latex["days"], latex["project"]), (5, "Grupos de referencia competitiva (GRC)"))
        self.assertIn("5 días hábiles a partir del día siguiente", latex["rule"])

    def test_pdf_sin_regla(self):
        self.assertIsNone(udc.parse_pdf("PLAZO: el que diga el BOE")["days"])


class Source(unittest.TestCase):
    def test_abiertas_el_15_11(self):
        http = Http()
        offers = udc.UdcSource(now=at(11, 15)).list_offers(http)
        # 263, 262, 261 y 260 (10/11, hasta el 17/11). Las del 05 y 06/11 vencieron el 12 y el 13: ni se abren.
        self.assertEqual([(o.code, o.deadline) for o in offers],
                         [(f"2026/CP/{n}", "2026-11-17") for n in (263, 262, 261, 260)])
        first = offers[0]
        self.assertEqual((first.ref, first.title, first.source_title, first.published_on, first.deadline_rule),
                         ("2026-cp-263", "Colaborador de investigación a tempo completo · Facultade de Dereito",
                          "Conv. contrat. 2026/CP/263. Facultade de Dereito", "2026-11-10", udc.RULE))
        self.assertEqual(http.asked[:3], [udc.INDEX, udc.INDEX + "?page=2", udc.INDEX + "?page=3"])
        self.assertEqual(len(http.asked), 7)  # tres páginas y cuatro fichas

    def test_resoluciones_listas_y_correcciones_no_son_ofertas(self):
        offers = udc.UdcSource(now=at(11, 11)).list_offers(Http())
        self.assertNotIn("2026/CP/253", [o.code for o in offers])  # solo «Lista Definitiva» en el tablón
        self.assertIn("2026/CP/259", [o.code for o in offers])  # 06/11: hasta el 13/11

    def test_ficha_lee_el_pdf_y_marca_el_calculo(self):
        source = udc.UdcSource(now=at(11, 15))
        http = Http()
        offer = source.list_offers(http)[0]
        with mock.patch.object(udc, "read_pdf", return_value=fixture("udc-anuncio-cp263.txt")) as read:
            detail = source.fetch_detail(http, offer)
        self.assertIn("documentCsv=", read.call_args.args[1])
        self.assertEqual((detail.deadline, detail.deadline_rule), ("2026-11-17", udc.RULE))
        self.assertEqual([s["title"] for s in detail.sections], ["Proyecto", "Plazo de presentación", "Documentos"])

    def test_otro_numero_de_dias_corrige_el_plazo(self):
        source = udc.UdcSource(now=at(11, 15))
        http = Http()
        offer = source.list_offers(http)[0]
        text = fixture("udc-anuncio-cp263.txt").replace("PLAZO: 5 días", "PLAZO: 10 días")
        with mock.patch.object(udc, "read_pdf", return_value=text):
            detail = source.fetch_detail(http, offer)
        self.assertEqual(detail.deadline, "2026-11-24")
        self.assertTrue(detail.deadline_rule.startswith("10 días hábiles"))

    def test_pdf_sin_regla_avisa(self):
        source = udc.UdcSource(now=at(11, 15))
        http = Http()
        offer = source.list_offers(http)[0]
        with mock.patch.object(udc, "read_pdf", return_value="Nada"), self.assertRaises(SourceLayoutError):
            source.fetch_detail(http, offer)

    def test_demasiadas_paginas_detiene(self):
        class Endless(Http):
            def get(self, url):
                self.asked.append(url)
                return fixture("udc-taboleiro.html").replace("category/7?page=", "category/7?page=")
        with mock.patch.object(udc, "next_page", side_effect=lambda html, page: udc.INDEX + f"?page={page + 1}"), \
                self.assertRaises(SourceLayoutError):
            udc.UdcSource(now=at(11, 15)).list_offers(Endless())


if __name__ == "__main__":
    unittest.main()
