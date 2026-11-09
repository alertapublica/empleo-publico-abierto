import json
import unittest
from datetime import date
from pathlib import Path

from empleo.model import SourceLayoutError, process_type
from empleo.sources import rtve

FIXTURES = Path(__file__).parent / "fixtures"


def raw(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeHttp:
    """Sirve los JSON reales; `edit` permite cambiar los de la convocatoria 1."""

    def __init__(self, edit=None):
        self.edit, self.requests = edit, []

    def get(self, url):
        self.requests.append(url)
        if url.endswith("getConvocatorias"):
            return raw("rtve-convocatorias.json")
        number = url.rsplit("=", 1)[1]
        text = raw(f"rtve-puestos-{number}.json")
        if number == "1" and self.edit:
            data = json.loads(text)
            self.edit(data)
            text = json.dumps(data)
        return text


class Announcements(unittest.TestCase):
    def setUp(self):
        self.source = rtve.RtveSource(today=date(2026, 11, 7))
        self.http = FakeHttp()
        self.source.list_offers(self.http)
        self.items = self.source.list_announcements(self.http)

    def test_hoy_no_hay_inscripciones_abiertas(self):
        # comprobado en la API real el 7-11-2026: todas las fechas de inscripción vienen vacías
        self.assertEqual(self.source.list_offers(self.http), [])

    def test_lee_las_dos_convocatorias(self):
        self.assertEqual(len(self.http.requests), 3)  # convocatorias + una petición por convocatoria
        self.assertTrue(self.http.requests[1].endswith("idConvocatoria=9"))

    def test_documentos_recientes_con_titulo_fecha_y_enlace(self):
        self.assertTrue(self.items)
        newest = max(self.items, key=lambda i: i.date)
        self.assertEqual(newest.date, "2026-11-03")
        self.assertEqual(newest.title, "Adjudicación bolsa de reserva 02")
        self.assertEqual(newest.url, "https://convocatorias.rtve.es/Documentos/convocatoria-1/listados/"
                                     "AMDE_P3_Adjudicaci%C3%B3n-bolsa-de-reserva-02_PUBLICO.pdf")
        self.assertIn("Ambientación decorados", newest.process)
        self.assertIn("Proceso Libre", newest.process)

    def test_los_documentos_antiguos_no_entran(self):
        self.assertTrue(all(i.date >= "2026-05-11" for i in self.items))

    def test_banco_de_datos_incluido(self):
        self.assertTrue(any("Banco de datos" in i.process for i in self.items))

    def test_claves_distintas_y_sin_nombres_de_personas(self):
        self.assertEqual(len({i.key for i in self.items}), len(self.items))
        self.assertIn(process_type(self.items[0].process), ("otro", "bolsa"))

    def test_cada_convocatoria_con_su_via_y_contrato(self):
        bank = next(i for i in self.items if "Banco de datos" in i.process)
        self.assertEqual((bank.via, bank.contract), ("bolsa", None))
        free = next(i for i in self.items if "Proceso Libre" in i.process)
        self.assertEqual((free.via, free.access, free.contract), ("otro", "libre", "indefinido"))

    def test_sistema_segun_sus_documentos(self):
        post = {"process": "Proceso Libre", "documents": [
            {"title": "Listado provisional de méritos"}, {"title": "Puntuaciones prueba práctica"}]}
        self.assertEqual(rtve._system(post), "concurso-oposicion")
        self.assertEqual(rtve._system({"process": "Proceso sólo méritos", "documents": []}), "concurso")


class Offers(unittest.TestCase):
    """Con datos reales no hay inscripciones abiertas; aquí se ponen fechas inventadas para
    comprobar el camino de las ofertas."""

    @staticmethod
    def open_first(start="2026-11-01", end="2026-11-20T23:59:59"):
        def edit(data):
            post = data[0]["puestos"][0]
            post["fechaInicioInscripcion"], post["fechaFinInscripcion"] = start, end
        return edit

    def offers(self, edit, today=date(2026, 11, 7)):
        source = rtve.RtveSource(today=today)
        http = FakeHttp(edit)
        return source, http, source.list_offers(http)

    def test_puesto_con_inscripcion_abierta_es_oferta(self):
        source, http, offers = self.offers(self.open_first())
        (offer,) = offers
        self.assertEqual(offer.deadline, "2026-11-20")
        self.assertEqual(offer.kind, "indefinido")
        self.assertEqual(offer.positions, 3)
        self.assertEqual(offer.title, "Ambientación decorados")
        self.assertEqual(offer.category, "Proceso Libre")
        self.assertRegex(offer.ref, r"^1-\d+$")
        detail = source.fetch_detail(http, offer)
        titles = [s["title"] for s in detail.sections]
        self.assertEqual(titles, ["Datos del puesto", "Documentos de la convocatoria"])
        self.assertIn("del 01/11/2026 al 20/11/2026", detail.sections[0]["html"])
        self.assertIn("bases-especificas/", detail.sections[1]["html"])

    def test_inscripcion_vencida_o_sin_empezar_no_es_oferta(self):
        self.assertEqual(self.offers(self.open_first(end="2026-11-06T23:59:59"))[2], [])
        self.assertEqual(self.offers(self.open_first(start="2026-11-08"))[2], [])

    def test_fecha_con_formato_desconocido_no_se_interpreta(self):
        with self.assertRaises(SourceLayoutError):
            self.offers(self.open_first(end="el 20 de noviembre"))

    def test_respuesta_que_no_es_json_no_pasa_por_vacia(self):
        class Broken:
            def get(self, url):
                return "<html>Mantenimiento</html>"
        with self.assertRaises(SourceLayoutError):
            rtve.RtveSource().list_offers(Broken())

    def test_puesto_sin_proceso_no_se_interpreta(self):
        def edit(data):
            del data[0]["puestos"][0]["proceso"]
        with self.assertRaises(SourceLayoutError):
            self.offers(edit)


if __name__ == "__main__":
    unittest.main()
