import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import ua

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


def at(month, day, hour=10):
    return datetime(2026, month, day, hour, 0, tzinfo=timezone.utc)


class Http:
    """Los dos tablones reales del 2026-11-15; cuatro fichas reales y, para las demás, la I-PTGAI 33-26
    (plazo de junio)."""

    FICHAS = {"/pi57/": "ua-ficha-pi57.html", "/pi79/": "ua-ficha-pi79.html", "/ptgai55/": "ua-ficha-ptgai55.html"}

    def __init__(self, login=()):
        self.asked = []
        self.login = login

    def get(self, url):
        self.asked.append(url)
        if url == ua.LISTS[0]:
            return fixture("ua-investigador.html")
        if url == ua.LISTS[1]:
            return fixture("ua-tecnico.html")
        if any(part in url for part in self.login):
            return fixture("ua-login.html")
        return fixture(next((name for part, name in self.FICHAS.items() if part in url), "ua-ficha-ptgai33.html"))


class List(unittest.TestCase):
    def test_tarjetas_con_codigo_puesto_departamento_y_dogv(self):
        rows = ua.parse_list(fixture("ua-investigador.html"))
        self.assertEqual((len(rows), len(ua.parse_list(fixture("ua-tecnico.html")))), (40, 23))
        self.assertEqual(rows[0], {
            "ref": "2026-pi57", "code": "I-PI 57-26",
            "url": "https://ssp.ua.es/es/selecinvest/03-personal-investigador/2026/pi57/convocatoria-i-pi-57-26.html",
            "title": "Personal investigador en formación para colaborar con el proyecto «Contribuciones de la geodesia "
                     "al transporte de agua y al riesgo hidrometeorológico»",
            "department": "Departamento de Matemática Aplicada e Ingeniería Aeroespacial", "published_on": "2026-11-13",
        })
        # La errata de la tarjeta se queda en el listado; la clave sale del enlace.
        errata = next(row for row in rows if row["ref"] == "2026-pi79")
        self.assertEqual(errata["code"], "I-PI 79-25")

    def test_tarjeta_incompleta_o_tablon_vacio_detienen_la_fuente(self):
        html = fixture("ua-tecnico.html")
        for broken in (html.replace("noticia__fecha", "otra-fecha"), html.replace("Convocatoria I-PTGAI 55-26", "I-PTGAI 55-26"),
                       html.replace("/2026/ptgai55/", "/ptgai55/"), "<main><p>Nada</p></main>"):
            with self.assertRaises(SourceLayoutError):
                ua.parse_list(broken)


