import unittest

from empleo import titulaciones as T
from empleo.sources import ACTIVE
from empleo.sources.ciber import CiberSource
from empleo.sources.ineco import InecoSource
from empleo.sources.tragsa import TragsaSource

H = " (titulación homologada en España o certificado de equivalencia emitido por la Secretaría General de Universidades)"


def vias(texto):
    """«grado+master@3 | titulo_superior@3»: las vías leídas, con su MECES."""
    req = T.lee(texto)
    return " | ".join("+".join(via.tipos) + ("@" + "".join(map(str, via.meces)) if via.meces else "") for via in req.vias)


class Vias(unittest.TestCase):
    """Frases reales del apartado «Titulación» de Tragsa y «Titulación requerida» de CIBER."""

    def test_el_master_se_suma_al_grado_y_la_licenciatura_va_aparte(self):
        casos = {
            "Poseer la titulación de Licenciatura o Grado + Máster Oficial en Derecho (nivel 3 MECES)" + H:
                "titulo_superior@3 | grado+master@3",
            "Posees la titulación Universitaria (Nivel Meces 3) de Licenciatura en Derecho o Grado+Máster Oficial en Derecho" + H:
                "titulo_superior@3 | grado+master@3",
            "Posees la titulación de Ingeniería o Grado y Máster Universitario en Ingeniería de Montes o Ingeniería Agrónoma (MECES 3)" + H:
                "titulo_superior@3 | grado+master@3",
            "Posees la titulación de Graduado/a + Máster universitario/a oficial o Licenciado/a (Nivel MECES 3)" + H:
                "grado+master@3 | titulo_superior@3",
            "Licenciatura en Comunicación o Grado en Comunicación + Master universitario (Meces 3)":
                "titulo_superior@3 | grado+master@3",
        }
        for texto, esperado in casos.items():
            self.assertEqual(vias(texto), esperado, texto)
            self.assertEqual(T.lee(texto).parcial, (), texto)

    def test_el_master_se_suma_a_los_titulos_de_primer_ciclo_seguidos(self):
        casos = {
            "Poseer la titulación de Ingeniería de Caminos, Canales y Puertos, o Ingeniería Técnica de Obras Públicas/Grado en"
            " Ingeniería Civil + Máster Oficial en Ingeniería de Caminos, Canales y Puertos (nivel MECES 3)" + H:
                "titulo_superior@3 | titulo_medio+master@3 | grado+master@3",
            "Poseer la titulación de Licenciatura, Ingeniería, Arquitectura o Grado/Diplomatura + Máster Oficial (nivel 3 MECES)" + H:
                "titulo_superior@3 | grado+master@3 | titulo_medio+master@3",
            "Ingeniería o, Arquitectura técnica o Ingeniería Técnica o Grado + Máster Oficial, (nivel 3 MECES)" + H:
                "titulo_superior@3 | titulo_medio+master@3 | grado+master@3",
        }
        for texto, esperado in casos.items():
            self.assertEqual(vias(texto), esperado, texto)

    def test_grado_o_grado_mas_master_deja_el_primero_solo(self):
        # (un «2 o 3» de todo el grupo no dice qué nivel es de cada vía: no se reparte)
        self.assertEqual(
            vias("Posees la titulación de Licenciatura o Diplomatura o Grado o Grado + Máster (nivel 2 MECES o 3 MECES) en"
                 " Administración y Dirección de Empresas" + H),
            "titulo_superior | titulo_medio | grado | grado+master")
        self.assertEqual(
            vias("Disponer de la titulación de Ingeniería, Ingeniería Técnica, Arquitectura, Arquitectura Técnica, Grado o Grado +"
                 " Máster Oficial en ramas de la Ingeniería y/o Arquitectura (Nivel 2 o 3 MECES)" + H),
            "titulo_superior | titulo_medio | grado | grado+master")

    def test_cada_marca_de_meces_cierra_su_grupo(self):
        self.assertEqual(
            vias("Poseer la titulación de Licenciatura o Grado + Máster Oficial en Biología, Ciencias Ambientales o Ciencias del Mar"
                 " (nivel 3 MECES); o Grado en Biología, Ciencias Ambientales o Ciencias del Mar (nivel MECES 2)" + H),
            "titulo_superior@3 | grado+master@3 | grado@2")
        self.assertEqual(
            vias("Poseer la titulación de Arquitectura (nivel MECES 3) o Grado en Arquitectura (nivel MECES 3) o Grado + Máster"
                 " Oficial en Arquitectura" + H),
            "titulo_superior@3 | grado@3 | grado+master")

    def test_ingenieria_es_titulo_en_la_enumeracion_y_especialidad_tras_en(self):
        casos = {
            "Poseer la titulación de Ingeniería Técnica o Grado en Ingeniería (nivel 2 MECES)" + H: "titulo_medio@2 | grado@2",
            "Poseer la titulación de Ingeniería Técnica, Diplomatura o Grado Universitario en Geografía, Ciencias Ambientales,"
            " Ingeniería Agrícola, Ingeniería Forestal o Ingeniería Topográfica (Nivel 2 MECES)" + H: "titulo_medio@2 | grado@2",
            "Ingeniería o Grado + Máster Habilitante (nivel 3 MECES)" + H + " en:\n- Ingeniería de Montes\n- Ingeniería Agrónoma":
                "titulo_superior@3 | grado+master@3",
            "Posees alguna de las siguientes titulaciones (nivel 2 o 3 MECES)" + H + ":\n- Arquitectura / Arquitectura Técnica /"
            " Grado en Arquitectura\n- Ingeniería Técnica / Ingeniería Superior": "titulo_superior | titulo_medio | grado",
            "(Licenciatura/Ingeniería o Grado+Máster universitario MECES 3) en Ingeniería Informática o de Telecomunicaciones.":
                "titulo_superior@3 | grado+master@3",
        }
        for texto, esperado in casos.items():
            self.assertEqual(vias(texto), esperado, texto)
            self.assertEqual(T.lee(texto).parcial, (), texto)

    def test_un_rotulo_generico_no_es_una_via(self):
        self.assertEqual(vias("Titulación superior: Licenciatura o Grado+Master universitario Meces 3) en biotecnología"),
                         "titulo_superior@3 | grado+master@3")
        self.assertEqual(vias("Disponer de la titulación universitaria oficial de Ingeniería Industrial o Grado del campo de estudio de"
                              " ingeniería industrial + Máster Universitario en Ingeniería Industrial (Máster habilitante) (nivel 3 MECES)"),
                         "titulo_superior@3 | grado+master@3")
        self.assertEqual(vias("Titulación Superior (MECES-3) en Biomedicina"), "titulo_superior@3")

    def test_fp_bachillerato_eso_y_experiencia(self):
        casos = {
            "Poseer la titulación de FP II o Ciclo Formativo de Grado Superior" + H + " en la rama administrativa o experiencia previa"
            " (con contrato laboral o académica) demostrable como administrativo/a (al menos 6 meses de experiencia).":
                "fp_superior | experiencia",
            "Bachiller (BUP/COU), FP I o CFGM, FP II o CFGS" + H + " o 6 meses de experiencia (con contrato laboral, académica o ambas)":
                "bachillerato | fp_medio | fp_superior | experiencia",
            "Poseer la titulación oficial de FPGB, FPI o CFGM o FP II o CFGS" + H + " o conocimientos apropiados a los cometidos"
            " desempeñados.": "fp_basica | fp_medio | fp_superior | experiencia",
            "Posees la titulación de Graduado en ESO o EGB/Graduado Escolar o BUP/COU o Bachillerato.": "eso | bachillerato",
        }
        for texto, esperado in casos.items():
            self.assertEqual(vias(texto), esperado, texto)
            self.assertEqual(T.lee(texto).parcial, (), texto)

    def test_la_experiencia_solo_es_via_si_hay_titulo_delante(self):
        texto = ("Posees la titulación de Titulación o conocimientos adquiridos en el desempeño de su profesión equivalentes a títulos"
                 " universitarios de primer ciclo (NIVEL 2 MECES), completada con una experiencia dilatada en su sector profesional")
        self.assertEqual(vias(texto), "")
        self.assertIn("sin título académico reconocido", T.lee(texto).parcial)

    def test_master_tras_especialidades_avisa(self):
        # «Diplomatura en X o Grado + Máster»: ¿la diplomatura va con máster? No se sabe; con barra, sí
        req = T.lee("Diplomatura en Biología o Grado + Máster Oficial en Biología (nivel 3 MECES)")
        self.assertIn("«+ Máster»: no se sabe a qué títulos se suma", req.parcial)
        self.assertEqual(T.lee("Ingeniería o Ingeniería técnica o Grado en Ingeniería + Máster Oficial (Nivel MECES 3)").parcial, ())

    def test_no_exigida_solo_si_lo_dice(self):
        self.assertEqual(T.lee("Titulación no exigida.")._asdict()["estado"], "no_exigida")
        self.assertEqual(T.lee("Grado en Derecho").estado, "consta")

    def test_ingenieria_tecnica_tras_grado_en_es_especialidad(self):
        self.assertEqual(vias("Licenciatura en Química o Grado en Ingeniería Técnica Agrícola y Agroalimentaria + Máster en Agrícola"
                              " o Agroalimentaria (nivel 3 MECES)"), "titulo_superior@3 | grado+master@3")
        self.assertEqual(vias("Grado en Edificación o Arquitectura Técnica (nivel 2 MECES)"), "grado@2 | titulo_medio@2")


