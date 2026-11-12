import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import ccma

FIXTURES = Path(__file__).parent / "fixtures"
FICHA = ccma.SITE + "/seleccio/convocatoria.jsf?idConv=3316"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, index="ccma-index.html"):
        self.index, self.urls = index, []

    def get(self, url):
        self.urls.append(url)
        if url == ccma.PAGE:
            return self.index if self.index.startswith("<") else fixture(self.index)
        return fixture("ccma-convocatoria.html")


def at(*args):
    return datetime(*args, tzinfo=timezone.utc)


class Ccma(unittest.TestCase):
    def test_listado_de_procesos_oberts(self):
        (row,) = ccma.parse_list(fixture("ccma-index.html"))
        self.assertEqual(row, {
            "ref": "3316", "url": FICHA, "title": "2026 ENGINYER/A ESPECIALISTA EN PROJECTES D'INSTAL·LACIONS",
            "opens_on": "2026-10-26", "deadline": "2026-11-15",
            "scope": "Concurs públic / promoció interna", "company": "CCMA, SA",
        })

    def test_concurso_publico_con_hora_de_la_ficha(self):
        source = ccma.CcmaSource(at(2026, 11, 12, 12, 0))
        http = Http()
        (offer,) = source.list_offers(http)
        self.assertEqual((offer.ref, offer.company, offer.deadline, offer.deadline_time, offer.kind),
                         ("3316", "CCMA, SA", "2026-11-15", "23:59", None))
        sections = source.fetch_detail(http, offer).sections
        self.assertEqual([s["title"] for s in sections][:2], ["Convocatoria", "1. CARACTERÍSTIQUES DEL LLOC DE TREBALL"])
        self.assertNotIn("<p><p>", sections[0]["html"])
        self.assertEqual(len(http.urls), 2)  # la ficha no se vuelve a pedir

    def test_cierra_a_su_hora(self):
        self.assertEqual(ccma.CcmaSource(at(2026, 11, 15, 22, 59)).list_offers(Http()), [])  # 23:59 en Madrid

    def test_la_promocion_interna_no_se_lee(self):
        page = fixture("ccma-index.html").replace("Concurs públic / promoció interna", "Promoció interna")
        http = Http(page)
        self.assertEqual(ccma.CcmaSource(at(2026, 11, 12, 12, 0)).list_offers(http), [])
        self.assertEqual(http.urls, [ccma.PAGE])

    def test_hora_solo_si_es_la_misma_fecha(self):
        self.assertIsNone(ccma.parse_ficha(fixture("ccma-convocatoria.html"), "2026-11-16")["deadline_time"])
        self.assertIsNone(ccma.parse_ficha(fixture("ccma-convocatoria.html"), "2026-12-15")["deadline_time"])

    def test_hora_con_mes_apostrofado(self):
        page = fixture("ccma-convocatoria.html").replace("15 de novembre de 2026 a les 23:59h", "1 d’octubre de 2026 a les 14:00h")
        self.assertEqual(ccma.parse_ficha(page, "2026-10-01")["deadline_time"], "14:00")
        page = page.replace("d’octubre", "d'octubre")
        self.assertEqual(ccma.parse_ficha(page, "2026-10-01")["deadline_time"], "14:00")

    def test_ambito_ausente_o_desconocido_detiene_la_fuente(self):
        for page in (fixture("ccma-index.html").replace("Àmbit:", "Àmbit del procés:"),
                     fixture("ccma-index.html").replace("Concurs públic / promoció interna", "Borsa de treball")):
            with self.assertRaises(SourceLayoutError):
                ccma.CcmaSource(at(2026, 11, 12, 12, 0)).list_offers(Http(page))

    def test_lista_vacia_de_verdad(self):
        page = ('<h2 data-testid="seccio-processos">Processos de selecció oberts</h2>'
                '<div id="formLlistatVigents:llistaConvocatories"><div class="container"></div></div>')
        self.assertEqual(ccma.parse_list(page), [])

    def test_tarjetas_que_no_se_reconocen_detienen_la_fuente(self):
        page = ('<h2 data-testid="seccio-processos">Processos de selecció oberts</h2>'
                '<div id="formLlistatVigents:llistaConvocatories"><div class="nova"><h3>Tècnic/a</h3></div></div>')
        with self.assertRaises(SourceLayoutError):
            ccma.parse_list(page)
        with self.assertRaises(SourceLayoutError):
            ccma.parse_list("<html><body>Manteniment</body></html>")


if __name__ == "__main__":
    unittest.main()
