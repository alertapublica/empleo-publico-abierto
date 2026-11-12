import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import fundanet

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def __init__(self, listing, ficha=None):
        self.listing, self.ficha, self.urls = listing, ficha, []

    def get(self, url):
        self.urls.append(url)
        return fixture(self.ficha if "VerConvocatoria" in url else self.listing)


def source(template, now=NOW):
    return fundanet.FundanetSource(id=template.id, name=template.name, listing=template.listing,
                                   scope=template.scope, bases_contract=template.bases_contract,
                                   text_lang=template.text_lang, now=now)


class Listado(unittest.TestCase):
    def test_columnas_y_fechas_con_hora(self):
        rows = fundanet.parse_listing(fixture("fundanet-idibell-listado.html"), "IDIBELL")
        self.assertEqual(len(rows), 5)
        self.assertEqual(rows[0], {
            "ref": "2320", "title": "26-159_SS_FF Biostatistician - Psychoneurobiology of Eating and Addictive Behaviours",
            "href": "/convocatoriaspropias/es/Convocatorias/VerConvocatoria/2320",
            "opens_on": "2026-11-06", "deadline": "2026-11-20", "deadline_time": "23:59",
        })

    def test_solo_las_que_no_han_vencido_y_sin_mirar_el_estado(self):
        offers = source(fundanet.IDIBELL).list_offers(FakeHttp("fundanet-idibell-listado.html"))
        self.assertEqual([o.ref for o in offers], ["2320", "2318"])
        first = offers[0]
        self.assertEqual(first.url, "https://idibell.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/VerConvocatoria/2320")
        self.assertEqual((first.apply_url, first.kind, first.company), (first.url, None, "IDIBELL"))
        self.assertEqual((first.opens_on, first.deadline, first.deadline_time), ("2026-11-06", "2026-11-20", "23:59"))

    def test_fisabio_sin_columna_de_estado(self):
        offers = source(fundanet.FISABIO).list_offers(FakeHttp("fundanet-fisabio-listado.html"))
        self.assertEqual([o.ref for o in offers], ["881", "880"])

    def test_imas12_titulo_literal(self):
        offers = source(fundanet.IMAS12).list_offers(FakeHttp("fundanet-imas12-listado.html"))
        self.assertEqual([(o.ref, o.title) for o in offers], [
            ("41", "ENFERMERO/A ENSAYOS CLÍNICOS( REF.2611/16)- Dr.Arribas"),
            ("40", "PERSONAL INVESTIGADOR( REF. 2611/14). DR. Rojo"),
            ("26", "GESTOR/A DE DATOS ( REF:2611/15 ) - Dra. Álvarez Conejo")])
        self.assertEqual((offers[2].opens_on, offers[2].deadline, offers[2].deadline_time),
                         ("2026-11-04", "2026-11-12", "23:59"))
        self.assertEqual(fundanet.IMAS12.labels(offers[1].title, "40")["title"], offers[1].title)

    def test_cierra_a_la_hora_del_listado(self):
        html = fixture("fundanet-idival-listado.html").replace("11/11/2026 23:59", "11/11/2026 12:24")
        http = FakeHttp("fundanet-idival-listado.html")
        http.get = lambda url: html
        # 11:30 UTC son las 12:30 en Madrid.
        late = source(fundanet.IDIVAL, datetime(2026, 11, 11, 11, 30, tzinfo=timezone.utc)).list_offers(http)
        self.assertEqual(late, [])
        early = source(fundanet.IDIVAL, datetime(2026, 11, 11, 11, 0, tzinfo=timezone.utc)).list_offers(http)
        self.assertEqual([(o.ref, o.deadline_time) for o in early], [("1498", "12:24")])

    def test_hora_de_una_cifra(self):
        html = fixture("fundanet-idival-listado.html").replace("11/11/2026 23:59", "11/11/2026 0:00")
        self.assertEqual(fundanet.parse_listing(html, "IDIVAL")[0]["deadline_time"], "00:00")

    def test_sin_tabla_o_con_otras_columnas_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fundanet.parse_listing("<h1>Mantenimiento</h1>", "IDIBELL")
        html = fixture("fundanet-idibell-listado.html").replace("F.Fin Presentación", "Fecha de fin")
        with self.assertRaises(SourceLayoutError):
            fundanet.parse_listing(html, "IDIBELL")

    def test_fecha_ilegible_se_detiene(self):
        html = fixture("fundanet-idibell-listado.html").replace("20/11/2026 23:59", "pronto", 1)
        with self.assertRaises(SourceLayoutError):
            fundanet.parse_listing(html, "IDIBELL")


