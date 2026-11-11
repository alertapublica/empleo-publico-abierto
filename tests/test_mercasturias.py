import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

from empleo.model import SourceLayoutError
from empleo.sources import mercasturias

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


# La misma página cuando el proceso de limpieza aún admitía candidaturas: bases y ampliación.
EN_PLAZO = """<td class="cont"><div class="CollapsiblePanel" id="CollapsiblePanel7">
<div class="CollapsiblePanelTab"><strong>OFERTAS DISPONIBLES</strong></div>
<div class="CollapsiblePanelContent">
<a href="https://mercasturias.com/ofertas_empleo/AMPLIACION_SEPTIEMBRE_2026.pdf">Ampliación de plazo de presentación de candidaturas establecido en las bases de la convocatoria del proceso selectivo</a><br/>
7 de octubre 2026<br/><br/>
<a href="https://mercasturias.com/ofertas_empleo/BASES_SEPTIEMBRE_2026.pdf">Cobertura de puesto de trabajo Operario/a de limpieza, jardinería y conservación</a><br/>
28 de septiembre 2026<br/><br/>
</div></div></td>"""


class Http:
    def __init__(self, html):
        self.html = html

    def get(self, url):
        return self.html


def pdfs(http, url, what):
    return fixture("mercasturias-ampliacion.txt" if "AMPLIACION" in url else "mercasturias-bases.txt")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


def read(html, now):
    source = mercasturias.MercasturiasSource(now=now)
    with mock.patch.object(mercasturias, "read_pdf", pdfs) as reader:
        offers = source.list_offers(Http(html))
        notices = source.list_announcements(Http(html))
        details = [source.fetch_detail(Http(html), offer) for offer in offers]
    return offers, notices, details


class Page(unittest.TestCase):
    def setUp(self):
        self.processes = mercasturias.parse_page(fixture("mercasturias-ofertas.html"))

    def test_cada_bases_abre_un_proceso(self):
        self.assertEqual([p["job"] for p in self.processes], [
            "Operario/a de mantenimiento, limpieza y conservación",
            "Operario/a de limpieza, jardinería y conservación"])
        self.assertEqual([len(p["documents"]) for p in self.processes], [6, 5])

    def test_documentos_en_orden_y_con_fecha(self):
        docs = self.processes[1]["documents"]
        self.assertEqual([d["date"] for d in docs],
                         ["2026-09-28", "2026-10-07", "2026-10-19", "2026-10-26", "2026-11-04"])
        self.assertEqual(docs[-1]["label"], "Puntuación fase de oposición")
        self.assertTrue(docs[0]["url"].endswith("BASES_DE_LA_CONVOCATORIA_DEL_PROCESO_SELECTIVO_SEPTIEMBRE_2026.pdf"))

    def test_con_relaciones_ya_no_es_candidato(self):
        self.assertEqual([mercasturias._is_candidate(p) for p in self.processes], [False, False])

    def test_panel_vacio_no_es_error(self):
        html = EN_PLAZO.split('<div class="CollapsiblePanelContent">')[0] + '<div class="CollapsiblePanelContent"></div></div>'
        self.assertEqual(mercasturias.parse_page(html), [])

    def test_sin_panel_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            mercasturias.parse_page("<p>Ofertas de empleo</p>")

    def test_documento_sin_bases_detiene_la_fuente(self):
        html = EN_PLAZO.replace("Cobertura de puesto de trabajo", "Convocatoria")
        with self.assertRaises(SourceLayoutError):
            mercasturias.parse_page(html)


class Source(unittest.TestCase):
    def test_hoy_solo_procesos_y_sin_leer_pdf(self):
        with mock.patch.object(mercasturias, "read_pdf", side_effect=AssertionError("no hace falta")):
            source = mercasturias.MercasturiasSource(now=at(11, 11))
            html = fixture("mercasturias-ofertas.html")
            self.assertEqual(source.list_offers(Http(html)), [])
            notices = source.list_announcements(Http(html))
        self.assertEqual(len(notices), 11)
        self.assertEqual({n.state for n in notices}, {"curso"})
        self.assertEqual(notices[0].title, notices[0].process)  # las bases, con el título que les da la web

    def test_en_plazo_es_oferta_con_la_ampliacion(self):
        offers, notices, details = read(EN_PLAZO, at(10, 15))
        (offer,) = offers
        self.assertEqual(offer.title, "Operario/a de limpieza, jardinería y conservación")
        self.assertEqual((offer.deadline, offer.deadline_time, offer.kind), ("2026-10-18", "23:59", "indefinido"))
        self.assertEqual(offer.published_on, "2026-09-28")
        self.assertEqual(notices, [])
        self.assertEqual(details[0].location, "Llanera")

    def test_vencida_la_hora_pasa_a_proceso(self):
        offers, notices, _ = read(EN_PLAZO, at(10, 18, 22))  # 00:00 del 19 en Madrid
        self.assertEqual(offers, [])
        self.assertEqual([n.date for n in notices], ["2026-09-28", "2026-10-07"])


if __name__ == "__main__":
    unittest.main()
