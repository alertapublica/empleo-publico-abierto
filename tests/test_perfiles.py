import unittest

from empleo import perfiles


class Referencia(unittest.TestCase):
    """Los casos revisados (empleo/perfiles_referencia.csv) tienen que seguir saliendo igual."""

    def test_casos_revisados(self):
        rows = perfiles.reference()
        self.assertGreater(len(rows), 100)
        wrong = [f"{r['fuente']} | {r['titulo']} | esperado {r['perfil']!r}, sale {perfiles.classify(r['titulo'], r['fuente'])!r}"
                 for r in rows if perfiles.classify(r["titulo"], r["fuente"]) != r["perfil"]]
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

    def test_en_formacion_solo_del_investigador(self):
        self.assertEqual(perfiles.classify("Personal investigador en formación"), "predoctoral")
        self.assertEqual(perfiles.classify("Personal investigador en formació"), "predoctoral")
        self.assertEqual(perfiles.classify("Técnico/a de laboratorio en formación"), "tecnico")

    def test_subcadenas_que_no_son_gestion(self):
        # «financiado» y «digestión» no son finanzas ni gestión
        self.assertEqual(perfiles.classify("Técnico/a de laboratorio para proyecto financiado por el ISCIII"), "tecnico")
        self.assertEqual(perfiles.classify("Técnico/a de laboratorio en digestión anaerobia"), "tecnico")
        self.assertEqual(perfiles.classify("Técnico/a superior del área financiera"), "gestion")
        self.assertEqual(perfiles.classify("Head of Finance"), "gestion")
        self.assertEqual(perfiles.classify("Tècnic/a de gestió financera"), "gestion")
        self.assertEqual(perfiles.classify("Técnico/a financeiro"), "gestion")

    def test_ensayos_solo_los_clinicos(self):
        self.assertEqual(perfiles.classify("Técnico de laboratorio para ensayos de materiales"), "tecnico")
        self.assertEqual(perfiles.classify("Técnico/a de apoyo para la monitorización de reactores"), "tecnico")
        self.assertEqual(perfiles.classify("Coordinador/a de ensayos clínicos"), "ensayos")
        self.assertEqual(perfiles.classify("Monitor/a de ensayos"), "ensayos")
        self.assertEqual(perfiles.classify("Monitores/as de ensayos"), "ensayos")
        self.assertEqual(perfiles.classify("Clinical Research Monitors"), "ensayos")
        self.assertEqual(perfiles.classify("Coordinador/a de ensayos fase I/II"), "ensayos")

    def test_el_arranque_de_tecnico_manda(self):
        # El complemento («para la gestión de…», «al investigador») no cambia el puesto
        self.assertEqual(perfiles.classify("Técnico/a de laboratorio para la gestión de muestras del biobanco"), "tecnico")
        self.assertEqual(perfiles.classify("Técnico/a de apoyo al investigador principal"), "tecnico")
        self.assertEqual(perfiles.classify("Tècnic/a de suport a la recerca"), "tecnico")
        # …pero el técnico de gestión sigue siendo de gestión
        for title in ("Técnico/a de apoyo a la gestión de proyectos", "Técnico/a de apoyo a gestión de proyectos",
                      "Técnico/a de apoyo en la gestión de proyectos", "Técnico/a de apoyo a la administración de proyectos",
                      "Tècnic/a de suport a la gestió de projectes"):
            self.assertEqual(perfiles.classify(title), "gestion", title)
        self.assertEqual(perfiles.classify("Técnico/a de gestión de la investigación"), "gestion")

    def test_en_los_contratos_de_proyecto_decide_la_categoria(self):
        title = ("Personal tecnólogo superior para colaborar con la línea de investigación financiada "
                 "«Diseño de espacios de datos y gestión de datos abiertos»")
        self.assertEqual(perfiles.matches(title, "ua"), ["tecnico"])
        self.assertEqual(perfiles.classify("Personal especialista para colaborar con el proyecto «X»", "ua"), "tecnico")
        self.assertEqual(perfiles.classify("Técnico Superior · Gestión de plagas para el investigador", "ifapa"), "tecnico")
        # udc: «categoría · centro»; el colaborador de investigación es titulado sin doctorado
        self.assertEqual(perfiles.matches("Colaborador/a de Investigación a tempo completo · CITIC", "udc"), ["tecnico"])
        self.assertEqual(perfiles.classify("Investigador/a Contratado/a Doutor/a a tempo completo · CICA", "udc"),
                         "investigador")

    def test_investigador_en_formacion_no_es_dudoso(self):
        for title in ("Personal investigador en formación para colaborar con el proyecto «X»",
                      "Investigador/a Predoctoral para el grupo X"):
            self.assertEqual(perfiles.matches(title), ["predoctoral"], title)
        self.assertEqual(perfiles.matches("Investigador/a postdoctoral"), ["investigador"])

    def test_sin_perfil(self):
        self.assertEqual(perfiles.classify("Titulación Universitaria en Biología"), "")


class Informe(unittest.TestCase):
    def offer(self, title, source="irb"):
        return {"source": source, "title": title, "url": "https://x.example/1"}

    def test_avisa_de_las_dudosas_y_de_las_sin_perfil(self):
        text = perfiles.report([
            self.offer("Técnico/a de laboratorio para la gestión de muestras"),
            self.offer("Titulación Universitaria en Biología"),
            self.offer("Técnico/a de laboratorio"),  # una sola regla: no se avisa
        ], reviewed=set())
        self.assertIn("## Con más de un perfil posible (1)", text)
        self.assertIn("- `irb` [Técnico/a de laboratorio para la gestión de muestras](https://x.example/1)"
                      " → Técnico/a de laboratorio y apoyo (también casa: Gestión y administración)", text)
        self.assertIn("## Sin perfil (1)", text)
        self.assertNotIn("[Técnico/a de laboratorio](", text)

    def test_las_revisadas_no_salen(self):
        offers = [self.offer("Titulación Universitaria en Biología")]
        self.assertEqual(perfiles.report(offers, reviewed={("irb", "Titulación Universitaria en Biología")}), "")
        self.assertEqual(perfiles.report([self.offer("Research Assistant")], reviewed=set()), "")


if __name__ == "__main__":
    unittest.main()
