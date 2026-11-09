"""Código de la oferta: el que el portal pega al título o el que usa como referencia."""
import unittest

from empleo.sources import ACTIVE

SOURCES = {source.id: source for source in ACTIVE}


def labels(source_id, title, ref="1"):
    found = SOURCES[source_id].labels(title, ref)
    return found["title"], found["code"]


class TituloConCodigo(unittest.TestCase):
    # Títulos tal cual se leyeron el 2026-11-09.
    CASES = [
        ("isdefe", "Consultor/a de Ciberseguridad SOC (2025-T00019)(7)",
         "Consultor/a de Ciberseguridad SOC", "2025-T00019 (7)"),
        ("isdefe", "Ingeniero/a de operaciones de Sistemas GNSS Seguros (2025-T00495) (10)",
         "Ingeniero/a de operaciones de Sistemas GNSS Seguros", "2025-T00495 (10)"),
        ("isdefe", "Técnico/a experto en Contabilidad Analítica (2025-T00391)4",
         "Técnico/a experto en Contabilidad Analítica", "2025-T00391 4"),
        ("isdefe", "Ingeniero/a de Equipamiento de Aeronave (MEL)(2025-T00082) (12)",
         "Ingeniero/a de Equipamiento de Aeronave (MEL)", "2025-T00082 (12)"),
        ("isdefe", "Ingeniero/a de Plataformas Aéreas (2026-T00434)", "Ingeniero/a de Plataformas Aéreas",
         "2026-T00434"),
        ("idibell", "26-108_MS_XG Higher Technician in Occupational Health and Safety",
         "Higher Technician in Occupational Health and Safety", "26-108_MS_XG"),
        ("idibell", "26-144_SS_VN - Study Coordinator for Cancer Clinical Trials (Sick Leave Cover)",
         "Study Coordinator for Cancer Clinical Trials (Sick Leave Cover)", "26-144_SS_VN"),
        ("fisabio", "2026/67 UN/A TÉCNICO/A DE INVESTIGACIÓN (T3) PLAZA 146 RPT",
         "UN/A TÉCNICO/A DE INVESTIGACIÓN (T3)", "2026/67 PLAZA 146 RPT"),
        ("fisabio", "2026/70 PERSONAL TÉCNICO DE APOYO", "PERSONAL TÉCNICO DE APOYO", "2026/70"),
        ("idival", "2026.76. Convocatoria para la cobertura del puesto de Director/a Científico de IDIVAL",
         "Convocatoria para la cobertura del puesto de Director/a Científico de IDIVAL", "2026.76"),
        ("fnmt", "OE 25/26 - Médico de Empresa", "Médico de Empresa", "OE 25/26"),
        ("gpex", "BC26342 Personal Técnico Medio Ambiental", "Personal Técnico Medio Ambiental", "BC26342"),
        ("navarrabiomed", "26-42 Personal administrativo", "Personal administrativo", "26-42"),
        ("fisevi", "Titulación Universitaria de la rama de Ciencias o Ciencias de la Salud (NIVEL 2 MECES, "
                   "mínimo) REF: 297/26 IBiS",
         "Titulación Universitaria de la rama de Ciencias o Ciencias de la Salud (NIVEL 2 MECES, mínimo)",
         "297/26 IBiS"),
    ]

    def test_el_codigo_sale_del_titulo(self):
        for source_id, raw, title, code in self.CASES:
            with self.subTest(raw):
                self.assertEqual(labels(source_id, raw), (title, code))
                self.assertEqual(SOURCES[source_id].labels(raw, "1")["source_title"], raw)

    def test_si_no_encaja_el_titulo_queda_como_esta(self):
        for source_id, raw in [("isdefe", "Ingeniero/a de Sistemas"), ("fnmt", "Médico de Empresa"),
                               ("tragsa", "Veterinarios/as_Vigilancia (Salamanca)")]:
            with self.subTest(raw):
                self.assertEqual(SOURCES[source_id].labels(raw, "x"),
                                 {"title": raw, "code": None, "source_title": None})


class CodigoDeReferencia(unittest.TestCase):
    def test_solo_se_ensena_el_ref_que_publica_el_portal(self):
        cases = [
            ("tragsa", "56154", "56154"),
            ("tragsa", "tasas-reposicion-especifica-2025-2026", None),  # proceso: slug nuestro
            ("enresa", "DO-DE-26-028", "DO-DE-26-028"),
            ("enresa", "48a04f9e58", None),  # hash cuando la web no da código
            ("senasa", "21-26", "21-26"),
            ("efe", "MI 2025-01-02", "MI 2025-01-02"),
            ("cetarsa", "48a04f9e58", None),
            ("zarzuela", "responsable-tic", None),
            ("correos", "1413480533", None),
            ("isdefe", "2609", None),
        ]
        for source_id, ref, code in cases:
            with self.subTest(source_id=source_id, ref=ref):
                self.assertEqual(labels(source_id, "Puesto", ref), ("Puesto", code))

    def test_el_codigo_que_da_la_fuente_se_respeta(self):
        found = SOURCES["fundesalud"].labels("UN /A TÉCNICO", "13387", "Ref. 22/2026")
        self.assertEqual(found, {"title": "UN /A TÉCNICO", "code": "Ref. 22/2026", "source_title": None})


if __name__ == "__main__":
    unittest.main()
