import json
import tempfile
import unittest
from collections import Counter
from pathlib import Path

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


class Informe(unittest.TestCase):
    def test_la_misma_convocatoria_en_puertos_y_en_el_port(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)
            (data / "puertos").mkdir()
            (data / "apb").mkdir()
            (data / "puertos" / "announcements.json").write_text(json.dumps({"puertos:1": {
                "process": "Técnico/a de Promoción y Comunicación de Mercado (Autoridad Portuaria: Barcelona)",
                "location": "Barcelona", "state": "curso"}}), encoding="utf-8")
            (data / "apb" / "offers.json").write_text(json.dumps({"apb:x": {
                "title": "Técnico/a de promoción y comunicación de mercado", "status": "open"}}), encoding="utf-8")
            text = entidades.report(data)
        self.assertIn("- puertos: apb 1", text)
        self.assertIn("- apb: apb (oferta)", text)
        self.assertIn("puertos (proceso)", text)


if __name__ == "__main__":
    unittest.main()
