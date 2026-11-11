import io
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import ListedOffer, SourceLayoutError
from empleo.sources import fundesalud, navarrabiomed

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, listing, detail=None):
        self.listing, self.detail = listing, detail

    def get(self, url):
        return fixture(self.detail if url != navarrabiomed.PAGE and self.detail else self.listing)


class Navarrabiomed(unittest.TestCase):
    def test_tarjetas_con_referencia_y_fechas(self):
        entries = navarrabiomed.parse_listing(fixture("navarrabiomed-empleo.html"))
        self.assertEqual(entries[0], {
            "ref": "26-43", "title": "26-43 Personal apoyo a la investigación",
            "url": "https://navarrabiomed.es/es/empleo/26-43-personal-apoyo-investigacion",
            "published_on": "2026-11-06", "deadline": "2026-11-20",
        })
        self.assertEqual([e["ref"] for e in entries], ["26-43", "26-42"])

    def test_el_cierre_cuenta_el_dia_entero(self):
        http = Http("navarrabiomed-empleo.html")
        last_day = navarrabiomed.NavarrabiomedSource(datetime(2026, 11, 13, 22, 0, tzinfo=timezone.utc))
        self.assertEqual([o.ref for o in last_day.list_offers(http)], ["26-43", "26-42"])
        next_day = navarrabiomed.NavarrabiomedSource(datetime(2026, 11, 13, 23, 30, tzinfo=timezone.utc))
        offers = next_day.list_offers(http)
        self.assertEqual([o.ref for o in offers], ["26-43"])
        self.assertEqual((offers[0].company, offers[0].kind, offers[0].deadline_time),
                         ("Fundación Miguel Servet", None, None))

    def test_la_hora_de_cierre_sale_de_las_bases(self):
        def bases(name):
            return lambda http, url, what: fixture(name)
        offer = ListedOffer(ref="26-43", title="t", company="c", url="https://navarrabiomed.es/es/empleo/x",
                            apply_url="u", deadline="2026-11-20")
        source = navarrabiomed.NavarrabiomedSource()
        http = Http("navarrabiomed-empleo.html", "navarrabiomed-ficha.html")
        with mock.patch.object(navarrabiomed, "read_pdf", bases("navarrabiomed-bases-26-43.txt")):
            self.assertEqual(source.fetch_detail(http, offer).deadline_time, "12:00")
        # Ampliada: la hora del cierre ampliado, no la del primero.
        offer.deadline = "2026-11-13"
        with mock.patch.object(navarrabiomed, "read_pdf", bases("navarrabiomed-bases-26-42.txt")):
            self.assertEqual(source.fetch_detail(http, offer).deadline_time, "12:00")
        # Si las bases no hablan del día del listado, no hay hora.
        offer.deadline = "2026-11-21"
        with mock.patch.object(navarrabiomed, "read_pdf", bases("navarrabiomed-bases-26-43.txt")):
            self.assertIsNone(source.fetch_detail(http, offer).deadline_time)

    def test_bases_sin_texto_dejan_el_dia_entero(self):
        def broken(http, url, what):
            raise SourceLayoutError("sin texto")
        offer = ListedOffer(ref="26-43", title="t", company="c", url="https://navarrabiomed.es/es/empleo/x",
                            apply_url="u", deadline="2026-11-20")
        with mock.patch.object(navarrabiomed, "read_pdf", broken):
            detail = navarrabiomed.NavarrabiomedSource().fetch_detail(
                Http("navarrabiomed-empleo.html", "navarrabiomed-ficha.html"), offer)
        self.assertIsNone(detail.deadline_time)
        self.assertEqual(len(detail.sections), 2)

    def test_ficha_con_texto_y_bases(self):
        detail = navarrabiomed.parse_detail(fixture("navarrabiomed-ficha.html"))
        self.assertEqual([s["title"] for s in detail.sections], ["Convocatoria", "Documentos de la convocatoria"])
        self.assertIn("DIABYUDA", detail.sections[0]["html"])
        self.assertIn("26-43-personal-apoyo-a-la-investigacion", detail.sections[1]["html"])
        self.assertEqual(detail.location, "Pamplona (Navarra)")

    def test_cambios_de_marcado_detienen_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            navarrabiomed.parse_listing("<h1>Empleo</h1>")
        html = fixture("navarrabiomed-empleo.html").replace("end-date", "otra-fecha", 1)
        with self.assertRaises(SourceLayoutError):
            navarrabiomed.parse_listing(html)
        with self.assertRaises(SourceLayoutError):
            navarrabiomed.parse_detail("<article></article>")