class Parcial(unittest.TestCase):
    def parcial(self, texto):
        return " / ".join(T.lee(texto).parcial)

    def test_habilitaciones_y_formulas_sin_titulo(self):
        self.assertIn("sin título académico", self.parcial("Poseer la tarjeta profesional de Jefe/a de Máquinas de la Marina Mercante"))
        self.assertIn("titulacion", self.parcial("Posees la titulación de Técnico Superior en Transporte Marítimo" + H
                                                 + " o Titulación Oficial habilitante para el despacho de embarcaciones"))

    def test_experiencia_que_se_suma_al_titulo(self):
        self.assertIn("experiencia", self.parcial(
            "Poseer Diplomatura, Ingeniería Técnica, Arquitectura Técnica o Grado (nivel 2 MECES)" + H
            + " con al menos 2 años de experiencia académica y/o con contrato laboral en el sector pesquero."))

    def test_titulos_tras_la_experiencia(self):
        self.assertIn("títulos tras la experiencia", self.parcial(
            "Posees la titulación de Titulación o conocimientos adquiridos en el desempeño de su profesión equivalentes a títulos"
            " universitarios de primer ciclo o estudios universitarios de grado medio (NIVEL 2 MECES)"))

    def test_suma_que_no_es_con_master(self):
        self.assertIn("suma sin leer", self.parcial("Bachillerato (BUP/COU), Ciclo Formativo de Grado Medio (FPI) y Ciclo Formativo"
                                                    " de Grado Medio (FPII)"))

    def test_ingenieria_tras_o_sin_via_de_licenciatura(self):
        self.assertIn("título o especialidad", self.parcial(
            "Poseer la titulación de Grado /Ingeniería Técnica + Máster Oficial en Ingeniería de Caminos, Canales y Puertos o"
            " Ingeniería de Caminos, Canales y Puertos (MECES 3)"))

    def test_profesion_regulada_sin_desglosar(self):
        for texto in ("Posees la titulación que habilite a la profesión regulada de Ingeniero/a de Montes (nivel 3 MECES)",
                      "Posees la titulación que da acceso a la profesión regulada de Arquitecto/a o Arquitecto/a técnico/a (Nivel MECES 2 o 3)"):
            self.assertIn("habilita para una profesión", self.parcial(texto))
        self.assertEqual(self.parcial("Grado en Arquitectura que habilite para la profesión (nivel MECES 3)"), "")

    def test_condiciones_anadidas_y_negaciones(self):
        self.assertIn("plan de estudios", self.parcial("Grado en Ingeniería (que incluya en el plan de estudios al menos una materia"
                                                       " del ámbito de electricidad)"))
        self.assertIn("con la especialidad", self.parcial("Licenciatura o Grado en Medicina, con la especialidad de Medicina del"
                                                          " Trabajo (Nivel 3 MECES)"))
        self.assertIn("requisito negativo", self.parcial("No estar ya en posesión de un título de Doctorado, por ninguna universidad"))
        self.assertIn("minimo", self.parcial("Grado o Máster (mínimo MECES 2)"))

    def test_el_meces_escrito_tiene_que_casar(self):
        self.assertIn("MECES 3 en una vía sin máster", self.parcial("Grado en Biología (nivel 3 MECES)"))
        self.assertIn("MECES 2 en una vía de máster", self.parcial("Licenciatura en Biología (nivel 2 MECES)"))
        self.assertEqual(self.parcial("Licenciatura o Grado en Veterinaria (nivel 3 MECES)"), "")
        self.assertEqual(self.parcial("Arquitectura (nivel MECES 3) o Grado en Arquitectura que habilite para la profesión (nivel MECES 3)"), "")


