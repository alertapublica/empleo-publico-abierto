import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import fibao

FIXTURES = Path(__file__).parent / "fixtures"
FICHA = fibao.SITE + "/ofertas/ficha/{}/"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        page = self.pages[url]
        return page if page.startswith("<") else fixture(page)


def listing(*rows, count=None):
    count = len(rows) if count is None else count
    menu = (f'<div class="mod_nav_top"><ul><li><a href="./">Todas</a></li>'
            + (f'<li><a href="./?estado=Abierta">Abierta <span class="with-count">({count})</span></a></li>' if count else "")
            + "</ul></div>")
    articles = "".join(f'<article class="article_item article_event"><a href="/ofertas/ficha/{ref}/"><ul>'
                       f'<li><strong>Fecha:</strong><br />28 de Octubre de 2026</li></ul><h3>{title}</h3></a></article>'
                       for ref, title in rows) or '<article class="article_item no_events"><h1>No hay ofertas de empleo</h1></article>'
    return f"<html><body><section>{menu}{articles}</section></body></html>"


def at(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Fibao(unittest.TestCase):
    def test_listado_de_abiertas(self):
        rows = fibao.parse_list(fixture("fibao-abiertas.html"))
        self.assertEqual([(r["ref"], r["published_on"]) for r in rows], [("1505", "2026-11-03"), ("1504", "2026-10-29")])
        self.assertEqual(rows[0]["url"], FICHA.format(1505))

    def test_ficha_con_plazo_y_bases(self):
        ficha = fibao.parse_ficha(fixture("fibao-ficha.html"))
        self.assertEqual((ficha["deadline"], ficha["internal"]), ("2026-11-07", False))
        self.assertEqual([s["title"] for s in ficha["sections"]], ["Convocatoria", "Documentación"])
        self.assertIn("PI24/00888", ficha["sections"][0]["html"])
        self.assertIn("Bases de la convocatoria", ficha["sections"][1]["html"])
        self.assertNotIn("Inscripción online", ficha["sections"][0]["html"])

    def test_oferta_con_numero_como_codigo(self):
        http = Http({fibao.PAGE: listing(("1501", "87/2026.- Técnico/a Investigación PI24/00888")),
                     FICHA.format(1501): "fibao-ficha.html"})
        source = fibao.FibaoSource(at(2026, 11, 5, 12, 0))
        (offer,) = source.list_offers(http)
        self.assertEqual((offer.ref, offer.title, offer.deadline, offer.published_on),
                         ("1501", "87/2026.- Técnico/a Investigación PI24/00888", "2026-11-07", "2026-10-28"))
        # El literal llega a la ingesta, que separa el código y guarda el título original.
        self.assertEqual(source.labels(offer.title, offer.ref), {
            "title": "Técnico/a Investigación PI24/00888", "code": "87/2026",
            "source_title": "87/2026.- Técnico/a Investigación PI24/00888"})
        self.assertEqual(source.fetch_detail(http, offer).sections[0]["title"], "Convocatoria")
        self.assertEqual(len(http.urls), 2)  # la ficha no se vuelve a pedir

    def test_plazo_vencido(self):
        http = Http({fibao.PAGE: listing(("1501", "87/2026.- Técnico/a")), FICHA.format(1501): "fibao-ficha.html"})
        self.assertEqual(fibao.FibaoSource(at(2026, 11, 7, 23, 0)).list_offers(http), [])

    def test_ni_internas_ni_busqueda_de_candidatos_para_ayudas(self):
        http = Http({fibao.PAGE: "fibao-abiertas.html", FICHA.format(1505): "fibao-ficha-interna.html",
                     FICHA.format(1504): "fibao-ficha-pta.html"})
        self.assertEqual(fibao.FibaoSource(at(2026, 11, 12, 12, 0)).list_offers(http), [])
        self.assertNotIn(FICHA.format(1504), http.urls)  # descartada por el título
        self.assertTrue(fibao.parse_ficha(fixture("fibao-ficha-interna.html"))["internal"])

    def test_mas_de_una_pagina_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fibao.parse_list(fixture("fibao-abiertas.html").replace("</body>", '<a href="?page=2">2</a></body>'))

    def test_sin_convocatorias_y_sin_lista_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fibao.parse_list("<html><body>Página no encontrada</body></html>")
        self.assertEqual(fibao.parse_list(listing()), [])

    def test_vacio_real_sin_contador_de_abiertas(self):
        page = fixture("fibao-sin-resultados.html")  # un filtro sin resultados: «No hay ofertas de empleo»
        with self.assertRaises(SourceLayoutError):  # el menú dice 2 abiertas
            fibao.parse_list(page)
        self.assertEqual(fibao.parse_list(page.replace('Abierta <span class="with-count">(2)</span>', "")), [])

    def test_si_no_cuadra_con_el_contador_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fibao.parse_list(listing(("1501", "87/2026.- Técnico/a"), count=2))
        with self.assertRaises(SourceLayoutError):  # tarjetas con otra clase: no se ve ninguna
            fibao.parse_list(fixture("fibao-abiertas.html").replace("article_item article_event", "item"))

    def test_lista_vacia_sin_el_aviso_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fibao.parse_list(listing().replace("No hay ofertas de empleo", ""))

    def test_ficha_sin_plazo_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fibao.parse_ficha(fixture("fibao-ficha.html").replace("Fecha fin de presentación", "Último día"))

    def test_solo_se_enlazan_las_bases(self):
        page = fixture("fibao-ficha.html").replace(
            "</table>", '<tr><td>Acta de valoración de candidaturas</td><td><a href="/media/acta.pdf">Descargar</a></td></tr></table>')
        documents = fibao.parse_ficha(page)["sections"][-1]["html"]
        self.assertIn("Bases de la convocatoria", documents)
        self.assertNotIn("acta.pdf", documents)

    def test_ficha_sin_convocatoria_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            fibao.parse_ficha("<html><body>Página no encontrada</body></html>")


if __name__ == "__main__":
    unittest.main()
