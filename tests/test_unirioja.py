import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import unirioja

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def at(year, month, day, hour=10):
    return datetime(year, month, day, hour, 0, tzinfo=timezone.utc)


class Http:
    """Las dos páginas del 2026-11-16, recortadas a sus bloques: 13 de proyectos y 5 de talento."""

    def __init__(self, proyectos=None, talento=None):
        self.asked = []
        self.pages = {unirioja.PROYECTOS: proyectos or fixture("unirioja-proyectos.html"),
                      unirioja.TALENTO: talento or fixture("unirioja-talento.html")}

    def get(self, url):
        self.asked.append(url)
        return self.pages[url]


class Blocks(unittest.TestCase):
    def test_plazos_y_publicacion_de_todos_los_bloques(self):
        blocks = unirioja.parse_blocks(fixture("unirioja-proyectos.html"))
        self.assertEqual(len(blocks), 13)
        self.assertEqual([(b["opens_on"], b["deadline"], b["published_on"]) for b in blocks[:1] + blocks[4:5]], [
            ("2026-11-11", "2026-11-25", "2026-11-10"),  # «del 11 de noviembre al 25 de noviembre de 2026»
            ("2026-06-09", "2026-06-23", "2026-06-08"),  # «del 9 al 23 de junio de 2026»
        ])
        self.assertEqual((blocks[-1]["opens_on"], blocks[-1]["deadline"]), ("2025-11-14", "2025-11-28"))  # sin «de»
        self.assertIsNone(blocks[5]["published_on"])  # «Convocatoria BOR» sin fecha
        talento = unirioja.parse_blocks(fixture("unirioja-talento.html"))
        self.assertEqual(len(talento), 5)
        # «desde el 12 de septiembre hasta el 13 de octubre de 2026»; las bases (BOR de 2025) van antes
        self.assertEqual((talento[0]["opens_on"], talento[0]["deadline"], talento[0]["published_on"]),
                         ("2026-09-12", "2026-10-13", "2026-09-11"))

    def test_bloque_informativo_se_salta(self):
        notices = ("<div class='bloque-texto'><p>Convocatoria pendiente de publicación</p></div>"
                   "<div class='bloque-texto'><p>Información sobre la presentación electrónica de solicitudes</p></div>")
        html = fixture("unirioja-proyectos.html").replace("<main>", "<main>" + notices)
        self.assertEqual(len(unirioja.parse_blocks(html)), 13)
        offers = unirioja.UniriojaSource(now=at(2026, 11, 16)).list_offers(Http(proyectos=html))
        self.assertEqual([o.ref for o in offers], ["08-01-id26"])

    def test_plazo_que_cruza_el_año(self):
        html = "<div class='bloque-texto'><p>Plazo presentación de solicitudes: del 20 de diciembre al 3 de enero de 2027</p></div>"
        block = unirioja.parse_blocks(html)[0]
        self.assertEqual((block["opens_on"], block["deadline"]), ("2026-12-20", "2027-01-03"))

    def test_sin_bloques_sin_plazo_o_con_dos_detiene(self):
        with self.assertRaises(SourceLayoutError):
            unirioja.parse_blocks("<main><p>Nada</p></main>")
        with self.assertRaises(SourceLayoutError):
            unirioja.parse_blocks("<div class='bloque-texto'><p>TÉCNICO/A: se convoca el proceso selectivo…</p></div>")
        two = ("<div class='bloque-texto'><p>Plazo presentación de solicitudes: del 1 al 5 de junio de 2026</p>"
               "<p>Plazo presentación de solicitudes: del 8 al 12 de junio de 2026</p></div>")
        with self.assertRaises(SourceLayoutError):
            unirioja.parse_blocks(two)


class Source(unittest.TestCase):
    def test_en_plazo_el_16_de_noviembre(self):
        http = Http()
        offers = unirioja.UniriojaSource(now=at(2026, 11, 16)).list_offers(http)
        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual((offer.ref, offer.code, offer.company, offer.url, offer.kind),
                         ("08-01-id26", "08-01-ID26", "Universidad de La Rioja", unirioja.PROYECTOS, None))
        self.assertEqual(offer.title, "Técnica/o · Percepción de la igualdad de género en el alumnado universitario: "
                                      "implicaciones para el diseño de políticas educativas y estrategias coeducativas")
        self.assertEqual((offer.opens_on, offer.deadline, offer.published_on), ("2026-11-11", "2026-11-25", "2026-11-10"))
        self.assertEqual(http.asked, [unirioja.PROYECTOS, unirioja.TALENTO])

    def test_proyectos_y_talento(self):
        # El 20/09: tres de proyectos (una con «+» en la referencia) y la de talento de Computación Científica.
        offers = unirioja.UniriojaSource(now=at(2026, 9, 20)).list_offers(Http())
        self.assertEqual([(o.ref, o.code) for o in offers], [
            ("08-01-id26", "08-01-ID26"), ("testacos", "TESTACOS+"), ("shield4grape", "SHIELD4GRAPE"),
            ("talento-1374-2026", None)])
        self.assertEqual(offers[1].title.split(" · ")[0], "Técnico/a")
        self.assertEqual(offers[3].title, "Contrato de investigación para la captación de talento · Computación Científica")
        self.assertEqual(offers[3].url, unirioja.TALENTO)

    def test_detalle_con_el_bloque_entero(self):
        source = unirioja.UniriojaSource(now=at(2026, 11, 16))
        offer = source.list_offers(Http())[0]
        detail = source.fetch_detail(Http(), offer)
        self.assertEqual(detail.location, "Logroño")
        self.assertEqual([s["title"] for s in detail.sections], ["La convocatoria"])
        self.assertIn("Investigadora: Iratxe Suberviola Ovejas.", detail.sections[0]["html"])
        self.assertIn("unirioja.sharepoint.com", detail.sections[0]["html"])

    def test_detalle_sin_cache_busca_el_bloque_aunque_haya_cerrado(self):
        offer = unirioja.UniriojaSource(now=at(2026, 9, 20)).list_offers(Http())[1]  # TESTACOS+, cerrada el 13/11
        detail = unirioja.UniriojaSource(now=at(2026, 11, 16)).fetch_detail(Http(), offer)
        self.assertIn("TESTACOS+", detail.sections[0]["html"])

    def test_formato_antiguo_en_plazo_detiene(self):
        # «Resolución 1903/2025… de un técnico…»: sin categoría delante de los dos puntos.
        with self.assertRaises(SourceLayoutError):
            unirioja.UniriojaSource(now=at(2025, 12, 10)).list_offers(Http())

    def test_misma_referencia_en_plazo_detiene(self):
        proyectos = fixture("unirioja-proyectos.html").replace("Proyecto de referencia TESTACOS+", "Proyecto 08-01-ID26")
        with self.assertRaises(SourceLayoutError):
            unirioja.UniriojaSource(now=at(2026, 11, 1)).list_offers(Http(proyectos=proyectos))


if __name__ == "__main__":
    unittest.main()
