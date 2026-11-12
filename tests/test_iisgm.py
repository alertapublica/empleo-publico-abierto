import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import iisgm

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        page = self.pages[url]
        return page if page.startswith("<") else fixture(page)


def at(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Iisgm(unittest.TestCase):
    def test_tarjetas_con_plazo(self):
        rows = iisgm.parse_list(fixture("iisgm-lista.html"))
        self.assertEqual([(r["ref"], r["opens_on"], r["deadline"]) for r in rows], [
            ("135", "2026-11-10", "2026-11-19"), ("133", "2026-11-10", "2026-11-19"),
            ("132", "2026-11-06", "2026-11-15"), ("129", "2026-10-27", "2026-11-06")])
        self.assertEqual(rows[0]["url"], iisgm.SITE + "/ofertas-de-empleo/135/study-coordinator-oncohematologia-pediatrica-ref-108-2026")
        self.assertEqual(rows[0]["title"], "STUDY COORDINATOR ONCOHEMATOLOGÍA PEDIÁTRICA REF.108_2026")

    def test_en_plazo_y_sin_becas(self):
        http = Http({iisgm.PAGE: "iisgm-lista.html"})
        offers = iisgm.IisgmSource(at(2026, 11, 12, 12, 0)).list_offers(http)
        self.assertEqual([o.ref for o in offers], ["135", "132"])  # 133 es una beca; 129 cerró el 6
        self.assertEqual(http.urls, [iisgm.PAGE])  # la última tarjeta ya cerró: no hace falta la página 2
        self.assertEqual((offers[0].opens_on, offers[0].deadline, offers[0].deadline_time), ("2026-11-10", "2026-11-19", None))

    def test_pasa_de_pagina_mientras_la_ultima_siga_en_plazo(self):
        first = fixture("iisgm-lista.html").replace('datetime="2026-11-06"', 'datetime="2026-11-16"')
        http = Http({iisgm.PAGE: first, iisgm.PAGE + "page/2": "iisgm-lista.html"})
        offers = iisgm.IisgmSource(at(2026, 11, 12, 12, 0)).list_offers(http)
        self.assertEqual(http.urls, [iisgm.PAGE, iisgm.PAGE + "page/2"])
        self.assertIn("129", [o.ref for o in offers])
        always = Http({iisgm.PAGE: first, **{f"{iisgm.PAGE}page/{n}": first for n in (2, 3, 4)}})
        with self.assertRaises(SourceLayoutError):
            iisgm.IisgmSource(at(2026, 11, 12, 12, 0)).list_offers(always)

    def test_ficha(self):
        detail = iisgm.parse_detail(fixture("iisgm-ficha.html"))
        self.assertEqual([s["title"] for s in detail.sections], ["Datos del puesto", "Requisitos", "Documentos relacionados"])
        self.assertIn("Grado en Farmacia + Máster", detail.sections[0]["html"])
        self.assertIn("ÚNICO ARCHIVO PDF", detail.sections[1]["html"])
        self.assertIn('href="https://iisgm.com/media/upload/pdf/Study%20coordinator%20OncoHematolog%C3%ADa', detail.sections[2]["html"])
        self.assertIn(">OFERTA Y REQUISITOS 108_2026</a>", detail.sections[2]["html"])  # sin el tamaño del PDF
        self.assertEqual(detail.location, "Madrid")

    def test_cambios_de_pagina(self):
        with self.assertRaises(SourceLayoutError):
            iisgm.parse_list("<html><body>Mantenimiento</body></html>")
        with self.assertRaises(SourceLayoutError):
            iisgm.parse_list(fixture("iisgm-lista.html").replace('datetime="2026-11-19"', 'datetime=""', 1))
        with self.assertRaises(SourceLayoutError):
            iisgm.parse_detail(fixture("iisgm-ficha.html").replace("text-18", "texto"))


if __name__ == "__main__":
    unittest.main()
