import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import ofertastrabajo
from empleo.sources.ofertastrabajo import GaliciaSurSource, IdisSource

FIXTURES = Path(__file__).parent / "fixtures"


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


class Idis(unittest.TestCase):
    def test_listado_con_referencia_fechas_y_plazas(self):
        rows = ofertastrabajo.parse_idis(fixture("idis-publicadas.html"))
        self.assertEqual(len(rows), 4)
        self.assertEqual(rows[0], {
            "ref": "946", "url": "https://empleo.idisantiago.es/ofertastrabajo/inscripciones/946",
            "title": "Titulado/a Graduado/a I · Plataforma ISCIII de Dinamización e Innovación de las capacidades "
                     "industriales del SNS y su transferencia efectiva al sector productivo. PT23/00016",
            "source_title": "2 PLAZAS de 1.2 3 Titulado/a Graduado/a I", "code": "080/2026", "positions": 2,
            "opens_on": "2026-10-16", "deadline": "2026-10-28",
        })
        self.assertEqual((rows[-1]["code"], rows[-1]["deadline"]), ("Ctto 73/2018", "2018-09-23"))

    def test_solo_las_de_plazo_sin_vencer(self):
        http = Http({IdisSource.page: "idis-publicadas.html"})
        offers = IdisSource(at(2026, 10, 28, 22, 0)).list_offers(http)  # 23:00 del 28 en Madrid
        self.assertEqual([o.ref for o in offers], ["946", "947", "948"])
        first = offers[0]
        self.assertEqual((first.code, first.positions, first.opens_on, first.kind, first.apply_url),
                         ("080/2026", 2, "2026-10-16", None, first.url))
        self.assertEqual(IdisSource(at(2026, 10, 28, 23, 0)).list_offers(http), [])  # ya el 29

    def test_sin_convocatorias_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            ofertastrabajo.parse_idis("<html><body><p>Mantenimiento</p></body></html>")

    def test_pendiente_de_publicacion_sin_fechas_no_es_oferta(self):
        page = fixture("idis-publicadas.html").replace(
            "Fecha apertura: <strong>16/10/2026</strong><br>", "", 1).replace(
            "Fecha cierre: <strong>28/10/2026</strong>", "<span>Pendiente de publicación en DOGA</span>", 1)
        self.assertEqual(len(ofertastrabajo.parse_idis(page)), 3)

    def test_fecha_de_cierre_irreconocible_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            ofertastrabajo.parse_idis(fixture("idis-publicadas.html").replace("Fecha cierre:", "Fin del plazo:", 1))


class GaliciaSur(unittest.TestCase):
    def test_solo_las_que_tienen_plazo(self):
        rows = ofertastrabajo.parse_galiciasur(fixture("galiciasur-publicadas.html"))
        self.assertEqual([(r["ref"], r["opens_on"], r["deadline"]) for r in rows], [("315", "2026-11-12", "2026-11-22")])

    def test_la_referencia_sale_del_titulo(self):
        http = Http({GaliciaSurSource.page: "galiciasur-publicadas.html"})
        (offer,) = GaliciaSurSource(at(2026, 11, 12, 12, 0)).list_offers(http)
        self.assertEqual(offer.code, "25/26")
        self.assertEqual(offer.title, "Titulada/o Grado II – Personal de Apoyo a la Investigación. "
                                      "(Diplomatura/Grado con menos de 300 ECTS.) · “Investigación clínica "
                                      "traslacional para el tratamiento de enfermedades dermatológicas del "
                                      "Servicio de Dermatología del Complexo Hospitalario Universitario de Pontevedra”")
        self.assertTrue(offer.source_title.startswith("1.2.4 Titulada/o"))
        self.assertTrue(offer.source_title.endswith("(REF: 25/26)"))

    def test_sin_convocatorias_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            ofertastrabajo.parse_galiciasur("<div class='list-wrapper'></div>")

    def test_plazo_irreconocible_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):  # otra clase: ya no se ve el plazo
            ofertastrabajo.parse_galiciasur(fixture("galiciasur-publicadas.html").replace('class="plazo"', 'class="fechas"'))
        with self.assertRaises(SourceLayoutError):  # un estado que no conocemos
            ofertastrabajo.parse_galiciasur(fixture("galiciasur-publicadas.html").replace(
                "Convocatoria resuelta", "Plazo ampliado", 1))


