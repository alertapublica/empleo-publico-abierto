import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from bs4 import BeautifulSoup

from empleo.model import SourceLayoutError
from empleo.sources import uji

FIXTURES = Path(__file__).parent / "fixtures"
PAGE = (FIXTURES / "uji-tao-pi.html").read_text(encoding="utf-8")
FICHA = (FIXTURES / "uji-ficha-3607.html").read_text(encoding="utf-8")  # 13/11/2026 – 26/11/2026
# Solicitudes 14/10–27/10; la tarjeta enseña «sol·licituds» 04/11–17/11, la subsanación de la lista provisional
ESMENA = (FIXTURES / "uji-ficha-3563.html").read_text(encoding="utf-8")


def at(year, month, day, hour=10):
    return datetime(year, month, day, hour, 0, tzinfo=timezone.utc)


def call(conv="9001", title="23999 plaça de personal investigador júnior per col·laborar en el projecte "
         "d’investigació: “26I001 PROVA”, dirigit per Algú.", state=None, links=1):
    state = state or ("<div class=\"p\">Inici de presentació de sol·licituds 01/12/26</div>"
                      "<div class=\"p\"><strong>Fi de presentació de sol·licituds 14/12/26</strong></div>")
    concursos = "".join(f'<li><a href="/seu/info-adm/tao/convocatoriesRH?pConv={conv}&amp;pConcurso={n + 1}'
                        f'&amp;pCategoria=14">Personal investigador júnior</a></li>' for n in range(links))
    return (f'<div class="tao-concursos-pdi" id="convocatoria-{conv}" style="display:none">'
            f'<div class="item tao-item"><div><p class="customText bold secundary"><a href="#"><strong>{title}'
            f'</strong></a></p>{state}</div></div><ul>{concursos}</ul></div>')


def page(*calls, box="1001"):
    return f'<div id="tao-box-cat{box}" class="tao-box"><h4>a2) Places</h4>{"".join(calls)}</div>'


class Http:
    """El tablón PI del 2026-11-16, recortado (las 13 abiertas, 3 cerradas por subcategoría y los casos
    raros), y la ficha real de la 3607 con el plazo de cada convocatoria."""

    def __init__(self, page=PAGE, periods=None, fichas=None):
        self.asked, self.page, self.periods, self.fichas = [], page, periods or {}, fichas or {}

    def get(self, url):
        self.asked.append(url)
        if url == uji.INDEX:
            return self.page
        conv = parse_qs(urlparse(url).query)["pConv"][0]
        if conv in self.fichas:
            return self.fichas[conv]
        first, last = self.periods.get(conv, ("13/11/2026", "26/11/2026"))
        return FICHA.replace("13/11/2026", first).replace("26/11/2026", last)


