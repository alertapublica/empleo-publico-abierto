import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import cimus

FIXTURES = Path(__file__).parent / "fixtures"
OPEN = "https://cimus.usc.gal/es/empleo/convocatoria-publica-urgente-cimus-232026-de-contratacion-de-personal-para-colaborar-en-las"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self):
        self.urls = []

    def get(self, url):
        self.urls.append(url)
        if url == cimus.PAGE:
            return fixture("cimus-empleo.html")
        return fixture("cimus-ficha-abierta.html" if url == OPEN else "cimus-ficha-cerrada.html")


def ficha(text, field="2026-11-10"):
    return (f'<article class="node--type-job" data-history-node-id="1"><div class="field--name-field-offer">'
            f'<p>{text}</p></div><span class="field--name-field-deadline-job">'
            f'<time datetime="{field}T12:00:00Z">x</time></span></article>')


class Cimus(unittest.TestCase):
    def test_listado_sin_fechas(self):
        rows = cimus.parse_list(fixture("cimus-empleo.html"))
        self.assertEqual(len(rows), 6)
        self.assertEqual(rows[0]["url"], OPEN)
        self.assertTrue(rows[0]["title"].startswith("Convocatoria Pública Urgente CiMUS 23/2026"))

    def test_ficha_abierta_con_inicio_y_hora(self):
        e = cimus.parse_ficha(fixture("cimus-ficha-abierta.html"))
        self.assertEqual(e, {"ref": "5182", "deadline": "2026-11-10", "deadline_time": "23:59",
                             "opens_on": "2026-11-06", "published_on": "2026-11-05"})

    def test_el_plazo_de_enmiendas_no_es_el_de_inscripcion(self):
        e = cimus.parse_ficha(fixture("cimus-ficha-cerrada.html"))
        self.assertEqual((e["deadline"], e["deadline_time"], e["published_on"]), ("2026-10-19", "23:59", "2026-10-14"))

    def test_ampliacion_en_el_texto_vale_la_fecha_mayor(self):
        e = cimus.parse_ficha(ficha("Fecha fin candidaturas: 12/11/2026 14:00"))
        self.assertEqual((e["deadline"], e["deadline_time"]), ("2026-11-12", "14:00"))

    def test_sin_hora_si_el_texto_da_otro_dia(self):
        e = cimus.parse_ficha(ficha("Fecha fin candidaturas: 08/11/2026 23:59"))
        self.assertEqual((e["deadline"], e["deadline_time"]), ("2026-11-10", None))

    def test_solo_las_primeras_fichas_y_las_abiertas(self):
        http = Http()
        (offer,) = cimus.CimusSource(datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)).list_offers(http)
        self.assertEqual(len(http.urls), 1 + cimus.FICHAS)
        self.assertEqual((offer.ref, offer.kind, offer.contract, offer.url, offer.apply_url),
                         ("5182", None, None, OPEN, OPEN))

    def test_cierra_a_su_hora(self):
        late = datetime(2026, 11, 10, 22, 59, tzinfo=timezone.utc)  # 23:59 en Madrid
        self.assertEqual(cimus.CimusSource(late).list_offers(Http()), [])

    def test_sin_tabla_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            cimus.parse_list("<main><p>Empleo</p></main>")

    def test_ficha_sin_convocatoria_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            cimus.parse_ficha("<main><p>Página no encontrada</p></main>")


if __name__ == "__main__":
    unittest.main()
