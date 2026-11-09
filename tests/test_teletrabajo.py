import unittest

from empleo import teletrabajo

RELLENO = "<p>" + " ".join(["Funciones de apoyo técnico al equipo del proyecto."] * 12) + "</p>"


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


if __name__ == "__main__":
    unittest.main()
