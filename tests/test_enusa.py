import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo import ingest
from empleo.model import SourceLayoutError
from empleo.sources import enusa

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    def __init__(self, html=None):
        self.html, self.requests = html or fixture("enusa-bolsa.html"), []

    def get(self, url):
        self.requests.append(("GET", url))
        return "<html></html>"

    def post(self, url, fields):
        self.requests.append(("POST", url, fields))
        return self.html


class Listing(unittest.TestCase):
    def test_lee_filas_y_descripciones(self):
        processes = enusa.parse_listing(fixture("enusa-bolsa.html"))
        self.assertEqual([p["code"] for p in processes],
                         ["861-OPTAYM", "862-OPTAYM", "878-TTOFYD", "875-ADMUO", "880-OPEALM", "818-OPEUPC"])
        first = processes[0]
        self.assertEqual(first["title"], "OPERARIO/A TRATAMIENTO AGUAS, ING PLANTA Y MANTEN- MECA")
        self.assertEqual(first["published_on"], "2026-11-05")

    def test_sin_contador_no_pasa_por_vacia(self):
        with self.assertRaises(SourceLayoutError):
            enusa.parse_listing("<h1>Mantenimiento</h1>")

    def test_fila_sin_su_descripcion_no_se_interpreta(self):
        html = fixture("enusa-bolsa.html").replace('id="CAPA878"', 'id="OTRA878"')
        with self.assertRaises(SourceLayoutError):
            enusa.parse_listing(html)

    def test_bolsa_vacia(self):
        self.assertEqual(enusa.parse_listing("<td>Núm. de ofertas:&nbsp;0</td>"), [])

    def test_declara_ofertas_pero_no_hay_filas(self):
        with self.assertRaises(SourceLayoutError):
            enusa.parse_listing("<td>Núm. de ofertas:&nbsp;3</td>")


class Offers(unittest.TestCase):
    def setUp(self):
        self.source = enusa.EnusaSource()
        self.http = FakeHttp()
        self.offers = {o.ref: o for o in self.source.list_offers(self.http)}

    def test_abre_sesion_de_invitado_antes_de_pedir_la_lista(self):
        self.assertEqual(self.http.requests[0][0], "GET")
        method, url, fields = self.http.requests[1]
        self.assertEqual((method, url), ("POST", enusa.LOGIN))
        self.assertEqual(fields["_TYPE_LOGON"], "ANONYMOUS")

    def test_solo_los_procesos_con_plazo_son_ofertas(self):
        self.assertEqual(sorted(self.offers), ["818-OPEUPC", "875-ADMUO", "878-TTOFYD", "880-OPEALM"])

    def test_plazo_contrato_y_plazas(self):
        indefinida = self.offers["878-TTOFYD"]
        self.assertEqual(indefinida.deadline, "2026-11-19")
        self.assertEqual(indefinida.kind, "indefinido")
        self.assertEqual(indefinida.positions, 1)
        self.assertEqual(indefinida.title, "TÉCNICO/A TIITULADO/A ORGANIZACIÓN, FORMACIÓN Y DESARRO")
        self.assertEqual(self.offers["880-OPEALM"].kind, "temporal")

    def test_plazo_sin_ano_toma_el_de_la_publicacion(self):
        # «hasta el próximo día 11 de noviembre a las 23:59», publicada el 26-10-2026
        self.assertEqual(self.offers["875-ADMUO"].deadline, "2026-11-11")
        self.assertEqual(enusa._deadline("hasta el próximo día 5 de enero", "2026-12-20"), "2027-01-05")
        self.assertIsNone(enusa._deadline("hasta el próximo día 5 de enero", None))

    def test_si_amplian_el_plazo_vale_la_fecha_mayor(self):
        # el aviso dice «hasta el 18 de noviembre» y el texto original, «hasta el 5 de noviembre»
        self.assertEqual(self.offers["818-OPEUPC"].deadline, "2026-11-18")

    def test_localidad_cuando_el_texto_no_cierra_con_punto(self):
        # «Ubicación : Centro de trabajo de Madrid Horario: Según convenio del C.T. de Madrid»
        detail = self.source.fetch_detail(self.http, self.offers["875-ADMUO"])
        self.assertEqual(detail.location, "Madrid")

    def test_ficha_con_texto_y_localidad(self):
        detail = self.source.fetch_detail(self.http, self.offers["880-OPEALM"])
        self.assertEqual(detail.location, "Juzbado (Salamanca)")
        (section,) = detail.sections
        self.assertIn("seleccion@enusa.es", section["html"])
        self.assertNotIn("<table", section["html"])
        self.assertNotIn("style=", section["html"])

    def test_los_resultados_son_anuncios_sin_candidaturas(self):
        items = self.source.list_announcements(self.http)
        self.assertEqual(len(items), 2)  # el 875 tiene plazo abierto: es oferta
        self.assertEqual({i.date for i in items}, {"2026-11-05"})
        self.assertTrue(all(i.title == "Resultado de la revisión de requisitos mínimos" for i in items))
        self.assertTrue(all("00000" not in i.title and "DESCARTADO" not in i.title for i in items))
        self.assertEqual(len({i.key for i in items}), 2)


class EndToEnd(unittest.TestCase):
    def test_ingesta_completa(self):
        source, http, offers = enusa.EnusaSource(), FakeHttp(), {}
        now = datetime(2026, 11, 7, 12, tzinfo=timezone.utc)
        events = ingest.reconcile(offers, source.list_offers(http), "enusa", now)
        ingest.fetch_details(source, http, offers, events)
        ingest.apply_enrichment(source, http, offers)
        record = offers["878-TTOFYD"]
        self.assertEqual(record["id"], "enusa:878-TTOFYD")
        self.assertEqual(record["location"], "Madrid")
        self.assertEqual(record["region"], "Comunidad de Madrid")
        self.assertRegex(record["published_on"], r"^2026-\d{2}-\d{2}$")
        self.assertEqual(len(offers), 4)


if __name__ == "__main__":
    unittest.main()