class Ficha(unittest.TestCase):
    def detail(self, template, ficha, listing):
        src = source(template)
        http = FakeHttp(listing, ficha)
        (offer, *_) = src.list_offers(http)
        return src, http, offer

    def test_idibell_contrato_literal_de_la_ficha(self):
        src, http, offer = self.detail(fundanet.IDIBELL, "fundanet-idibell-ficha.html", "fundanet-idibell-listado.html")
        detail = src.fetch_detail(http, offer)
        self.assertEqual(detail.contract, "Permanent by project")
        self.assertEqual(detail.location, "Cataluña")
        self.assertEqual([s["title"] for s in detail.sections], ["Convocatoria", "Documentos de la convocatoria"])
        self.assertIn("Biostatistician", detail.sections[0]["html"])
        self.assertIn("DescargarDocumentoBases/2320", detail.sections[1]["html"])
        # Redacta en inglés: se marca su texto, no los documentos (el enlace lo escribimos nosotros)
        self.assertEqual([s.get("lang") for s in detail.sections], ["en", None])
        self.assertEqual(src.detail_version, 2)

    def test_fisabio_contrato_de_las_bases(self):
        src, http, offer = self.detail(fundanet.FISABIO, "fundanet-fisabio-ficha.html", "fundanet-fisabio-listado.html")
        read = mock.Mock(return_value=fixture("fundanet-fisabio-bases-881.txt"))
        with mock.patch.object(fundanet, "read_pdf", read):
            detail = src.fetch_detail(http, offer)
        self.assertEqual(detail.contract, "contrato indefinido")
        self.assertEqual(read.call_args.args[1],
                         "https://fisabio.fundanetsuite.com/convocatoriaspropias/es/Convocatorias/DescargarDocumentoBases/881")
        self.assertEqual(detail.location, "Comunitat Valenciana")

    def test_imas12_contrato_de_las_bases(self):
        src, http, offer = self.detail(fundanet.IMAS12, "fundanet-imas12-ficha.html", "fundanet-imas12-listado.html")
        read = mock.Mock(return_value=fixture("fundanet-imas12-bases-41.txt"))
        with mock.patch.object(fundanet, "read_pdf", read):
            detail = src.fetch_detail(http, offer)
        self.assertEqual(detail.contract, "Indefinido Art.23 Bis de la Ley 14/2011")
        self.assertEqual(detail.location, "Comunidad de Madrid")
        self.assertIn("I.P _ DR. ARRIBAS", detail.sections[0]["html"])
        self.assertIn("DescargarDocumentoBases/41", detail.sections[1]["html"])
        # Otra convocatoria con la viñeta de Symbol y el artículo entre paréntesis
        read.return_value = "CONDICIONES DE CONTRATO: \uf0b7 Plazas: 1 \uf0b7 Contrato: Indefinido (Art.23 bis de ley 14/2011) \uf0b7 Jornada"
        with mock.patch.object(fundanet, "read_pdf", read):
            self.assertEqual(src.fetch_detail(http, offer).contract, "Indefinido (Art.23 bis de ley 14/2011)")

    def test_idival_sin_contrato_y_sin_enlazar_listas_de_personas(self):
        src, http, offer = self.detail(fundanet.IDIVAL, "fundanet-idival-ficha.html", "fundanet-idival-listado.html")
        with mock.patch.object(fundanet, "read_pdf") as read:
            detail = src.fetch_detail(http, offer)
        read.assert_not_called()
        self.assertIsNone(detail.contract)
        self.assertNotIn("lang", detail.sections[0])  # en castellano, como la página
        self.assertEqual(src.detail_version, 1)
        documents = detail.sections[1]["html"]
        self.assertIn("DescargarDocumentoBases/1498", documents)
        self.assertNotIn("dmtidos", documents)
        self.assertNotIn("IdDocumento", documents)
        self.assertIn("admtidos", fixture("fundanet-idival-ficha.html").lower())  # el enlace existe en la ficha

    def test_ficha_sin_texto_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fundanet.parse_detail("<h1>Error</h1>", fundanet.IDIBELL.listing)


if __name__ == "__main__":
    unittest.main()
