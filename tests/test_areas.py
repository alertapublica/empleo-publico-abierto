import unittest

from empleo import areas, site
from empleo.model import GROUPS
from empleo.sources import ACTIVE

GROUP_OF = {s.id: s.group for s in ACTIVE}


def offer(title, source="tragsa", **extra):
    return {"id": f"{source}:{title}", "source": source, "title": title, "url": "https://x.example/o",
            "status": "open", **extra}


class Referencia(unittest.TestCase):
    """Los casos revisados (empleo/areas_referencia.csv) tienen que seguir saliendo igual."""

    def test_casos_revisados(self):
        rows = areas.reference()
        self.assertGreater(len(rows), 300)
        wrong = []
        for row in rows:
            got, _ = areas.classify(row["titulo"], row["ficha"], row["fuente"], GROUP_OF.get(row["fuente"], ""))
            if set(got) != set(row["areas"].split()):
                wrong.append(f"{row['fuente'] or '-'} | {row['titulo']} | esperado {row['areas']!r}, sale {' '.join(got)!r}")
        self.assertFalse(wrong, "\n" + "\n".join(wrong))

    def test_solo_areas_conocidas(self):
        for row in areas.reference():
            self.assertLessEqual(set(row["areas"].split()), set(areas.AREAS), row["titulo"])


class Reglas(unittest.TestCase):
    def test_ambitos_de_fuente_validos(self):
        ids = {s.id for s in ACTIVE}
        self.assertLessEqual(set(areas.SOURCE_AREAS), ids)
        self.assertLessEqual(set(areas.SOURCE_AREAS.values()) | set(areas.GROUP_AREAS.values()), set(areas.AREAS))
        self.assertLessEqual(set(areas.GROUP_AREAS), set(GROUPS))

    def test_defensa_judicial_no_es_defensa_militar(self):
        # Tragsa 58747
        title = ("Especialista en representación y defensa de procedimientos judiciales civiles, penales, "
                 "mercantiles y laborales Gerencia de Asuntos Contenciosos (TRAGSA)")
        self.assertEqual(areas.classify(title)[0], ["juridico"])
        self.assertIn("aeroespacial", areas.classify("Técnico/a de sistemas de defensa")[0])

    def test_resultado_estable_a_igualdad_de_puntos(self):
        # Sin orden fijo en los empates, el orden variaría entre ejecuciones.
        self.assertEqual(areas.classify("Ingeniero/a o Graduado/a + Máster de Montes - Obras")[0], ["ambiente", "obras"])

    def test_el_ambito_de_la_fuente_desempata_pero_no_basta_si_el_titulo_dice_otra_cosa(self):
        self.assertEqual(areas.classify("Técnico/a de Recursos Humanos", source="senasa"), (["personas"], "título"))
        self.assertEqual(areas.classify("Personal técnico especialista", source="senasa"), (["aeroespacial"], "fuente"))
        self.assertEqual(areas.classify("Personal técnico especialista", group="investigacion"), (["investigacion"], "fuente"))
        self.assertEqual(areas.classify("Personal técnico especialista"), ([], ""))

    def test_la_ficha_solo_si_el_titulo_no_basta(self):
        ficha = "Funciones: seguimiento de la biodiversidad en espacios naturales e inventarios forestales."
        self.assertEqual(areas.classify("Titulado/a universitario/a", ficha), (["ambiente"], "ficha"))
        self.assertEqual(areas.classify("Programador/a PHP", ficha), (["tic"], "título"))

    def test_proceso_de_muchos_puestos_sin_area(self):
        ficha = "Correcciones en los bloques de incendios, embarcaciones y saneamiento ganadero."
        self.assertEqual(areas.classify("Tasa de reposición específica 2026 Grupo Tragsa", ficha), ([], ""))

    def test_presentacion_fija_de_la_empresa_no_cuenta(self):
        ficha = ("Tragsatec, empresa especializada en la realización de actividades de ingeniería, consultoría "
                 "y asistencia técnica en materias agrícolas, ganadería, forestal y medioambiental, busca...")
        self.assertEqual(areas.classify("Titulados/as Universitarios/as", ficha), ([], ""))

    def test_texto_de_la_ficha(self):
        o = {"sections": [{"title": "Funciones", "html": "<p>Gestión &amp; <b>control</b></p>"}]}
        self.assertEqual(areas.ficha_text(o), "Funciones Gestión & control")


class Informe(unittest.TestCase):
    def test_lista_sin_area_y_area_de_fuente_y_omite_lo_revisado(self):
        offers = [
            offer("Analista Senior", "fnmt"),
            offer("Personal técnico especialista", "senasa"),
            offer("Programador/a PHP"),
            offer("Tasa de reposición específica 2026 Grupo Tragsa"),
            offer("Ya revisada", "fnmt"),
        ]
        text = areas.report(offers, GROUP_OF, reviewed={("fnmt", "Ya revisada")})
        self.assertIn("## Sin área (1)", text)
        self.assertIn("`fnmt` [Analista Senior](https://x.example/o)", text)
        self.assertIn("## Con el área de la fuente (1)", text)
        self.assertIn("Personal técnico especialista](https://x.example/o) → Aeronáutica, espacio y defensa", text)
        for absent in ("Programador", "Tasa de reposición", "Ya revisada"):
            self.assertNotIn(absent, text)

    def test_vacio_si_no_queda_nada(self):
        self.assertEqual(areas.report([offer("Programador/a PHP")], GROUP_OF, reviewed=set()), "")

    def test_las_abiertas_de_los_datos_revisadas_o_en_el_informe(self):
        # El informe se apoya en la referencia: comprueba que se puede leer entera.
        reviewed = {(row["fuente"], row["titulo"]) for row in areas.reference()}
        self.assertIn(("tragsa", "Programador/a - PHP (Santiago de Compostela)"), reviewed)


class Portada(unittest.TestCase):
    def test_opciones_por_nombre_y_sin_area_al_final(self):
        html = site.area_options(
            [offer("Programador/a PHP"), offer("Ingeniero/a de Montes"), offer("Sin pistas")], {})
        self.assertEqual(html, '<option value="tic">Informática y telecomunicaciones</option>'
                               '<option value="ambiente">Medio ambiente, agro y pesca</option>'
                               '<option value="ninguna">Sin área</option>')

    def test_tarjeta_con_sus_areas(self):
        card = site.offer_card(offer("Administrativo/a - Departamento de Personas", deadline=None, ref="1",
                                     first_seen="2026-11-07T00:00:00+00:00"), site.date(2026, 11, 7))
        self.assertIn('data-area="admin personas"', card)
