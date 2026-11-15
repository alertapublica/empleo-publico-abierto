import unittest

from empleo import perfiles


class Referencia(unittest.TestCase):
    """Los casos revisados (empleo/perfiles_referencia.csv) tienen que seguir saliendo igual."""

    def test_casos_revisados(self):
        rows = perfiles.reference()
        self.assertGreater(len(rows), 100)
        wrong = [f"{r['fuente']} | {r['titulo']} | esperado {r['perfil']!r}, sale {perfiles.classify(r['titulo'])!r}"
                 for r in rows if perfiles.classify(r["titulo"]) != r["perfil"]]
        self.assertFalse(wrong, "\n" + "\n".join(wrong))

    def test_solo_perfiles_conocidos(self):
        for row in perfiles.reference():
            self.assertIn(row["perfil"], {"", *perfiles.NAMES}, row["titulo"])


class Reglas(unittest.TestCase):
    def test_predoctoral_no_es_postdoctoral(self):
        self.assertEqual(perfiles.classify("Investigador/a Predoctoral para el grupo X"), "predoctoral")
        self.assertEqual(perfiles.classify("Investigador/a posdoctoral para el grupo X"), "investigador")

    def test_niveles_con_cifra(self):
        # R1–R4 llevan cifra: la normalización de áreas las quitaría
        self.assertEqual(perfiles.classify("PhD Call 2026. 5 R1 positions"), "predoctoral")
        self.assertEqual(perfiles.classify("Personal investigador líder (R4)"), "investigador")

    def test_enfermedades_no_es_enfermeria(self):
        self.assertEqual(perfiles.classify("Técnico de apoyo a la investigación en enfermedades raras"), "tecnico")
        self.assertEqual(perfiles.classify("Enfermero/a de investigación"), "sanitario")

    def test_gestor_de_datos_no_es_gestion(self):
        self.assertEqual(perfiles.classify("Gestor/a de datos"), "datos")
        self.assertEqual(perfiles.classify("Técnico/a de gestión de la investigación"), "gestion")

    def test_sin_perfil(self):
        self.assertEqual(perfiles.classify("Titulación Universitaria en Biología"), "")


if __name__ == "__main__":
    unittest.main()
