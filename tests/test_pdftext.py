import unittest
from datetime import date

from empleo import pdftext
from empleo.model import SourceLayoutError
from empleo.text import slug


def tiny_pdf(text: str) -> bytes:
    """PDF mínimo de una página con ese texto (pypdf reconstruye la tabla de referencias)."""
    stream = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET"
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 600 200] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = "%PDF-1.4\n"
    for number, body in enumerate(objects, 1):
        out += f"{number} 0 obj\n{body}\nendobj\n"
    return (out + "trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n0\n%%EOF").encode("latin-1")


class Pdf(unittest.TestCase):
    def test_lee_el_texto_de_un_pdf(self):
        text = pdftext.pdf_text(tiny_pdf("La recepcion finalizara el 16 de noviembre de 2026"), "prueba")
        self.assertIn("16 de noviembre de 2026", text)

    def test_pdf_ilegible_detiene_la_fuente(self):
        with self.assertRaises(SourceLayoutError):
            pdftext.pdf_text(b"esto no es un pdf", "prueba")


class Deadlines(unittest.TestCase):
    def test_las_formas_reales_de_las_bases(self):
        casos = {
            "El plazo para la cobertura del puesto finalizará el 16 de noviembre de 2026 a las 13:00 horas.": date(2026, 11, 16),
            "hasta las 12:00 h del 06 de Noviembre de 2026 con:": date(2026, 11, 6),
            "se aceptarán candidaturas hasta las 23:59 horas del día 16 de julio de 2026.": date(2026, 7, 16),
            "queda ampliado hasta las 12:00 horas del día 16 de noviembre de 2026.": date(2026, 11, 16),
            "deberán enviar su candidatura … hasta las 23: 59 horas del 18 de octubre de 2026": date(2026, 10, 18),
        }
        for text, expected in casos.items():
            self.assertEqual(pdftext.deadlines(text), [expected], text)

    def test_ampliacion_trae_el_plazo_anterior_y_el_nuevo(self):
        text = ("el plazo inicialmente previsto hasta las 12:00 horas del día 29 de octubre de 2026 queda "
                "ampliado hasta las 12:00 horas del día 16 de noviembre de 2026")
        self.assertEqual(max(pdftext.deadlines(text)), date(2026, 11, 16))
        self.assertEqual(max(pdftext.deadlines_at(text)), (date(2026, 11, 16), "12:00"))

    def test_hora_partida_por_el_pdf(self):
        self.assertEqual(pdftext.deadlines_at("hasta las 23: 59 horas del 18 de octubre de 2026"),
                         [(date(2026, 10, 18), "23:59")])

    def test_otros_hasta_no_son_plazos(self):
        self.assertEqual(pdftext.deadlines("hasta el 15 por ciento de la retribución; hasta el momento de la firma"), [])


class Slug(unittest.TestCase):
    def test_sin_acentos_ni_signos(self):
        self.assertEqual(slug("Técnico/a de Planificación y Control"), "tecnico-a-de-planificacion-y-control")


class HourOn(unittest.TestCase):
    def test_hora_del_dia_pedido(self):
        from empleo.dates import hour_on
        text = "Fecha de cierre: 5 de noviembre de 2026 a las 12.00h Se amplía hasta el 13 de noviembre de 2026 a las 14:30h"
        self.assertEqual(hour_on(text, date(2026, 11, 13)), "14:30")
        self.assertEqual(hour_on(text, date(2026, 11, 5)), "12:00")
        self.assertIsNone(hour_on(text, date(2026, 11, 20)))

    def test_horas_distintas_para_el_mismo_dia_no_valen(self):
        from empleo.dates import hour_on
        text = "el 11 de noviembre de 2026 a las 15.00 horas; o el 11 de noviembre de 2026 a las 14:00"
        self.assertIsNone(hour_on(text, date(2026, 11, 11)))
        self.assertEqual(hour_on("finalizará el día 11 de noviembre de 2026 las 15.00 horas", date(2026, 11, 11)), "15:00")