class Fundesalud(unittest.TestCase):
    def test_tarjetas_de_todas_las_pestanas(self):
        entries = fundesalud.parse_page(fixture("fundesalud-ofertas.html"))
        self.assertEqual(entries[0], {
            "ref": "13387", "title": "UN /A TÉCNICO DE PROYECTOS I+D+i", "code": "Ref. 22/2026",
            "url": "https://fundesalud.es/personal/ofertas-de-empleo/ref-22-2026/",
            "opens_on": "2026-09-22", "deadline": "2026-09-28", "positions": 1,
        })
        self.assertEqual(len(entries), 3)

    def test_mandan_las_fechas_y_no_la_pestana(self):
        http = Http("fundesalud-ofertas.html")
        # Antes de empezar, la 22/2026 ya se ofrece con su inicio; la 20/2026 cerró en agosto.
        offers = fundesalud.FundesaludSource(datetime(2026, 9, 20, 10, 0, tzinfo=timezone.utc)).list_offers(http)
        self.assertEqual([(o.ref, o.opens_on, o.positions) for o in offers],
                         [("13387", "2026-09-22", 1), (offers[1].ref, "2026-09-15", 1)])
        self.assertEqual((offers[0].title, offers[0].code), ("UN /A TÉCNICO DE PROYECTOS I+D+i", "Ref. 22/2026"))
        later = fundesalud.FundesaludSource(datetime(2026, 9, 28, 23, 0, tzinfo=timezone.utc)).list_offers(http)
        self.assertEqual(later, [])

    def test_todas_las_formas_de_referencia_de_la_pagina_real(self):
        # Formas vistas el 2026-11-08 en las 139 tarjetas: la referencia se conserva tal cual, como código.
        html = fixture("fundesalud-ofertas.html")
        for label in ("Ref:18/2025", "REF. P26-03", "PMP25/2026", "NO12345 P1"):
            entries = fundesalud.parse_page(html.replace("Ref. 22/2026", label, 1))
            self.assertEqual((entries[0]["code"], entries[0]["title"]), (label, "UN /A TÉCNICO DE PROYECTOS I+D+i"))

    def test_tarjeta_vacia_se_salta_con_aviso(self):
        # Así salió la 23/2026 el 2026-11-11: publicada sin rellenar, con los campos invisibles.
        vacia = ('<div class="elementor e-loop-item post-13927 oferta-de-empleo">'
                 '<a href="https://fundesalud.es/personal/ofertas-de-empleo/ref-23-2026/"></a>'
                 '<div><!-- dce invisible element 70a21164 --></div></div>')
        html = fixture("fundesalud-ofertas.html")
        primera = html.index('<div class="elementor elementor-1202 e-loop-item')
        with mock.patch("sys.stderr", new_callable=io.StringIO) as stderr:
            entries = fundesalud.parse_page(html[:primera] + vacia + html[primera:])
        self.assertEqual([e["ref"] for e in entries], [e["ref"] for e in fundesalud.parse_page(html)])
        self.assertIn("AVISO fundesalud: tarjeta vacía", stderr.getvalue())
        with mock.patch("sys.stderr", new_callable=io.StringIO), self.assertRaises(SourceLayoutError):
            fundesalud.parse_page(vacia)

    def test_ficha_no_se_pide(self):
        offer = fundesalud.FundesaludSource().fetch_detail(None, None)
        self.assertEqual((offer.sections, offer.location), ([], "Extremadura"))

    def test_cambios_de_marcado_detienen_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            fundesalud.parse_page("<p>Ahora mismo no hay nada para mostrar</p>")
        html = fixture("fundesalud-ofertas.html").replace("Finaliza:", "Hasta:", 1)
        with self.assertRaises(SourceLayoutError):
            fundesalud.parse_page(html)
        html = fixture("fundesalud-ofertas.html").replace("post-13387", "entrada", 1)
        with self.assertRaises(SourceLayoutError):
            fundesalud.parse_page(html)


if __name__ == "__main__":
    unittest.main()
