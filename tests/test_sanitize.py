import unittest

from empleo.sanitize import sanitize


class Sanitize(unittest.TestCase):
    def test_elimina_scripts_y_atributos(self):
        out = sanitize('<p onclick="x()" style="color:red">Hola<script>alert(1)</script></p>')
        self.assertEqual(out, "<p>Hola</p>")

    def test_no_deja_enlaces_peligrosos(self):
        out = sanitize('<a href="javascript:alert(1)">pulsa</a>')
        self.assertEqual(out, "pulsa")
        self.assertNotIn("javascript", out)

    def test_mantiene_enlaces_seguros(self):
        out = sanitize('<a href="https://a.es/b" onmouseover="x()">web</a>')
        self.assertEqual(out, '<a href="https://a.es/b">web</a>')

    def test_desenvuelve_contenedores_y_conserva_texto(self):
        out = sanitize('<div class="x"><span><b>Dato</b></span></div>')
        self.assertEqual(out, "<strong>Dato</strong>")

    def test_quita_invisibles_y_vacios(self):
        out = sanitize("<p>​\xa0</p><ul><li>Uno​</li><li> </li></ul>")
        self.assertEqual(out, "<ul><li>Uno</li></ul>")