class Vocabulario(unittest.TestCase):
    def test_especialidades_por_familia_del_titulo(self):
        self.assertEqual(T.lee("FP II o CFGS en especialidad agraria o edificación y obra civil o electricidad y electrónica").titulaciones,
                         ("fp-agraria", "fp-edificacion", "fp-electricidad"))
        self.assertEqual(T.lee("Grado en Ingeniería de la Edificación o Grado en Ingeniería Civil").titulaciones,
                         ("arquitectura_tecnica", "caminos"))
        self.assertEqual(T.lee("Bachiller o experiencia de al menos 1 año en Electricidad y Electrónica").titulaciones, ())

    def test_el_titulo_nombra_la_titulacion_salvo_en_la_formula_general(self):
        self.assertEqual(T.lee("Titulación que da acceso a la profesión regulada de Arquitecto/a o Arquitecto/a técnico/a").titulaciones,
                         ("arquitectura", "arquitectura_tecnica"))
        self.assertEqual(T.lee("Licenciatura, Ingeniería, Arquitectura o Grado + Máster Oficial (nivel 3 MECES)").titulaciones, ())

    def test_lo_que_no_esta_en_la_lista_queda_sin_clave(self):
        req = T.lee("Diplomatura o Grado en Derecho, Gestión y Administración Pública o Turismo (nivel 2 MECES)")
        self.assertEqual(req.titulaciones, ("derecho", "turismo"))
        self.assertEqual(req.sin_clave, ("gestion y administracion publica",))
        self.assertEqual(req.parcial, ())

    def test_sin_clave_solo_nombres_de_especialidad(self):
        # el resto de un título ya reconocido pierde la conjunción; las condiciones y oraciones de relativo no cuentan
        self.assertEqual(T.lee("Licenciatura o Grado + Máster Universitario en Arqueología o en Geografía e Historia (MECES 3)").sin_clave,
                         ())  # un nombre con clave no deja restos («e Historia»)
        self.assertEqual(T.lee("Grado en Ingeniería (que incluya en el plan de estudios al menos una materia del ámbito de "
                               "electricidad, energía y/o instalaciones)").sin_clave, ())
        self.assertEqual(T.lee("FP II o CFGS en especializaciones que permitan el desarrollo del puesto de delineante de conformidad "
                               "con la normativa legal de aplicación al mismo (FPII/CFGS rama de Edificación y/o Obra civil)").sin_clave, ())

    def test_la_clave_empieza_el_nombre(self):
        # un nombre dentro de otro no lo menciona: dar menos antes que meter la oferta en un filtro que no le toca
        casos = {
            "Grado en Ingeniería Química Industrial": ("quimica",),
            "Grado + Máster en Bioinformática para las Ciencias de la Salud o Bioinformática y Bioestadística": ("informatica",),
            "Grado + Máster en Bioinformática y Análisis de Datos Biomédicos o Bioinformática y Biología Computacional":
                ("informatica", "biologia"),
            "Grado en Ingeniería de Tecnologías de Telecomunicación": ("teleco",),
            "Doble Grado en Derecho y ADE": ("economia", "derecho"),
            "Grado en Ciencias de la Actividad Física y del Deporte": ("deporte",),
            # (títulos oficiales del RUCT: el complemento con «de» o «en» sí nombra la disciplina; el adjetivo, no)
            "Grado en Ingeniería Electrónica de Telecomunicación": ("teleco",),
            "Máster Universitario en Cuidados de Enfermería Intensiva": ("enfermeria",),
            "Máster Universitario en Investigación en Ingeniería Industrial": ("industrial",),
            "Máster Universitario en Intervención Psicológica en Niños y Adolescentes": ("psicologia",),
            "Máster Universitario en Física Médica": ("fisica",),  # (física, no medicina)
            "Máster Universitario en Responsabilidad Civil": (),
            "Máster Universitario en Investigación en Educación Física y Salud": (),
            "Grado en Arquitectura Naval": ("naval",),
            "Máster Universitario en Arquitectura de Software": ("informatica",),
        }
        for texto, esperado in casos.items():
            self.assertEqual(T.lee(texto).titulaciones, esperado, texto)

    def test_alias_que_nombran_otro_titulo(self):
        for texto in ("Grado en Náutica y Transporte Marítimo", "Grado en Ciencias Jurídicas de las Administraciones Públicas",
                      "Grado en Ingeniería Geológica", "Grado en Ingeniería Biomédica",
                      "Grado en Gestión y Operaciones del Transporte Aéreo"):
            self.assertEqual(T.lee(texto).titulaciones, (), texto)
        self.assertEqual(T.lee("Máster en Sistemas del Transporte Aéreo").titulaciones, ("aeroespacial",))

    def test_otras_no_es_cualquiera(self):
        # «otras ingenierías», «otros estudios universitarios»: la lista sigue abierta, no admite cualquiera
        for texto in ("Grado en Derecho, Otras Ingenierías", "Grado en Derecho, otros estudios universitarios",
                      "Grado en Derecho, Otras Formaciones Universitarias"):
            self.assertEqual(T.lee(texto).titulaciones, ("derecho",), texto)
        self.assertEqual(T.lee("Grado en cualquier ingeniería").titulaciones, ("cualquier_ingenieria",))

    def test_ciclos_de_informatica(self):
        for texto in ("Formación Profesional - Sistemas y Redes", "Formación Profesional en Inteligencia Artificial y Big Data"):
            self.assertEqual(T.lee(texto).titulaciones, ("fp-informatica",), texto)

    def test_ingenieria_tras_un_rotulo_generico_con_en(self):
        req = T.lee("Titulación universitaria en Ingeniería Industrial o Grado en Ingeniería de Telecomunicación")
        self.assertEqual(req.titulaciones, ("industrial", "teleco"))
        # tras la marca MECES, «en Ingeniería …» sigue siendo la especialidad del título
        self.assertEqual(T.lee("Grado (nivel 2 MECES) en Ingeniería Forestal").vias, (T.Via(("grado",), (2,)),))

    def test_las_condiciones_no_nombran_especialidades(self):
        self.assertEqual(T.lee("Grado en Biología con al menos 2 años de experiencia en el sector agrario").titulaciones, ("biologia",))
        self.assertEqual(T.lee("Grado en Derecho, valorándose conocimientos de informática").titulaciones, ("derecho",))
        # (la condición acaba con su frase: lo que va entre paréntesis después sí cuenta)
        self.assertEqual(T.lee("FP II o CFGS, FP I o CFGM en especializaciones que permitan el desarrollo del puesto de delineante de"
                               " conformidad con la normativa legal de aplicación al mismo (rama de Edificación y/o Obra civil)").titulaciones,
                         ("fp-edificacion",))
        req = T.lee("Doctor/a en Psicologia Clínica o afines.")
        self.assertEqual((vias("Doctor/a en Psicologia Clínica o afines."), req.titulaciones, req.parcial),
                         ("doctorado", ("psicologia",), ("sin leer: afines",)))

    def test_claves_y_expresiones(self):
        self.assertFalse(set(T.TITULACIONES) & set(T.FP_FAMILIAS))
        for key, (_, langs) in {**T.TITULACIONES, **T.FP_FAMILIAS}.items():
            self.assertIn("es", langs, key)
        for tipo, _ in T.FRASES:
            self.assertIn((tipo or "grado").rstrip("*"), {**T.TIPOS, "ing_arq": ""}, tipo)


