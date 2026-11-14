import unittest

from empleo import teletrabajo

RELLENO = ("<p>" + " ".join(["Funciones de apoyo técnico al equipo del proyecto."] * 12)
           + " Contrato temporal a jornada completa.</p>")


def ficha(*html):
    return {"sections": [{"title": "Condiciones", "level": 2, "html": h} for h in html]}


class Teletrabajo(unittest.TestCase):
    def test_frases_reales_de_las_fuentes(self):
        casos = {
            "<ul><li>- Posibilidad de hasta un 50% de la jornada de trabajo a distancia por ahorro energético"
            " a determinar por la empresa.</li><li>Jornada de 37,5 horas.</li></ul>":
                "Posibilidad de hasta un 50% de la jornada de trabajo a distancia por ahorro energético"
                " a determinar por la empresa.",
            "<p>Possibility to work some days in remote -Teleworking<br>26 working days of holiday</p>":
                "Possibility to work some days in remote -Teleworking",
            "<p>Possibilitat de teletreball 1 dia a la setmana.</p>": "Possibilitat de teletreball 1 dia a la setmana.",
        }
        for html, frase in casos.items():
            self.assertEqual(teletrabajo.mention(ficha(html, RELLENO)), frase)

    def test_palabras_sueltas_no_bastan(self):
        for html in (
            "<p>Experiencia en administración de plataformas SAP sobre entornos cloud o híbridos.</p>",
            "<p>Soporte en remoto y atención presencial a usuarios.</p>",
            "<p>Disponibilidad para trabajar presencialmente en la Comunidad de Madrid.</p>",
        ):
            self.assertIs(teletrabajo.mention(ficha(html, RELLENO)), False, html)

    def test_si_lo_niega_no_cuenta(self):
        self.assertIs(teletrabajo.mention(ficha("<p>Puesto sin posibilidad de teletrabajo.</p>", RELLENO)), False)
        frase = teletrabajo.mention(ficha("<p>No hay guardias.</p><p>Se permite el teletrabajo dos días.</p>", RELLENO))
        self.assertEqual(frase, "Se permite el teletrabajo dos días.")

    def test_sin_texto_no_se_sabe(self):
        self.assertIsNone(teletrabajo.mention({"sections": []}))
        self.assertIsNone(teletrabajo.mention(ficha('<a href="b.pdf">Bases de la convocatoria (PDF)</a>')))

    def test_frase_larga_recortada_alrededor_de_la_mencion(self):
        larga = " ".join(["Requisito adicional del puesto"] * 20) + " con teletrabajo parcial " + " ".join(["y otra cosa"] * 30)
        frase = teletrabajo.mention(ficha(f"<p>{larga}</p>"))
        self.assertIn("teletrabajo parcial", frase)
        self.assertTrue(frase.startswith("…") and frase.endswith("…"))
        self.assertLessEqual(len(frase), teletrabajo.MAX_CHARS + 30)

    def test_cuanto_solo_si_la_frase_lo_dice(self):
        casos = {
            "Posibilidad de hasta un 50% de la jornada de trabajo a distancia por ahorro energético a determinar"
            " por la empresa.": "hasta el 50 %",
            "Posibilidad de trabajo a distancia por ahorro energético a determinar por la empresa de hasta el 50%.":
                "hasta el 50 %",
            "Posibilidad de trabajo a distancia por ahorro energético a determinar por la empresa.": None,
            "Possibility to work some days in remote -Teleworking": "algunos días",
            "Possibilitat de teletreball 1 dia a la setmana.": "1 día a la semana",
            "Teletrabajo dos días a la semana.": "2 días a la semana",
            "Jornada laboral completa de 39 h. en horario de invierno, con flexibilidad horaria y posibilidad"
            " de teletrabajo.": None,
            # Una cifra lejos de la mención habla de otra cosa.
            "Porcentaje de viaje de hasta el 25% de la jornada laboral, en proyectos repartidos por toda la provincia"
            " y con desplazamientos frecuentes a las oficinas comarcales; posibilidad de teletrabajo.": None,
        }
        for frase, cuanto in casos.items():
            leido = teletrabajo.read(ficha(f"<p>{frase}</p>", RELLENO))
            self.assertEqual((leido.state, leido.detail), ("menciona", cuanto), frase)

    def test_sin_teletrabajo_solo_si_la_ficha_lo_dice(self):
        for frase in ("IMDEA Energía, Móstoles, Madrid. 100% presencial", "Puesto sin posibilidad de teletrabajo."):
            leido = teletrabajo.read(ficha(f"<p>{frase}</p>", RELLENO))
            self.assertEqual((leido.state, leido.phrase), ("sin", frase))
        for frase in (
            "Curso de Prevención de Riesgos Laborales 100% presencial.",
            "Disponibilidad para trabajar presencialmente en la Comunidad de Madrid.",  # no excluye lo híbrido
            "Posibilidad de oficina remota en otras oficinas de Tragsatec de Galicia.",  # otra sede, no su casa
            "Flexibilidad horaria.",  # el silencio no es un «no»
        ):
            self.assertEqual(teletrabajo.read(ficha(f"<p>{frase}</p>", RELLENO)).state, "no_menciona", frase)

    def test_no_consta_si_la_ficha_no_recoge_las_condiciones(self):
        instrucciones = "<p>" + " ".join(["Lea la convocatoria antes de iniciar la inscripción."] * 20) + "</p>"
        self.assertEqual(teletrabajo.read(ficha(instrucciones)).state, "no_consta")
        self.assertIsNone(teletrabajo.mention(ficha(instrucciones)))
        # Los apartados que solo enlazan documentos no cuentan como descripción del puesto.
        enlaces = {"sections": [{"title": "Convocatoria", "level": 2, "html": "<p>Convocatoria de un puesto de técnico.</p>"},
                                {"title": "Documentos de la convocatoria", "level": 2, "html": RELLENO}]}
        self.assertEqual(teletrabajo.read(enlaces).state, "no_consta")
        # Pero una mención en ellos sí se lee.
        enlaces["sections"][1]["html"] += "<p>Anexo: acuerdo de teletrabajo.</p>"
        self.assertEqual(teletrabajo.read(enlaces).state, "menciona")


if __name__ == "__main__":
    unittest.main()
