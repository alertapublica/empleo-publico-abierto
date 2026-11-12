import unittest
from datetime import datetime, timezone
from pathlib import Path

from empleo.model import SourceLayoutError
from empleo.sources import andalucia

FIXTURES = Path(__file__).parent / "fixtures"
FICHA = andalucia.SITE + "/organismos/transparencia/empleo-publico/entidades-instrumentales/ofertas-empleo/detalle/{}.html"


def fixture(name):
    return (FIXTURES / name).read_text(encoding="utf-8")


class Http:
    def __init__(self, pages):
        self.pages, self.urls = pages, []

    def get(self, url):
        self.urls.append(url)
        page = self.pages[url]
        return page if page.startswith("<") else fixture(page)


def listing(*rows, total=None):
    total = len(rows) if total is None else total
    if not rows:
        return ('<html><body><div class="view"><div class="view-empty">No se encontraron resultados coincidentes'
                ' con la consulta realizada.</div></div></body></html>')
    body = "".join(
        f'<tr><td headers="view-field-ofem-denominacion-puesto-table-column"><a href="/organismos/transparencia/'
        f'empleo-publico/entidades-instrumentales/ofertas-empleo/detalle/{ref}.html">{title}</a></td>'
        f'<td headers="view-field-organismo-table-column">{entity}</td></tr>' for ref, title, entity in rows)
    return (f'<html><body><div class="view"><span class="view-header__summary">{total} recursos disponibles</span>'
            f"<table><tbody>{body}</tbody></table></div></body></html>")


def at(*args):
    return datetime(*args, tzinfo=timezone.utc)


FPS = "Fundación Pública Andaluza Progreso y Salud, M.P."
CODE_TITLE = "Técnico/a Auxiliar en Caracterización Molecular y Cultivo Celular"