class List(unittest.TestCase):
    def test_plazas_con_su_plazo_y_sin_bolsas(self):
        rows = uji.parse_list(PAGE)
        self.assertEqual(len(rows), 41)
        self.assertTrue({r["kind"] for r in rows} <= uji.PLACES)
        by_ref = {r["ref"]: (r["opens_on"], r["deadline"]) for r in rows}
        self.assertEqual(sum(1 for r in rows if r["deadline"]), 13)
        self.assertEqual(by_ref["3607"], ("2026-11-13", "2026-11-26"))
        self.assertEqual(by_ref["3576"], ("2026-11-16", "2026-11-27"))
        self.assertEqual(by_ref["3586"], (None, None))  # «Disponible únicament per a consulta»
        self.assertEqual(by_ref["3583"], (None, None))  # «Inici termini d'esmena»: no es de solicitudes
        self.assertEqual(rows[0]["url"], "https://www.uji.es/seu/info-adm/tao/convocatoriesRH?pConv=3607&pConcurso=1"
                                         "&pCategoria=14")

    def test_titulo_categoria_y_proyecto(self):
        rows = {r["ref"]: uji.labels(r) for r in uji.parse_list(PAGE)}
        self.assertEqual(rows["3607"], {
            "title": "Personal investigador predoctoral en formació (Projectes) · 26I445 Desenvolupament de nous "
                     "biomaterials per al tractament de l'osteonecrosi (OSTEOPROTECT)",
            "category": "Personal investigador predoctoral en formació (Projectes)", "code": "23207",
            "source_title": "23207 plaça de personal investigador predoctoral en formació (Projectes) per col·laborar "
                            "en el projecte d’investigació: “26I445 DESENVOLUPAMENT DE NOUS BIOMATERIALS PER AL "
                            "TRACTAMENT DE L'OSTEONECROSI (OSTEOPROTECT)”, dirigit per Julio José Suay Antón del "
                            "Departament d'Enginyeria de Sistemes Industrials i Disseny. Grup d’investigació: "
                            "Polímers i materials avançats."})
        # El concurso dice «Plaça de personal tecnòleg…»: la categoría sale del título
        self.assertEqual(rows["3600"]["category"], "Personal tecnòleg o gestor superior")
        # Comillas «», sin dos puntos ni «dirigit per»
        self.assertEqual(rows["3560"]["title"], "Personal tecnòleg o gestor bàsic · 25I567 Valorització de residus "
                         "procedents del cicle integral de l'aigua en materials de baix impacte ambiental")
        self.assertTrue(rows["3557"]["title"].startswith("Personal investigador predoctoral en formació (Projectes) · "
                                                         "Pecaths - photo-electrocatalytic"))  # sin código

    def test_formatos_antiguos_literal_con_los_codigos(self):
        rows = {r["ref"]: uji.labels(r) for r in uji.parse_list(PAGE)}
        self.assertEqual(rows["3586"]["title"], "Convocatòria única: 08 contractes predoctorals (PROGRAMA ESTATAL "
                                                "FPI-AEI 2026)")
        self.assertIsNone(rows["3586"]["category"])  # ocho concursos
        self.assertIsNone(rows["3586"]["code"])
        self.assertEqual(rows["3466"]["title"][:42], "Projecte d’investigació 21I395. grup d'inv")
        self.assertEqual(rows["3466"]["category"], "Personal investigador predoctoral en formació")

    def test_subcategoria_desconocida_detiene_y_bolsas_se_saltan(self):
        with self.assertRaisesRegex(SourceLayoutError, "subcategoría desconocida"):
            uji.parse_list(page(call(), box="3000"))
        with self.assertRaisesRegex(SourceLayoutError, "ninguna convocatoria de plazas"):
            uji.parse_list(page(call(), box="2001"))
        with self.assertRaisesRegex(SourceLayoutError, "no tiene subcategorías"):
            uji.parse_list("<html><body><p>Manteniment</p></body></html>")

    def test_tarjeta_rara_detiene(self):
        cases = {
            "sin un plazo": '<div class="p">Fi de presentació de sol·licituds 14/12/26</div>',
            "imposible": ('<div class="p">Inici de presentació de sol·licituds 01/12/26</div>'
                          '<div class="p">Fi de presentació de sol·licituds 31/11/26</div>'),
            "al revés": ('<div class="p">Inici de presentació de sol·licituds 14/12/26</div>'
                         '<div class="p">Fi de presentació de sol·licituds 01/12/26</div>'),
        }
        for message, state in cases.items():
            with self.subTest(message), self.assertRaisesRegex(SourceLayoutError, message):
                uji.parse_list(page(call(state=state)))
        with self.assertRaisesRegex(SourceLayoutError, "sin un plazo"):  # ni plazo ni «únicament per a consulta»
            uji.parse_list(page(call(state='<div class="p">Pendent</div>')))
        with self.assertRaisesRegex(SourceLayoutError, "sin título o sin concursos"):
            uji.parse_list(page(call(links=0)))
        with self.assertRaisesRegex(SourceLayoutError, "apunta a pConv"):
            uji.parse_list(page(call().replace('id="convocatoria-9001"', 'id="convocatoria-9002"')))

    def test_ficha(self):
        ficha = uji.parse_ficha(FICHA)
        self.assertEqual((ficha["opens_on"], ficha["deadline"]), ("2026-11-13", "2026-11-26"))
        self.assertEqual(ficha["published_on"], "2026-11-12")
        self.assertIn("Codi Registre", ficha["html"])
        self.assertIn('href="https://ujiapps.uji.es/ade/rest/storage/R8WBVS32LVQYZMAPXGJIG9QSNYNBWG0X"', ficha["html"])
        self.assertNotIn("<h2", ficha["html"])
        with self.assertRaisesRegex(SourceLayoutError, "ficha sin"):
            uji.parse_ficha("<html><body><h2>Error</h2></body></html>")
        esmena = uji.parse_ficha(ESMENA)  # el «Termini» de la lista provisional no cuenta
        self.assertEqual((esmena["opens_on"], esmena["deadline"], esmena["published_on"]),
                         ("2026-10-14", "2026-10-27", "2026-10-13"))

    def test_ficha_con_plazos_distintos_o_ampliados_detiene(self):
        other = FICHA.replace("Termini  </strong>13/11/2026", "Termini  </strong>14/11/2026")
        with self.assertRaisesRegex(SourceLayoutError, "solo uno"):
            uji.parse_ficha(other)
        far = FICHA.replace("13/11/2026 - 26/11/2026", "13/11/2026 - 22/11/2026")
        with self.assertRaisesRegex(SourceLayoutError, "solo uno"):
            uji.parse_ficha(far)

    def test_ficha_con_plazos_que_acaban_casi_igual_vale_el_mas_temprano(self):
        # La 3610 el 2026-11-25: concurso 25/11–10/12, resolución que convoca 25/11–09/12.
        for end, deadline in (("25/11/2026", "2026-11-25"), ("29/11/2026", "2026-11-26")):
            ficha = uji.parse_ficha(FICHA.replace("13/11/2026 - 26/11/2026", f"13/11/2026 - {end}"))
            self.assertEqual((ficha["opens_on"], ficha["deadline"]), ("2026-11-13", deadline))

    def test_plazos_casi_iguales_con_dos_resoluciones_que_convocan_detiene(self):
        # La tolerancia es para el concurso frente a una sola resolución, no para tres plazos.
        html = FICHA.replace("13/11/2026 - 26/11/2026", "13/11/2026 - 25/11/2026")
        soup = BeautifulSoup(html, "html.parser")
        resolution = next(p for p in soup.select("p.tao-ar-texto") if uji.CONVENES.search(p.get_text(" ")))
        head = resolution.find_previous_sibling("div")
        copy = BeautifulSoup(str(head).replace("25/11/2026", "26/11/2026") + str(resolution), "html.parser")
        resolution.insert_after(copy)
        with self.assertRaisesRegex(SourceLayoutError, "solo uno"):
            uji.parse_ficha(str(soup))
        extended = FICHA.replace("per la qual es convoca un procés selectiu",
                                 "per la qual s'amplia el termini de presentació del procés selectiu", 1)
        with self.assertRaisesRegex(SourceLayoutError, "amplía o cambia"):
            uji.parse_ficha(extended)
        with self.assertRaisesRegex(SourceLayoutError, "al revés"):
            uji.parse_ficha(FICHA.replace("26/11/2026", "01/11/2026"))


