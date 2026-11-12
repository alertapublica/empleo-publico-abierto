import io
import json
import sys
import tempfile
import unittest
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest import mock

from empleo import entidades
from empleo.sources import ACTIVE
from empleo.text import slug


class Tabla(unittest.TestCase):
    def setUp(self):
        self.data = json.loads(entidades.TABLE.read_text(encoding="utf-8"))
        self.ids = [e["id"] for e in self.data["entidades"]]

    def test_cada_fuente_es_una_entidad_con_su_mismo_id(self):
        self.assertTrue({s.id for s in ACTIVE} <= set(self.ids))

    def test_ids_unicos(self):
        self.assertEqual(len(self.ids), len(set(self.ids)))

    def test_un_alias_no_nombra_a_dos_entidades(self):
        names = Counter(slug(n) for e in self.data["entidades"] for n in {e["nombre"], *e["alias"]})
        self.assertEqual([n for n, c in names.items() if c > 1], [])

    def test_las_coberturas_son_de_fuentes(self):
        rules = {k: v for k, v in self.data["coberturas"].items() if not k.startswith("_")}
        self.assertTrue(set(rules) <= {s.id for s in ACTIVE})


class Convocante(unittest.TestCase):
    def test_por_defecto_el_organismo_de_la_fuente(self):
        self.assertEqual(entidades.convocante({"company": "CNIC"}, "cnic", "ofertas"), "cnic")

    def test_por_empresa(self):
        self.assertEqual(entidades.convocante({"company": "Tragsatec"}, "tragsa", "ofertas"), "tragsatec")
        self.assertEqual(entidades.convocante({"company": "Grupo Tragsa"}, "tragsa", "ofertas"), "tragsa")
        self.assertEqual(entidades.convocante({"company": "SADIM"}, "hunosa", "ofertas"), "sadim")
        self.assertIsNone(entidades.convocante({"company": "Otra"}, "tragsa", "ofertas"))  # no se adivina

    def test_procesos_de_puertos_por_autoridad(self):
        self.assertEqual(entidades.convocante({"location": "Bahía de Algeciras"}, "puertos", "procesos"),
                         "ap-bahia-de-algeciras")
        self.assertEqual(entidades.convocante({"location": "Barcelona"}, "puertos", "procesos"), "apb")
        self.assertEqual(entidades.convocante({"company": "Puertos del Estado"}, "puertos", "ofertas"), "puertos")


PUERTOS_BCN = "Técnico/a de Promoción y Comunicación de Mercado (Autoridad Portuaria: Barcelona)"


def _escribe(data: Path, source: str, name: str, value: dict) -> None:
    (data / source).mkdir(exist_ok=True)
    (data / source / name).write_text(json.dumps(value), encoding="utf-8")


class Informe(unittest.TestCase):
    def test_la_misma_convocatoria_en_puertos_y_en_el_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            _escribe(data, "puertos", "announcements.json", {"puertos:1": {
                "process": PUERTOS_BCN, "location": "Barcelona", "state": "curso"}})
            _escribe(data, "apb", "offers.json", {"apb:x": {
                "title": "Técnico/a de promoción y comunicación de mercado", "status": "open"}})
            text = entidades.report(data)
        self.assertIn("- puertos: apb 1", text)
        self.assertIn("- apb: apb (oferta, open)", text)
        self.assertIn("puertos (proceso, curso)", text)

    def test_tambien_los_duplicados_del_historico(self):
        # El caso real: Puertos lo guardó antes de existir la fuente del Port; los dos ya terminados.
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            _escribe(data, "puertos", "announcements.json", {"puertos:1": {
                "process": PUERTOS_BCN, "location": "Barcelona", "state": "retirado"}})
            _escribe(data, "apb", "announcements.json", {"apb:1": {
                "process": "Técnico/a de promoción y comunicación de mercado", "state": "finalizado"}})
            text = entidades.report(data)
        self.assertNotIn("- puertos: apb", text)  # el recuento por fuente sigue siendo de lo vivo
        self.assertIn("apb (proceso, finalizado)", text)
        self.assertIn("puertos (proceso, retirado)", text)

    def test_los_comunicados_de_un_proceso_son_una_aparicion_con_su_enlace(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            url = "https://seleccio.portdebarcelona.cat/es/web/seleccio/tecnic"
            _escribe(data, "apb", "announcements.json", {
                "apb:1": {"process": "Técnico/a de promoción y comunicación de mercado", "state": "curso",
                          "process_url": url},
                "apb:2": {"process": "Técnico/a de promoción y comunicación de mercado", "state": "finalizado",
                          "process_url": url}})
            _escribe(data, "puertos", "announcements.json", {"puertos:1": {
                "process": PUERTOS_BCN, "location": "Barcelona", "state": "retirado"}})
            (who, items), = entidades.duplicates(entidades._records(data))
            text = entidades.report(data)
        self.assertEqual((who, [i["source"] for i in items]), ("apb", ["apb", "puertos"]))
        self.assertIn(f"apb (proceso, curso/finalizado): [Técnico/a de promoción y comunicación de mercado]({url})",
                      text)
        self.assertIn(f"puertos (proceso, retirado): {PUERTOS_BCN}", text)  # sin enlace guardado, sin corchetes

    def test_el_mismo_titulo_en_una_sola_fuente_no_es_duplicado(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            _escribe(data, "cnic", "offers.json", {
                "cnic:1": {"title": "Técnico de laboratorio", "status": "closed"},
                "cnic:2": {"title": "Técnico de laboratorio", "status": "open"}})
            self.assertIn("Ninguno.", entidades.report(data))

    def test_anota_el_aviso_en_actions_si_hay_duplicados(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            _escribe(data, "puertos", "announcements.json", {"puertos:1": {
                "process": PUERTOS_BCN, "location": "Barcelona", "state": "retirado"}})
            _escribe(data, "apb", "offers.json", {"apb:x": {
                "title": "Técnico/a de promoción y comunicación de mercado", "status": "closed"}})
            out, err = io.StringIO(), io.StringIO()
            with mock.patch.object(sys, "argv", ["entidades", "informe", tmp]), \
                    redirect_stdout(out), redirect_stderr(err):
                entidades.main()
        self.assertIn("::warning title=Duplicados entre fuentes::1 convocatoria(s)", err.getvalue())
        self.assertNotIn("::warning", out.getvalue())  # no se cuela en el resumen

    def test_sin_duplicados_no_anota_nada(self):
        with tempfile.TemporaryDirectory() as tmp:
            err = io.StringIO()
            with mock.patch.object(sys, "argv", ["entidades", "informe", tmp]), \
                    redirect_stdout(io.StringIO()), redirect_stderr(err):
                entidades.main()
        self.assertEqual(err.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