class Andalucia(unittest.TestCase):
    def test_listado_en_plazo(self):
        total, rows = andalucia.parse_list(fixture("andalucia-lista.html"))
        self.assertEqual((total, len(rows)), (14, 14))
        self.assertEqual(rows[0], {"ref": "692710", "url": FICHA.format(692710),
                                   "title": "AYUDANTE TÉCNICO/A ELECTRÓNICO",
                                   "entity": "Canal Sur Radio y Televisión, S.A."})

    def test_ficha_sae(self):
        ficha = andalucia.parse_ficha(fixture("andalucia-ficha-sae.html"))
        self.assertEqual({k: ficha[k] for k in ("type", "read", "opens_on", "deadline", "published_on",
                                                 "positions", "code", "location", "contract")}, {
            "type": "Oferta genérica SAE", "read": True, "opens_on": "2026-11-11", "deadline": "2026-11-15",
            "published_on": "2026-11-10", "positions": 1, "code": None, "location": "MÁLAGA (Málaga)",
            "contract": "Duración determinada- interinidad"})
        self.assertEqual([s["title"] for s in ficha["sections"]],
                         ["Datos de la convocatoria", "Otros requisitos", "Convocatoria y bases de la oferta"])
        self.assertIn("Oferta genérica SAE", ficha["sections"][0]["html"])
        self.assertIn("Convocatoria%20puesto%20Ayudante", ficha["sections"][-1]["html"])

    def test_codigo_solo_si_lo_es(self):
        self.assertEqual(andalucia.parse_ficha(fixture("andalucia-ficha-2487.html"))["code"], "2487")
        educacion = andalucia.parse_ficha(fixture("andalucia-ficha-educacion.html"))
        self.assertIsNone(educacion["code"])  # «Según convocatoria en la Agencia»
        self.assertIn("Perfil técnico especialista o experto", educacion["sections"][0]["html"])
        self.assertEqual([s["title"] for s in educacion["sections"]][1:3], ["Funciones", "Otros requisitos"])

    def test_ofertas_con_entidad_codigo_y_una_sola_vez_las_repetidas(self):
        http = Http({
            andalucia.PAGE: listing(("692710", "AYUDANTE TÉCNICO/A ELECTRÓNICO", "Canal Sur Radio y Televisión, S.A."),
                                    ("692230", f"{CODE_TITLE} -2487", FPS), ("692221", f"{CODE_TITLE}- 2487", FPS)),
            FICHA.format(692710): "andalucia-ficha-sae.html",
            FICHA.format(692221): "andalucia-ficha-2487.html",
            FICHA.format(692230): "andalucia-ficha-2487.html",
        })
        source = andalucia.AndaluciaSource(at(2026, 11, 12, 12, 0))
        offers = source.list_offers(http)
        self.assertEqual([(o.ref, o.title, o.code, o.source_title, o.company) for o in offers], [
            ("692221", CODE_TITLE, "2487", f"{CODE_TITLE}- 2487", FPS),
            ("692710", "AYUDANTE TÉCNICO/A ELECTRÓNICO", None, None, "Canal Sur Radio y Televisión, S.A.")])
        sae = offers[1]
        self.assertEqual((sae.kind, sae.contract, sae.opens_on, sae.deadline, sae.positions),
                         ("temporal", "Duración determinada- interinidad", "2026-11-11", "2026-11-15", 1))
        self.assertEqual(offers[0].kind, "indefinido")
        detail = source.fetch_detail(http, sae)
        self.assertEqual(detail.location, "MÁLAGA (Málaga)")
        self.assertEqual(len(http.urls), 4)  # las fichas no se vuelven a pedir

    def test_ni_promocion_interna_ni_fuentes_propias_ni_consejerias(self):
        interna = fixture("andalucia-ficha-sae.html").replace(">Oferta genérica SAE<", ">Promoción interna<")
        http = Http({
            andalucia.PAGE: listing(
                ("1", "Puesto", "Canal Sur Radio y Televisión, S.A."),
                ("2", "Técnico", "Fundación Pública Andaluza para la Gestión de la Investigación en Salud de Sevilla (FISEVI)"),
                ("3", "Técnico", "Fundación Pública Andaluza para la Investigación Biosanitaria en Andalucía Oriental Alejandro Otero (FIBAO)"),
                ("4", "Inspector", "Verificaciones Industriales de Andalucía S.A."),
                ("5", "Administrativo", "Salud y Familias")),
            FICHA.format(1): interna,
        })
        self.assertEqual(andalucia.AndaluciaSource(at(2026, 11, 12, 12, 0)).list_offers(http), [])
        self.assertEqual(http.urls, [andalucia.PAGE, FICHA.format(1)])  # las demás, sin leer la ficha

    def test_plazo_vencido_o_tipo_desconocido(self):
        http = Http({andalucia.PAGE: listing(("692710", "Puesto", "Canal Sur Radio y Televisión, S.A.")),
                     FICHA.format(692710): "andalucia-ficha-sae.html"})
        self.assertEqual(andalucia.AndaluciaSource(at(2026, 11, 15, 23, 30)).list_offers(http), [])
        with self.assertRaises(SourceLayoutError):
            andalucia.parse_ficha(fixture("andalucia-ficha-sae.html").replace(">Oferta genérica SAE<", ">Concurso<"))

    def test_ficha_sin_plazo_completo_se_detiene(self):
        with self.assertRaises(SourceLayoutError):
            andalucia.parse_ficha(fixture("andalucia-ficha-sae.html").replace("11/11/2026 - 15/11/2026", "15/11/2026"))

    def test_bolsa(self):
        self.assertEqual(andalucia.kind_of("Bolsa de trabajo", "Indefinido"), "bolsa")
        self.assertEqual(andalucia.kind_of("Oferta de empleo", "Duración determinada- prácticas"), "practicas")
        self.assertIsNone(andalucia.kind_of("Oferta de empleo", "Alta dirección"))

    def test_vacio_y_cambios_de_pagina(self):
        self.assertEqual(andalucia.parse_list(listing()), (0, []))
        with self.assertRaises(SourceLayoutError):
            andalucia.parse_list("<html><body>Página no encontrada</body></html>")
        with self.assertRaises(SourceLayoutError):  # sin la cifra de arriba
            andalucia.parse_list(fixture("andalucia-lista.html").replace("recursos disponibles", "resultados"))

    def test_si_no_cuadra_con_la_cifra_se_detiene(self):
        http = Http({andalucia.PAGE: listing(("1", "Puesto", "Canal Sur Radio y Televisión, S.A."), total=2),
                     andalucia.PAGE + "&page=1": listing()})
        with self.assertRaises(SourceLayoutError):
            andalucia.AndaluciaSource(at(2026, 11, 12, 12, 0)).list_offers(http)

    def test_pasa_de_pagina_hasta_completar(self):
        http = Http({andalucia.PAGE: listing(("1", "Uno", "Agencia X"), total=2),
                     andalucia.PAGE + "&page=1": listing(("2", "Dos", "Agencia X"), total=2),
                     FICHA.format(1): "andalucia-ficha-sae.html", FICHA.format(2): "andalucia-ficha-educacion.html"})
        offers = andalucia.AndaluciaSource(at(2026, 11, 12, 12, 0)).list_offers(http)
        self.assertEqual([o.ref for o in offers], ["1", "2"])


if __name__ == "__main__":
    unittest.main()