def seccion(titulo, nivel, html):
    return {"title": titulo, "level": nivel, "html": html}


class Fuentes(unittest.TestCase):
    def test_tragsa_lee_la_titulacion_de_los_requisitos_y_no_los_meritos(self):
        oferta = {"sections": [
            seccion("Requisitos Específicos", 2, ""), seccion("Formación", 3, ""),
            seccion("Titulación", 3, "<ul><li>Posees la titulación de Grado en Ciencias del Mar (nivel 2 MECES)</li></ul>"),
            seccion("Méritos (Valorables)", 2, ""), seccion("Formación", 3, ""),
            seccion("Formación Complementaria", 3, "<p>Máster en Oceanografía</p>"),
        ]}
        req = TragsaSource().titulacion(oferta)
        self.assertEqual(req.exigido, "Posees la titulación de Grado en Ciencias del Mar (nivel 2 MECES)")
        self.assertEqual(req.vias, (T.Via(("grado",), (2,)),))
        self.assertEqual(req.titulaciones, ("mar",))

    def test_tragsa_una_titulacion_fuera_de_los_requisitos_no_cuenta(self):
        oferta = {"sections": [seccion("Méritos (Valorables)", 2, ""), seccion("Titulación", 3, "<p>Máster en Derecho</p>")]}
        self.assertEqual(TragsaSource().titulacion(oferta), T.Requisito(T.NO_CONSTA, "sin_apartado"))
        self.assertEqual(TragsaSource().titulacion({"sections": []}), T.Requisito(T.NO_CONSTA, "sin_ficha"))

    def test_ciber(self):
        oferta = {"sections": [seccion("Titulación requerida", 2, "<p>Doctorado en Medicina</p>"),
                               seccion("Otros conocimientos", 2, "<p>Máster en Bioinformática</p>")]}
        req = CiberSource().titulacion(oferta)
        self.assertEqual((req.vias, req.titulaciones), ((T.Via(("doctorado",)),), ("medicina",)))

    def ineco(self, requisitos: str) -> T.Requisito:
        html = "<p>" + "<br/>".join(requisitos.split("\n")) + "</p>"
        return InecoSource().titulacion({"sections": [seccion("Funciones", 2, "<p>Obras</p>"), seccion("Requisitos", 2, html)]})

    def test_ineco_renglon_titulacion_hasta_el_siguiente_rotulo(self):
        req = self.ineco("Experiencia en: obra ferroviaria\nTitulación: Licenciatura en Biología, Licenciatura en Geología.\n"
                         "Programas: MS Word - Usuario")
        self.assertEqual(req.exigido, "Licenciatura en Biología, Licenciatura en Geología.")
        self.assertEqual(req.titulaciones, ("biologia", "geologia"))
        # en el mismo renglón que otro rótulo, o cortado por «//» o por «Programas:»
        self.assertEqual(self.ineco("- Años de experiencia: Más de 5 años. Titulación: Grado en Ingeniería Informática - Otros.").exigido,
                         "Grado en Ingeniería Informática - Otros.")
        self.assertEqual(self.ineco("Experiencia en: X // Titulación: Grado en Ingeniería Civil //").exigido, "Grado en Ingeniería Civil")
        self.assertEqual(self.ineco("Titulación: Grado en Ingeniería Mecánica  Programas: MS Word").exigido, "Grado en Ingeniería Mecánica")

    def test_ineco_lista_debajo_del_rotulo(self):
        # con otra viñeta que la del rótulo: es la lista; con la misma, otro requisito
        req = self.ineco("*Años de experiencia: 2\n*Titulación:\n- Ingeniería de Montes\n- Licenciatura en Ciencias Ambientales\n"
                         "*Programas:\n- MS Word")
        self.assertEqual(req.exigido, "Ingeniería de Montes\nLicenciatura en Ciencias Ambientales")
        self.assertEqual(self.ineco("- Titulación: Formación Profesional, Otros.\n- Se requieren más de 5 años de experiencia.").exigido,
                         "Formación Profesional, Otros.")
        self.assertEqual(self.ineco("Titulación:\nIngeniero de Caminos, Canales y Puertos.\nOffice").exigido,
                         "Ingeniero de Caminos, Canales y Puertos.")
        # renglón suelto sin viñeta tras el valor: no se sabe si sigue la lista
        self.assertEqual(self.ineco("Titulación: Ingeniería Informática\nFormación Profesional en Informática.").exigido,
                         "Ingeniería Informática")

    def test_ineco_rotulos_de_rama_del_formulario_no_nombran(self):
        req = self.ineco("Titulación: Aeronáutica - Master en Ingeniería,Otros estudios universitarios - Licenciatura en Derecho")
        self.assertEqual(req.exigido, "Aeronáutica - Master en Ingeniería,Otros estudios universitarios - Licenciatura en Derecho")  # literal
        self.assertEqual(req.titulaciones, ("derecho",))
        self.assertEqual(self.ineco("Titulación: Industria Ingeniería Industrial , Máster en Ingeniería Industrial").titulaciones,
                         ("industrial",))
        self.assertEqual(self.ineco("Titulación: Informática, Ingeniería Informática.").titulaciones, ("informatica",))
        # tras un título, la misma palabra es su especialidad
        self.assertEqual(self.ineco("Titulación: Grado en Ingeniería Civil, Telecomunicaciones.").titulaciones, ("caminos", "teleco"))

    def test_ineco_lo_valorable_y_otros_rotulos_no_son_exigido(self):
        self.assertEqual(self.ineco("Titulación: Grado en Ingeniería Civil. Valorable Máster en Informática").exigido,
                         "Grado en Ingeniería Civil.")
        self.assertEqual(self.ineco("Valorable formación: Grado en Informática"), T.Requisito(T.NO_CONSTA, "sin_apartado"))
        self.assertEqual(self.ineco("Titulación:\nProgramas: Máster en Informática"), T.Requisito(T.NO_CONSTA, "sin_apartado"))
        self.assertEqual(self.ineco("Titulación: Grado en Ingeniería Civil idiomas: Grado en Informática").exigido,
                         "Grado en Ingeniería Civil")
        self.assertEqual(self.ineco("*Titulación:\n- Grado en Derecho\n- Valorable Máster en Informática").exigido, "Grado en Derecho")

    def test_ineco_sin_rotulo(self):
        self.assertEqual(self.ineco("- Grado en Ingeniería Aeroespacial o Grado en Física\n- Al menos 1 año de experiencia").exigido,
                         "Grado en Ingeniería Aeroespacial o Grado en Física")
        self.assertEqual(self.ineco("- Titulación de Ingeniería Técnica Industrial, con especialización en Mecánica.").exigido,
                         "Titulación de Ingeniería Técnica Industrial, con especialización en Mecánica.")
        self.assertEqual(self.ineco("- Grado en Informática\n- Grado en Derecho").titulaciones, ("informatica", "derecho"))
        self.assertEqual(self.ineco("- Profesional con titulación universitaria de Licenciatura, Ingeniería Civil o disciplinas afines.")
                         .titulaciones, ("caminos",))
        self.assertEqual(self.ineco("- Experiencia en laboratorio\n- Acreditación nivel 2"), T.Requisito(T.NO_CONSTA, "sin_apartado"))
        self.assertEqual(self.ineco("*Titulación:\n- Titulación no exigida, valorable formación universitaria en Ingeniería Civil").estado,
                         T.NO_EXIGIDA)
        self.assertEqual(InecoSource().titulacion({"sections": []}), T.Requisito(T.NO_CONSTA, "sin_ficha"))

    def test_sin_lector_no_consta(self):
        sin_lector = [s for s in ACTIVE if s.id not in ("tragsa", "ciber", "ineco")]
        self.assertTrue(sin_lector)
        for source in sin_lector:
            self.assertIs(source.titulacion({"sections": [seccion("Titulación", 2, "<p>Grado en Derecho</p>")]}), T.SIN_LECTOR)


