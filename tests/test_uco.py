import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import uco

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "uco-pit.html").read_text(encoding="utf-8")


def at(year, month, day, hour=10):
    return datetime(year, month, day, hour, 0, tzinfo=timezone.utc)


def article(body, ref="999", title="12ª CONVOCATORIA DE CONTRATOS DE PERSONAL INVESTIGADOR Y TÉCNICO (PIT) 2026"):
    return (f'<div itemprop="blogPost"><div class="page-header"><h2 itemprop="name"><a itemprop="url" '
            f'href="/investigacion/portal/convocatorias-de-contratos/{ref}-12-convocatoria">{title}</a></h2></div>'
            f'{body}</div>')


class Http:
    """La primera página del listado del 2026-11-16, recortada a sus 20 artículos y la paginación."""

    def __init__(self, page=PAGE):
        self.asked, self.page = [], page

    def get(self, url):
        self.asked.append(url)
        assert url == uco.INDEX, url
        return self.page


class List(unittest.TestCase):
    def test_plazos_y_publicacion_de_todos_los_articulos(self):
        rows = uco.parse_list(PAGE)
        self.assertEqual(len(rows), 20)
        by_ref = {r["ref"]: (r["published_on"], r["opens_on"], r["deadline"]) for r in rows}
        self.assertEqual(by_ref["711"], ("2026-10-30", "2026-11-03", "2026-11-09"))  # «desde el 03 de noviembre al 09 de noviembre»
        # 6.ª: «Corrección de errores plazo de presentación de solicitudes» no es otro plazo
        self.assertEqual(by_ref["696"], ("2026-05-26", "2026-06-02", "2026-06-09"))
        # 10.ª: el «Plazo de subsanación» del listado provisional tampoco
        self.assertEqual(by_ref["709"], ("2026-10-20", "2026-10-21", "2026-10-28"))
        # 3.ª: sin fecha delante, la de la resolución; «desde el 21 al 27 de febrero»
        self.assertEqual(by_ref["686"], ("2026-02-20", "2026-02-21", "2026-02-27"))
        self.assertEqual(by_ref["668"][1:], ("2025-05-27", "2025-06-02"))  # «desde el 27 de mayo hasta el 2 de junio»

    def test_titulo_sin_mayusculas_sostenidas_y_pit(self):
        rows = {r["ref"]: r["title"] for r in uco.parse_list(PAGE)}
        self.assertEqual(rows["711"], "11ª convocatoria de contratos de personal investigador y técnico (PIT) 2026")
        self.assertEqual(rows["702"], "8ª Convocatoria de Contratos de Personal Investigador y Técnico (PIT) 2026")
        self.assertEqual(rows["670"], "7ª convocatoria de contratos PIT (personal investigador y técnico) 2025")

    def test_ficha_es_el_articulo_con_enlaces_absolutos_y_sin_titulo(self):
        html = uco.parse_list(PAGE)[0]["html"]
        self.assertIn('href="https://www.uco.es/investigacion/portal/images/00_11ª_Convocatoria_de_Contratos.pdf_firmada.pdf"', html)
        self.assertIn("NOTAS IMPORTANTES", html)
        self.assertNotIn("<h2", html)

    def test_articulo_sin_plazo_o_con_dos_detiene(self):
        with self.assertRaisesRegex(SourceLayoutError, "solo uno"):
            uco.parse_list(article("<p>Resolución de 1 de diciembre de 2026</p>"))
        two = ("<p>Plazo de presentación de solicitudes: desde el 1 al 7 de diciembre de 2026</p>"
               "<p>Plazo de presentación de solicitudes: desde el 2 al 9 de diciembre de 2026</p>")
        with self.assertRaisesRegex(SourceLayoutError, "solo uno"):
            uco.parse_list(article(two))
        with self.assertRaisesRegex(SourceLayoutError, "solo uno"):  # mención sin fechas legibles
            uco.parse_list(article("<p>Plazo de presentación de solicitudes: diez días hábiles</p>"))

    def test_plazo_al_reves_o_imposible_detiene(self):
        for text in ("desde el 9 de diciembre al 1 de diciembre de 2026", "desde el 1 al 31 de noviembre de 2026"):
            with self.subTest(text), self.assertRaisesRegex(SourceLayoutError, "ilegible"):
                uco.parse_list(article(f"<p>Plazo de presentación de solicitudes: {text}</p>"))

    def test_plazo_que_cruza_el_año(self):
        row = uco.parse_list(article("<p>Plazo de presentación de solicitudes: desde el 22 de diciembre al 5 de "
                                     "enero de 2027</p>"))[0]
        self.assertEqual((row["opens_on"], row["deadline"]), ("2026-12-22", "2027-01-05"))

    def test_pagina_sin_articulos_o_articulo_sin_enlace_detiene(self):
        with self.assertRaisesRegex(SourceLayoutError, "no tiene artículos"):
            uco.parse_list("<html><body><p>Mantenimiento</p></body></html>")
        with self.assertRaisesRegex(SourceLayoutError, "sin enlace"):
            uco.parse_list('<div itemprop="blogPost"><h2>11ª</h2></div>')


class Offers(unittest.TestCase):
    def test_hoy_ninguna_en_plazo(self):
        http = Http()
        self.assertEqual(uco.UcoSource(now=at(2026, 11, 16)).list_offers(http), [])
        self.assertEqual(http.asked, [uco.INDEX])

    def test_tanda_en_plazo(self):
        source = uco.UcoSource(now=at(2026, 11, 5))
        [offer] = source.list_offers(Http())
        self.assertEqual((offer.ref, offer.company, offer.published_on, offer.opens_on, offer.deadline),
                         ("711", "Universidad de Córdoba", "2026-10-30", "2026-11-03", "2026-11-09"))
        self.assertEqual(offer.url, "https://www.uco.es/investigacion/portal/convocatorias-de-contratos/"
                                    "711-11-convocatoria-de-contratos-de-personal-investigador-y-tecnico-pit-2026")
        self.assertEqual(offer.apply_url, offer.url)
        detail = source.fetch_detail(Http(page="sin uso"), offer)
        self.assertEqual(detail.sections[0]["title"], "La convocatoria")
        self.assertIn("desde el 03 de noviembre al 09 de noviembre de 2026", detail.sections[0]["html"])

    def test_antes_de_abrir_tambien_sale(self):
        offers = uco.UcoSource(now=at(2026, 10, 25)).list_offers(Http())
        self.assertEqual([(o.ref, o.opens_on) for o in offers], [("711", "2026-11-03"), ("709", "2026-10-21")])

    def test_ultimo_de_la_primera_pagina_en_plazo_detiene(self):
        with self.assertRaisesRegex(SourceLayoutError, "último artículo"):
            uco.UcoSource(now=at(2025, 2, 25)).list_offers(Http())

    def test_ficha_sin_cache_relee_el_listado(self):
        offer = uco.UcoSource(now=at(2026, 11, 5)).list_offers(Http())[0]
        http = Http()
        detail = uco.UcoSource().fetch_detail(http, offer)
        self.assertIn("NOTAS IMPORTANTES", detail.sections[0]["html"])
        self.assertEqual(http.asked, [uco.INDEX])
        gone = Http(page=article("<p>Plazo de presentación de solicitudes: desde el 1 al 7 de diciembre de 2026</p>"))
        self.assertIsNone(uco.UcoSource().fetch_detail(gone, offer))


if __name__ == "__main__":
    unittest.main()
