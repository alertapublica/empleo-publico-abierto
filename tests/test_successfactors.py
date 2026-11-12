import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import successfactors as sf

FIXTURES = Path(__file__).parent / "fixtures"
HOST = "https://empleo.example.org"
NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def page(first, last, total):
    rows = "".join(
        f'<tr class="data-row"><td class="colTitle"><a class="jobTitle-link" href="/job/x-{n}/{n}/">Oferta {n}</a></td>'
        f'<td class="colDepartment">Dept</td><td class="colFacility">Sede</td><td class="colDate">1 nov 2026</td></tr>'
        for n in range(first, last + 1)
    )
    return (f'<span class="paginationLabel">Resultados {first} – {last} de {total}</span>'
            f'<table id="searchresults">{rows}</table>')


class Listing(unittest.TestCase):
    def test_lee_las_filas_reales(self):
        rows, total = sf.parse_listing(fixture("sf-listado.html"), "https://empleo.correos.com")
        self.assertEqual(total, 3)
        self.assertEqual(len(rows), 3)
        first = rows[0]
        self.assertTrue(first["ref"].isdigit())
        self.assertTrue(first["url"].startswith("https://empleo.correos.com/job/"))
        self.assertEqual(first["department"], "Correos Express")
        self.assertEqual(first["facility"], "Sede Central")
        self.assertEqual([r["published_on"] for r in rows], ["2026-11-07", "2026-11-02", "2026-10-30"])

    def test_listado_en_catalan(self):
        # BSM: «Resultats 1 – 19 de 19» y fechas «11 de nov. 2026», «14 d’oct. 2026».
        rows, total = sf.parse_listing(fixture("bsm-vacants.html"), "https://creix.bsmsa.cat")
        self.assertEqual((total, len(rows)), (19, 3))
        self.assertEqual([r["published_on"] for r in rows], ["2026-11-11", "2026-11-10", "2026-11-09"])
        self.assertEqual(sf._list_date("14 d’oct. 2026"), "2026-10-14")
        self.assertEqual(sf._list_date("3 de febr. 2027"), "2027-02-03")

    def test_localidad_fija_si_el_microdato_no_sirve(self):
        source = sf.SuccessFactorsSource(id="x", name="X", host=HOST, company="X", categories=[], location="Barcelona")

        class Http:
            def get(self, url):
                return fixture("sf-ficha.html")

        offer = sf.ListedOffer(ref="1", title="T", company="X", url=HOST + "/job/x/1/", apply_url="")
        self.assertEqual(source.fetch_detail(Http(), offer).location, "Barcelona")

    def test_categoria_sin_vacantes_es_lista_vacia(self):
        self.assertEqual(sf.parse_listing(fixture("sf-vacio.html"), HOST), ([], 0))

    def test_categoria_sin_vacantes_en_catalan_es_lista_vacia(self):
        self.assertEqual(sf.parse_listing(fixture("sf-vacio-ca.html"), HOST), ([], 0))

    def test_aviso_sin_resultados_vacio_no_pasa_por_lista_vacia(self):
        # Una tabla que cambia de id junto a un aviso sin el «0» de «las 0 últimas ofertas»
        html = fixture("sf-listado.html").replace('id="searchresults"', 'id="otra"')
        with self.assertRaises(SourceLayoutError):
            sf.parse_listing(html + '<div id="noresults" hidden></div>', HOST)
        with self.assertRaises(SourceLayoutError):
            sf.parse_listing(html + '<div id="noresults"><div id="noresults-message"></div></div>', HOST)

    def test_aviso_de_vacia_junto_a_una_tabla_no_se_interpreta(self):
        aviso = '<div id="noresults"><div id="noresults-message">las 3 últimas ofertas</div></div>'
        with self.assertRaises(SourceLayoutError):
            sf.parse_listing(aviso + fixture("sf-listado.html"), HOST)

    def test_pagina_inesperada_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            sf.parse_listing("<h1>Mantenimiento</h1>", HOST)

    def test_fila_sin_enlace_a_oferta_no_se_interpreta(self):
        html = fixture("sf-listado.html").replace("/job/", "/otra/")
        with self.assertRaises(SourceLayoutError):
            sf.parse_listing(html, HOST)


