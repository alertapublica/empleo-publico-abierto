import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import imdea

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, page):
        self.page, self.urls = page, []

    def get(self, url):
        self.urls.append(url)
        return self.page


def at(*args):
    return datetime(*args, tzinfo=timezone.utc)


class ImdeaEnergia(unittest.TestCase):
    def test_vacantes_con_fechas_en_ingles(self):
        rows = imdea.parse_list(fixture("imdea-energia-lista.html"))
        self.assertEqual([(r["ref"], r["code"], r["published_on"], r["deadline"]) for r in rows], [
            ("453", "26.76 TN6 PRE", "2026-11-03", "2026-12-01"), ("454", "26.77 AT7 TEC", "2026-11-03", "2026-11-17"),
            ("452", "26.75 NT5 POD", "2026-10-14", "2026-10-28")])
        self.assertEqual(rows[1]["url"], imdea.SITE + "/es/offer/454")
        self.assertTrue(rows[1]["title"].startswith("Técnico de laboratorio para apoyo operacional"))

    def test_solo_las_que_no_han_vencido(self):
        source = imdea.ImdeaEnergiaSource(at(2026, 11, 12, 12, 0))
        offers = source.list_offers(Http(fixture("imdea-energia-lista.html")))
        self.assertEqual([o.ref for o in offers], ["453", "454"])
        self.assertEqual((offers[1].company, offers[1].code, offers[1].deadline_time), ("IMDEA Energía", "26.77 AT7 TEC", None))
        late = imdea.ImdeaEnergiaSource(at(2026, 11, 18, 12, 0)).list_offers(Http(fixture("imdea-energia-lista.html")))
        self.assertEqual([o.ref for o in late], ["453"])

    def test_ficha(self):
        detail = imdea.parse_detail(fixture("imdea-energia-ficha.html"))
        self.assertEqual([s["title"] for s in detail.sections], [
            "Descripción", "Requisitos", "Criterios de selección", "Condiciones", "Lugar de trabajo",
            "Documentos que hay que adjuntar"])
        self.assertEqual((detail.contract, detail.location), ("Contrato según legislación vigente", "Móstoles"))
        self.assertIn("Técnico de Laboratorio Júnior", detail.sections[0]["html"])
        self.assertEqual(detail.sections[-1]["html"], "<ul><li>Título del Certificado Académico</li><li>Carta de Motivación</li></ul>")

    def test_cambios_de_pagina(self):
        with self.assertRaises(SourceLayoutError):
            imdea.parse_list("<html><body>Mantenimiento</body></html>")
        with self.assertRaises(SourceLayoutError):  # mes en castellano: hay que revisar el formato
            imdea.parse_list(fixture("imdea-energia-lista.html").replace("17 Nov 2026", "17 nov. 2026"))
        with self.assertRaises(SourceLayoutError):
            imdea.parse_list(fixture("imdea-energia-lista.html").replace("Fecha de fin", "Cierre"))
        with self.assertRaises(SourceLayoutError):
            imdea.parse_detail(fixture("imdea-energia-ficha.html").replace(">Descripción<", ">Resumen<"))


if __name__ == "__main__":
    unittest.main()
