import unittest
from datetime import date, datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import ibsal, idisna

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        return self.pages[url] if url in self.pages else self.pages["*"]


class Idisna(unittest.TestCase):
    def test_lee_rotulos_del_texto(self):
        entries = {e["ref"]: e for e in idisna.parse_feed(fixture("idisna-rss.xml"))}
        first = entries["7749"]
        self.assertEqual((first["title"], first["url"]),
                         ("Ref. 26-33 Personal de apoyo a la investigación - Copia",
                          "https://www.idisna.es/portal/seccion.aspx?N=7749"))
        self.assertEqual((first["published_on"], first["deadline"], first["deadline_time"]),
                         ("2026-10-23", "2026-11-06", "12:00"))
        self.assertEqual(first["contract"], "Actividades científico-técnicas")
        self.assertEqual(entries["7746"]["contract"], "Contrato de duración determinada vinculado a programas "
                         "financiados con Fondos Europeos (Fondos Next Generation EU/PRTR)")
        self.assertEqual(entries["7737"]["contract"], "Indefinido")

    def test_abierta_hasta_la_hora_de_cierre(self):
        http = Http({"*": fixture("idisna-rss.xml")})
        # 10:30 UTC son las 11:30 en Madrid: la 26-33 sigue abierta; a las 11:00 UTC, ya no.
        before = idisna.IdisnaSource(datetime(2026, 11, 6, 10, 30, tzinfo=timezone.utc)).list_offers(http)
        self.assertEqual([o.ref for o in before], ["7749"])
        self.assertEqual((before[0].deadline_time, before[0].kind, before[0].contract),
                         ("12:00", None, "Actividades científico-técnicas"))
        after = idisna.IdisnaSource(datetime(2026, 11, 6, 11, 0, tzinfo=timezone.utc)).list_offers(http)
        self.assertEqual(after, [])

    def test_ficha_con_el_texto_del_rss(self):
        source = idisna.IdisnaSource(datetime(2026, 11, 1, tzinfo=timezone.utc))
        http = Http({"*": fixture("idisna-rss.xml")})
        (offer,) = source.list_offers(http)
        detail = source.fetch_detail(http, offer)
        self.assertEqual(detail.location, "Navarra")
        self.assertIn("Ref. 26-33", detail.sections[0]["html"])
        self.assertEqual(len(http.urls), 1)  # sin pedir fichas

    def test_sin_fecha_de_cierre_se_detiene(self):
        xml = fixture("idisna-rss.xml").replace("Fecha de cierre", "Cierre", 1)
        with self.assertRaises(SourceLayoutError):
            idisna.parse_feed(xml)

    def test_rss_roto_o_vacio_se_detiene(self):
        for xml in ("<html>", "<rss><channel></channel></rss>"):
            with self.assertRaises(SourceLayoutError):
                idisna.parse_feed(xml)


class Ibsal(unittest.TestCase):
    def test_sin_convocatorias_vigentes(self):
        self.assertEqual(ibsal.parse_listing(fixture("ibsal-vigentes-vacio.html")), [])

    def test_ficha_con_caducidad_y_contrato_literal(self):
        job = ibsal.parse_detail(fixture("ibsal-ficha.html"))
        self.assertEqual((job["ref"], job["deadline"]), ("28071", "2026-10-22"))
        self.assertEqual(job["title"], "Ref.44_2026. Técnico FP Superior en Investigación.")
        self.assertEqual(job["contract"], "Contrato Indefinido: actividades científicas- técnicas "
                                          "(art 23. Bis de la ley 14/2011 LCTI)")

    def test_meses_abreviados_en_ingles_o_en_espanol(self):
        self.assertEqual(ibsal.expiry_date("22 Oct 2026"), date(2026, 10, 22))
        self.assertEqual(ibsal.expiry_date("5 Dec 2026"), date(2026, 12, 5))
        self.assertEqual(ibsal.expiry_date("5 dic. 2026"), date(2026, 12, 5))
        self.assertEqual(ibsal.expiry_date("3 ene 2027"), date(2027, 1, 3))
        self.assertIsNone(ibsal.expiry_date("pronto"))

    def test_vigente_hasta_el_ultimo_dia(self):
        # Tarjeta construida: el 2026-11-08 no había ninguna vigente con la que probar.
        listing = ('<div class="awsm-job-listings"><div class="awsm-job-listing-item">'
                   '<a href="https://ibsal.es/?post_type=awsm_job_openings&amp;p=28071">Ref.44_2026</a></div></div>')
        http = Http({ibsal.PAGE: listing, "*": fixture("ibsal-ficha.html")})
        last_day = ibsal.IbsalSource(datetime(2026, 10, 22, 21, 0, tzinfo=timezone.utc)).list_offers(http)
        self.assertEqual([(o.ref, o.deadline, o.company) for o in last_day], [("28071", "2026-10-22", "FIBSAL")])
        self.assertEqual(ibsal.IbsalSource(datetime(2026, 10, 22, 23, 0, tzinfo=timezone.utc)).list_offers(http), [])

    def test_listado_cambiado_se_detiene(self):
        for html in ("<h1>Mantenimiento</h1>", '<div class="awsm-job-listings"><p>Algo</p></div>'):
            with self.assertRaises(SourceLayoutError):
                ibsal.parse_listing(html)

    def test_ficha_sin_caducidad_se_detiene(self):
        html = fixture("ibsal-ficha.html").replace("awsm-job-expiration-content", "otra")
        with self.assertRaises(SourceLayoutError):
            ibsal.parse_detail(html)


if __name__ == "__main__":
    unittest.main()
