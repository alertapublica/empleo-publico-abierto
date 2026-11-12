import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import cesga

FIXTURES = Path(__file__).parent / "fixtures"
OPEN = cesga.SITE + "/oferta/6ae1f559677f3c9a32b9ae5d"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        return fixture(self.pages[url])


def at(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Cesga(unittest.TestCase):
    def test_listado_con_las_cerradas(self):
        rows = cesga.parse_list(fixture("cesga-lista.html"))
        self.assertEqual([(r["code"], r["deadline"]) for r in rows], [
            ("HPQC-QEX-26-INV2 -TCC", "2026-11-13"), ("QUANTUMSEC-26-TSINV1", "2026-10-20"), ("TSIS-26-INT", "2026-10-09")])
        self.assertEqual(rows[0]["url"], OPEN)
        self.assertEqual(rows[0]["positions"], 1)

    def test_ficha_con_hora_y_descripcion_en_castellano(self):
        ficha = cesga.parse_ficha(fixture("cesga-ficha.html"))
        self.assertEqual((ficha["deadline"], ficha["deadline_time"], ficha["published_on"]),
                         ("2026-11-13", "14:00", "2026-10-30"))
        description, documents = ficha["sections"]
        self.assertIn("Es deseable que el técnico/a", description["html"])
        self.assertNotIn("lang", description)
        self.assertEqual(documents["lang"], "gl")
        self.assertIn("newAttachments-1793270483703-57679285.pdf", documents["html"])
        self.assertIn("DOG, 30 de outubro 2026", documents["html"])

    def test_sin_version_castellana_va_la_gallega(self):
        html = fixture("cesga-ficha.html")
        start = html.index("spanish: `") + len("spanish: `")
        html = html[:start] + html[html.index("`", start):]
        description = cesga.parse_ficha(html)["sections"][0]
        self.assertEqual(description["lang"], "gl")
        self.assertIn("É desexable que o técnico/a", description["html"])

    def test_solo_las_que_no_han_vencido_con_la_hora_de_la_ficha(self):
        pages = {cesga.PAGE: "cesga-lista.html", OPEN: "cesga-ficha.html"}
        http = Http(pages)
        source = cesga.CesgaSource(at(2026, 11, 12, 12, 0))
        (offer,) = source.list_offers(http)
        self.assertEqual(http.urls, [cesga.PAGE, OPEN])  # las cerradas, sin leer la ficha
        self.assertEqual((offer.ref, offer.code, offer.title, offer.company), (
            "6ae1f559677f3c9a32b9ae5d", "HPQC-QEX-26-INV2 -TCC",
            "Investigador/a en tecnoloxías de computación cuántica", "CESGA (Centro de Supercomputación de Galicia)"))
        self.assertEqual((offer.deadline, offer.deadline_time, offer.published_on, offer.positions),
                         ("2026-11-13", "14:00", "2026-10-30", 1))
        detail = source.fetch_detail(http, offer)
        self.assertEqual(detail.location, "Santiago de Compostela")
        self.assertEqual(len(http.urls), 2)  # la ficha no se vuelve a pedir
        # 13:30 UTC son las 14:30 en Santiago: ya ha cerrado aunque el día no haya acabado
        self.assertEqual(cesga.CesgaSource(at(2026, 11, 13, 13, 30)).list_offers(Http(pages)), [])

    def test_cambios_de_pagina(self):
        with self.assertRaises(SourceLayoutError):
            cesga.parse_list("<html><body>Mantemento</body></html>")
        with self.assertRaises(SourceLayoutError):
            cesga.parse_list(fixture("cesga-lista.html").replace(">Prazo<", ">Data<"))
        with self.assertRaises(SourceLayoutError):
            cesga.parse_ficha(fixture("cesga-ficha.html").replace("13/11/2026 14:00", "13/11/2026"))
        with self.assertRaises(SourceLayoutError):
            cesga.parse_ficha(fixture("cesga-ficha.html").replace("spanish:", "castellano:"))

    def test_descripcion_solo_si_es_un_literal_entero_de_jobdata(self):
        html = fixture("cesga-ficha.html")
        with self.assertRaises(SourceLayoutError):  # concatenada: no se toma solo el primer trozo
            cesga.parse_ficha(html.replace("spanish: `", "spanish: `<p>Perfil</p>` + `", 1))
        # Las mismas claves en otro objeto, antes de `jobData`, no cuentan
        decoy = "<script>const otro = { spanish: `<p>Otro texto</p>`, };</script>"
        ficha = cesga.parse_ficha(html.replace("<script>", decoy + "<script>", 1))
        self.assertNotIn("Otro texto", ficha["sections"][0]["html"])

    def test_ficha_incompleta_avisa_sin_parar_el_listado(self):
        pages = {cesga.PAGE: "cesga-lista.html", OPEN: "cesga-ficha.html"}
        html = fixture("cesga-ficha.html").replace("Documentación da convocatoria", "Documentos")
        http = Http(pages)
        http.get = lambda url: html if url == OPEN else fixture(pages[url])
        source = cesga.CesgaSource(at(2026, 11, 12, 12, 0))
        (offer,) = source.list_offers(http)  # el plazo se sigue leyendo
        with self.assertRaises(SourceLayoutError):
            source.fetch_detail(http, offer)


if __name__ == "__main__":
    unittest.main()