class Offers(unittest.TestCase):
    def test_en_plazo_el_26(self):
        http = Http(periods={"3576": ("16/11/2026", "27/11/2026")})
        source = uji.UjiSource(now=at(2026, 11, 26))
        offers = source.list_offers(http)
        self.assertEqual([o.ref for o in offers], ["3607", "3606", "3576"])
        first = offers[0]
        self.assertEqual((first.code, first.category, first.published_on, first.opens_on, first.deadline, first.kind),
                         ("23207", "Personal investigador predoctoral en formació (Projectes)", "2026-11-12",
                          "2026-11-13", "2026-11-26", None))
        self.assertEqual(first.apply_url, first.url)
        self.assertEqual(len(http.asked), 4)  # el tablón y las tres fichas
        cached = Http(page="sin uso")
        detail = source.fetch_detail(cached, first)
        self.assertEqual(cached.asked, [])  # la ficha ya leída en list_offers no se vuelve a pedir
        self.assertEqual(detail.location, "Castelló de la Plana")
        self.assertEqual((detail.sections[0]["title"], detail.sections[0]["lang"]), ("La convocatoria", "ca"))

    def test_hoy_doce_la_de_la_subsanacion_no(self):
        rows = [r for r in uji.parse_list(PAGE) if r["deadline"]]
        periods = {r["ref"]: tuple(f"{d[8:]}/{d[5:7]}/{d[:4]}" for d in (r["opens_on"], r["deadline"])) for r in rows}
        http = Http(periods=periods, fichas={"3563": ESMENA})
        offers = uji.UjiSource(now=at(2026, 11, 16)).list_offers(http)
        self.assertEqual(len(offers), 12)
        self.assertNotIn("3563", [o.ref for o in offers])
        self.assertEqual(len(http.asked), 14)  # el tablón y las 13 fichas

    def test_antes_de_abrir_tambien_sale(self):
        http = Http(page=page(call()), periods={"9001": ("01/12/2026", "14/12/2026")})
        [offer] = uji.UjiSource(now=at(2026, 11, 20)).list_offers(http)
        self.assertEqual((offer.opens_on, offer.deadline, offer.title),
                         ("2026-12-01", "2026-12-14", "Personal investigador júnior · 26I001 Prova"))

    def test_ficha_sin_cache_la_relee(self):
        offer = uji.UjiSource(now=at(2026, 11, 26)).list_offers(Http(periods={"3576": ("16/11/2026", "27/11/2026")}))[0]
        http = Http()
        detail = uji.UjiSource().fetch_detail(http, offer)
        self.assertIn("Codi Registre", detail.sections[0]["html"])
        self.assertEqual(http.asked, [offer.url])


if __name__ == "__main__":
    unittest.main()
