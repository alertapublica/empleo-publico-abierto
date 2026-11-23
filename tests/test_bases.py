import tempfile
import unittest
from pathlib import Path

from empleo import bases, store

FIXTURES = Path(__file__).parent / "fixtures"
ANEXO = "ineco-tro26-ipa-001-anexo.pdf"


class FakeHttp:
    def __init__(self):
        self.urls = []

    def get_bytes(self, url):
        self.urls.append(url)
        if url.endswith("roto.pdf"):
            raise OSError("404")
        return (FIXTURES / ANEXO).read_bytes()


def offer(ref, **extra):
    return {"id": f"x:{ref}", "source": "x", "title": f"Oferta {ref}", "url": f"https://x.es/{ref}", "status": "open",
            "sections": [], **extra}


class Enlaces(unittest.TestCase):
    def test_pdf_de_la_ficha_y_la_propia_url(self):
        html = ('<a href="/bases.pdf">Bases</a> <a href="https://x.es/a.PDF?v=2">Anexo</a> <a href="/web">Web</a>'
                ' <a href="/bases.pdf">Otra vez</a>')
        found = bases.pdf_links(offer("1", url="https://x.es/conv.pdf", sections=[{"html": html}]))
        self.assertEqual(found, ["https://x.es/conv.pdf", "https://x.es/bases.pdf", "https://x.es/a.PDF?v=2"])

    def test_solo_las_fichas_sin_texto_salvo_que_se_pidan_todas(self):
        with tempfile.TemporaryDirectory() as tmp:
            link = [{"title": "Documentos", "html": '<a href="/b.pdf">Bases</a>'}]
            full = [{"title": "Funciones", "html": "<p>" + "palabra " * 120 + "</p>"}, *link]
            store.save(Path(tmp) / "x/offers.json", {
                "1": offer("1", sections=link), "2": offer("2", sections=full),
                "3": offer("3", sections=link, status="closed"), "4": offer("4")})
            self.assertEqual([c["id"] for c in bases.candidates(Path(tmp), [], False)], ["x:1"])
            self.assertEqual([c["id"] for c in bases.candidates(Path(tmp), [], True)], ["x:1", "x:2"])
            self.assertEqual(bases.candidates(Path(tmp), ["otra"], True), [])


class Lectura(unittest.TestCase):
    def test_frases_literales_con_su_pagina(self):
        found = bases.detect(["Se ofrece contrato indefinido. Posibilidad de teletrabajo hasta el 50 % de la jornada.",
                              "Requisitos: estar en posesión del título de Grado en Biología. Salario: 30.000 € brutos anuales."
                              " Plazo de presentación hasta el 30 de noviembre de 2026."])
        self.assertEqual(found["teletrabajo"],
                         [{"pagina": 1, "frase": "Posibilidad de teletrabajo hasta el 50 % de la jornada."}])
        self.assertEqual(found["titulacion"][0]["pagina"], 2)
        self.assertIn("Grado en Biología", found["titulacion"][0]["frase"])
        self.assertEqual(found["retribucion"][0]["frase"], "Salario: 30.000 € brutos anuales.")
        self.assertEqual(found["plazo"], ["2026-11-30"])
        self.assertEqual(found["presencial"], [])

    def test_tope_de_pdf_y_los_que_fallan_no_paran(self):
        http = FakeHttp()
        items = [{"id": "x:1", "fuente": "x", "titulo": "Uno", "ficha": "f", "pdfs": ["https://x/roto.pdf", "https://x/a.pdf"]},
                 {"id": "x:2", "fuente": "x", "titulo": "Dos", "ficha": "f", "pdfs": ["https://x/b.pdf"]},
                 {"id": "x:3", "fuente": "x", "titulo": "Tres", "ficha": "f", "pdfs": ["https://x/c.pdf"]}]
        results = bases.run(http, items, 3)
        self.assertEqual(len(http.urls), 3)
        self.assertEqual([r["id"] for r in results], ["x:1", "x:2"])
        roto, bueno = results[0]["leidos"]
        self.assertEqual((roto["legible"], roto["motivo"]), (False, "404"))
        self.assertTrue(bueno["legible"])
        # Anexo con forma de formulario: el texto sale desordenado y la frase es la del rótulo; aquí basta con
        # saber que lo menciona.
        self.assertIn("TITULACIÓN ACADÉMICA", bueno["titulacion"][0]["frase"])
        informe = bases.report(results)
        self.assertIn("| x | 2 | 3 | 2 |", informe)
        self.assertIn("- https://x/roto.pdf: no legible (404)", informe)

    def test_bases_sueltas(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "urls.txt"
            path.write_text("# comentario\nadif https://adif.es/bases.pdf\n\nmal\n", encoding="utf-8")
            self.assertEqual([(i["fuente"], i["pdfs"]) for i in bases.extra(path)],
                             [("adif", ["https://adif.es/bases.pdf"])])


if __name__ == "__main__":
    unittest.main()