class Informe(unittest.TestCase):
    def test_resumen_parciales_y_sin_clave(self):
        ofertas = [({"id": "x:1", "source": "x"}, T.lee("Grado en Derecho")),
                   ({"id": "x:2", "source": "x"}, T.lee("Tarjeta profesional de patrón")),
                   ({"id": "x:3", "source": "x"}, T.lee("Grado en Gestión Turística")),
                   ({"id": "x:4", "source": "x"}, T.Requisito(T.NO_CONSTA, "sin_apartado"))]
        texto = T.report(ofertas)
        self.assertIn("| x | 4 | 2 | 1 | 0 | 1 sin_apartado |", texto)
        self.assertIn("- `x:2` sin leer: tarjeta; sin título académico reconocido: Tarjeta profesional de patrón", texto)
        self.assertIn("- 1 × gestion turistica", texto)

    def test_ficha_para_revisar(self):
        texto = T.ficha({"id": "x:1", "title": "Técnico/a", "url": "https://example.org/1"},
                        T.lee("Licenciatura o Grado + Máster Oficial en Derecho (nivel 3 MECES)"))
        self.assertIn("> Licenciatura o Grado + Máster Oficial en Derecho (nivel 3 MECES)", texto)
        self.assertIn("- Vía: Grado + Máster (MECES 3)", texto)
        self.assertIn("- Nombra: Derecho", texto)


if __name__ == "__main__":
    unittest.main()