class Titulo(unittest.TestCase):
    def test_sin_categoria_del_convenio_ni_plazas(self):
        for literal, title in [
            ("2 PLAZAS de 1.2 3 Titulado/a Graduado/a I", "Titulado/a Graduado/a I"),
            ("2 PLAZAS Titulado/a Graduado/a II", "Titulado/a Graduado/a II"),
            ("1.2.2 Titulado/a superior especialista", "Titulado/a superior especialista"),
            ("1.2.2. TITULADO/A SUPERIOR ESPECIALISTA", "TITULADO/A SUPERIOR ESPECIALISTA"),
            ("1.1. 4 INVESTIGADOR/A PREDOCTORAL R1", "INVESTIGADOR/A PREDOCTORAL R1"),
            ("1 1.3 Investigador/a R2-A", "Investigador/a R2-A"),
            ("1..2 1 TITULADO/A SUPERIOR DOCTOR/A", "TITULADO/A SUPERIOR DOCTOR/A"),
            (".2.3 TITULADO/A GRADUADO/A I", "TITULADO/A GRADUADO/A I"),
            ("Técnico de laboratorio", "Técnico de laboratorio"),
            ("Investigador R3 (Doctorado)", "Investigador R3 (Doctorado)"),
        ]:
            self.assertEqual(ofertastrabajo.job_title(literal, None)["title"], title, literal)
        self.assertIsNone(ofertastrabajo.job_title("Técnico de laboratorio", None)["source_title"])

    def test_el_proyecto_solo_si_esta_rotulado(self):
        title = lambda project: ofertastrabajo.job_title("1.2 3 Titulado/a Graduado/a I", project)["title"]
        self.assertEqual(title("Proyecto de investigación: PROMODAS. Resistencia al platino."),
                         "Titulado/a Graduado/a I · PROMODAS. Resistencia al platino.")
        self.assertEqual(title("Proyecto de investigación UMI-MedIA: Desarrollo y validación clínica."),
                         "Titulado/a Graduado/a I · UMI-MedIA: Desarrollo y validación clínica.")
        self.assertEqual(title("PROYECTO: “ESPACIO DE DATOS” TITULACIÓN REQUERIDA: Grado en Ciencias."),
                         "Titulado/a Graduado/a I · “ESPACIO DE DATOS”")
        self.assertEqual(title("Línea de Investigación: Microbiota.  TITULACIÓN REQUERIDA: Grado."),
                         "Titulado/a Graduado/a I · Microbiota.")
        self.assertEqual(title("Realización de actividades científico-técnicas (ver funciones en las BASES)"),
                         "Titulado/a Graduado/a I")


class Ficha(unittest.TestCase):
    def test_cuadros_y_recuadros_sin_fecha_limite(self):
        sections = ofertastrabajo.parse_ficha(fixture("galiciasur-ficha.html"))
        self.assertEqual([s["title"] for s in sections], [
            "Oferta de empleo (REF: 25/26)", "Condiciones/Duración", "Requisitos imprescindibles",
            "Requisitos valorables", "Más información", "Documentación"])
        self.assertIn("<p>- Hasta fin de proyecto/financiamiento.</p>", sections[1]["html"])

    def test_solo_se_enlazan_las_bases(self):
        sections = ofertastrabajo.parse_ficha(fixture("idis-ficha.html"))
        documents = sections[-1]["html"]
        self.assertIn("946/bases-oferta.pdf", documents)
        self.assertNotIn("tribunal", documents)
        self.assertNotIn("baremo", documents)

    def test_el_recuadro_sin_titulo_va_como_otros_datos(self):
        other = next(s for s in ofertastrabajo.parse_ficha(fixture("idis-ficha.html")) if s["title"] == "Otros datos")
        self.assertIn("Ubicación del puesto", other["html"])
        self.assertIn("Hospital Clínico Universitario de Santiago", other["html"])

    def test_el_texto_preformateado_queda_en_parrafos(self):
        merits = next(s for s in ofertastrabajo.parse_ficha(fixture("idis-ficha.html")) if s["title"] == "Méritos")
        self.assertTrue(merits["html"].startswith("<p>Accede a las BASES"))
        self.assertNotIn("<pre", merits["html"])

    def test_la_ficha_se_lee_al_pedir_el_detalle(self):
        source = IdisSource(at(2026, 10, 20))
        http = Http({source.page: "idis-publicadas.html",
                     "https://empleo.idisantiago.es/ofertastrabajo/inscripciones/946": "idis-ficha.html"})
        offer = source.list_offers(http)[0]
        detail = source.fetch_detail(http, offer)
        self.assertEqual(detail.sections[0]["title"], "Oferta de empleo")
        self.assertIsNone(detail.location)

    def test_ficha_sin_cuadros_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            ofertastrabajo.parse_ficha("<html><body>Error</body></html>")


if __name__ == "__main__":
    unittest.main()