class Ficha(unittest.TestCase):
    def test_tecnico_indefinido_con_plazo_en_el_mismo_mes(self):
        ficha = ua.parse_ficha(fixture("ua-ficha-ptgai55.html"))
        self.assertEqual({k: ficha[k] for k in ("code", "opens_on", "deadline", "contract", "kind", "category")}, {
            "code": "I-PTGAI 55-26", "opens_on": "2026-11-09", "deadline": "2026-11-20",
            "contract": "contratación indefinida", "kind": "indefinido", "category": "Tecnólogo/a superior",
        })
        titles = [section["title"] for section in ficha["sections"]]
        self.assertEqual(titles, ["Convocatoria", "Datos de la convocatoria", "Solicitudes"])
        convocatoria, datos, solicitudes = (section["html"] for section in ficha["sections"])
        self.assertIn("<p><strong>Primer proyecto en el que va a colaborar:</strong></p>", convocatoria)
        self.assertTrue(datos.startswith("<p><strong>Plazas Personal Técnico Proy. Investigación</strong></p>"))
        self.assertIn("01.-convocatoria-dogv-i-ptgai-55-26-es.pdf", datos)
        self.assertIn("Del 09 al 20 de noviembre de 2026", solicitudes)
        # Las resoluciones (listas de personas) no se copian.
        self.assertNotIn("aspirantes admitidos", "".join(section["html"] for section in ficha["sections"]))

    def test_investigador_temporal_e_indefinido_y_plazo_entre_meses(self):
        ficha = ua.parse_ficha(fixture("ua-ficha-pi57.html"))
        self.assertEqual((ficha["kind"], ficha["opens_on"], ficha["deadline"]), ("temporal", "2026-11-16", "2026-11-27"))
        ficha = ua.parse_ficha(fixture("ua-ficha-pi79.html"))
        self.assertEqual((ficha["code"], ficha["kind"], ficha["category"]), ("I-PI 79-26", "indefinido", "Investigador/a Colaborador/a"))
        self.assertEqual((ficha["opens_on"], ficha["deadline"]), ("2026-10-29", "2026-11-11"))

    def test_pestanya_de_aviso_se_copia(self):
        ficha = ua.parse_ficha(fixture("ua-ficha-ptgai33.html"))
        self.assertEqual([s["title"] for s in ficha["sections"]], ["Convocatoria", "Datos de la convocatoria", "AVISO", "Solicitudes"])

    def test_plazo_que_cruza_de_anyo(self):
        self.assertEqual(ua._period("PLAZO DE PRESENTACIÓN DE SOLICITUDES: Del 22 de diciembre al 9 de enero de 2027"),
                         ("2026-12-22", "2027-01-09"))
        self.assertEqual(ua._period("PLAZO DE PRESENTACIÓN DE SOLICITUDES: Del 22 de diciembre de 2026 al 9 de enero de 2027"),
                         ("2026-12-22", "2027-01-09"))

    def test_con_dos_plazos_vale_el_que_acaba_mas_tarde(self):
        text = ("PLAZO DE PRESENTACIÓN DE SOLICITUDES: Del 27 de octubre al 7 de noviembre de 2026. "
                "NUEVO PLAZO DE PRESENTACIÓN DE SOLICITUDES: Del 12 al 25 de noviembre de 2026")
        self.assertEqual(ua._period(text), ("2026-11-12", "2026-11-25"))

    def test_ficha_retirada_tras_el_login(self):
        self.assertIsNone(ua.parse_ficha(fixture("ua-login.html")))

    def test_ficha_sin_plazo_o_sin_solicitudes_detiene_la_fuente(self):
        html = fixture("ua-ficha-pi57.html")
        for broken in (html.replace("Del 16 al 27 de noviembre", "Del 16 de noviembre"),
                       html.replace(">Solicitudes<", ">Inscripción<"), "<html><body><p>Error</p></body></html>"):
            with self.assertRaises(SourceLayoutError):
                ua.parse_ficha(broken)


class Source(unittest.TestCase):
    def test_solo_fichas_de_los_ultimos_60_dias_y_en_plazo(self):
        http = Http()
        source = ua.UaSource(now=at(11, 15))
        offers = source.list_offers(http)
        # 19 investigadores y 10 técnicos publicados desde el 16/09: el resto ni se abre.
        self.assertEqual(len(http.asked), 2 + 19 + 10)
        self.assertEqual([offer.code for offer in offers], ["I-PI 57-26", "I-PTGAI 55-26"])
        first = offers[0]
        self.assertEqual((first.ref, first.kind, first.opens_on, first.deadline, first.url),
                         ("2026-pi57", "temporal", "2026-11-16", "2026-11-27", first.apply_url))
        self.assertEqual(source.fetch_detail(http, first).location, "Alicante")
        # La fecha del DOGV y el departamento llegan por enrich: el motor solo lo llama si falta la fecha.
        self.assertIsNone(first.published_on)
        self.assertEqual(source.enrich(http)["2026-pi57"], {
            "published_on": "2026-11-13", "department": "Departamento de Matemática Aplicada e Ingeniería Aeroespacial"})

    def test_vale_el_codigo_de_la_ficha_y_se_saltan_las_retiradas(self):
        offers = ua.UaSource(now=at(11, 5)).list_offers(Http(login=("/pi57/",)))
        self.assertEqual([offer.code for offer in offers], ["I-PI 79-26", "I-PTGAI 55-26"])


if __name__ == "__main__":
    unittest.main()