class Detail(unittest.TestCase):
    def test_ficha_real(self):
        detail = sf.parse_detail(fixture("sf-ficha.html"))
        self.assertEqual(detail.location, "Madrid")
        self.assertEqual(detail.deadline, "2026-11-13")  # el texto oficial dice «hasta el 13 de noviembre»
        (section,) = detail.sections
        self.assertEqual(section["title"], "Descripción de la oferta")
        self.assertIn("Jóvenes Talentos", section["html"])
        self.assertNotIn("style=", section["html"])

    def test_pagina_sin_oferta_devuelve_none(self):
        self.assertIsNone(sf.parse_detail("<p>La oferta ya no está disponible.</p>"))

    def test_fecha_de_cierre_en_horario_de_verano_e_invierno(self):
        self.assertEqual(sf._closing_date("Fri Nov 13 23:00:00 UTC 2026"), "2026-11-13")
        self.assertEqual(sf._closing_date("Fri Aug 14 22:00:00 UTC 2026"), "2026-08-14")
        self.assertEqual(sf._closing_date("Fri Nov 13 12:00:00 UTC 2026"), "2026-11-13")
        self.assertIsNone(sf._closing_date("mañana"))


class Pagination(unittest.TestCase):
    class Http:
        def __init__(self, pages):
            self.pages, self.asked = pages, []

        def get(self, url):
            self.asked.append(url)
            return self.pages[url]

    def source(self):
        return sf.SuccessFactorsSource("x", "X", HOST, "X", [(None, "/go/a/1/")])

    def test_recorre_todas_las_paginas(self):
        base = f"{HOST}/go/a/1/"
        http = self.Http({base: page(1, 2, 3), base + "2/": page(3, 3, 3)})
        offers = self.source().list_offers(http)
        self.assertEqual([o.ref for o in offers], ["1", "2", "3"])
        self.assertEqual(http.asked, [base, base + "2/"])

    def test_si_faltan_resultados_se_detiene_en_vez_de_cerrar_ofertas(self):
        base = f"{HOST}/go/a/1/"
        http = self.Http({base: page(1, 2, 5), base + "2/": page(1, 2, 5)})
        with self.assertRaises(SourceLayoutError):
            self.source().list_offers(http)


class FakeHttp:
    def get(self, url):
        return fixture("sf-ficha.html") if "/job/" in url else fixture("sf-listado.html")


class EndToEnd(unittest.TestCase):
    def run_once(self, source, offers):
        events = ingest.reconcile(offers, source.list_offers(FakeHttp()), source.id, NOW)
        ingest.fetch_details(source, FakeHttp(), offers, events)
        ingest.apply_enrichment(source, FakeHttp(), offers)
        return events

    def test_ingesta_completa_con_plazo_de_la_ficha(self):
        source = sf.SuccessFactorsSource(
            "correos", "Grupo Correos", "https://empleo.correos.com", "Correos",
            [("practicas", "/go/Ofertas-publicadas/4331401/")],
        )
        offers = {}
        events = self.run_once(source, offers)
        self.assertEqual(len(offers), 3)
        self.assertTrue(all(e["kind"] == "new" for e in events))
        record = next(iter(offers.values()))
        self.assertEqual(record["deadline"], "2026-11-13")
        self.assertEqual(record["location"], "Madrid")
        self.assertEqual(record["region"], "Comunidad de Madrid")
        self.assertEqual(record["kind"], "practicas")
        self.assertEqual(record["department"], "Correos Express · Sede Central")
        self.assertEqual(record["company"], "Correos")
        self.assertRegex(record["apply_url"], r"/talentcommunity/apply/\d+/\?locale=es_ES$")
        self.assertTrue(record["published_on"])
        # Segunda ejecución: el listado no trae plazo y no debe parecer que cambia.
        again = self.run_once(source, offers)
        self.assertEqual(again, [])
        self.assertEqual(record["deadline"], "2026-11-13")
