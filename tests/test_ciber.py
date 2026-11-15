import copy
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from empleo.model import SourceLayoutError
from empleo.sources import ciber

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name):
    return (FIXTURES / (name + ".jsonp")).read_text(encoding="utf-8")


def wrapped(data):
    return "empleo(" + json.dumps(data, ensure_ascii=False) + ");"


def at(day, hour=10):
    return datetime(2026, 11, day, hour, tzinfo=timezone.utc)


class Http:
    def __init__(self, changes=None):
        self.calls = []
        self.changes = changes or {}

    def get(self, url):
        self.calls.append(url)
        if url in self.changes:
            return self.changes[url]
        query = parse_qs(urlsplit(url).query)
        if "PerfilId" in query:
            return fixture("ciber-perfil-" + query["PerfilId"][0])
        for method, name in zip(ciber.METHODS, ("abiertas", "reposicion-correcta", "estabilizacion")):
            if url == ciber.listing_url(method):
                return fixture("ciber-" + name)
        raise AssertionError("Petición inesperada: " + url)


class Parsing(unittest.TestCase):
    def test_listado_real_con_total_y_fechas(self):
        total, pages, current, rows = ciber.parse_page(fixture("ciber-abiertas"))
        self.assertEqual((total, pages, current, len(rows)), (5, 1, 1, 5))
        self.assertEqual(rows[0]["CategoriaProfesional"], "Titulado Superior")
        self.assertIsNone(rows[0]["Plazas"])

    def test_vacio_real_es_distinto_de_una_respuesta_rota(self):
        self.assertEqual(ciber.parse_page(fixture("ciber-estabilizacion")), (0, 0, 1, []))
        for text in ("<html>Error 500</html>", "empleo({});", "empleo(null);", "empleo({Lista:[]});",
                     'otro({"Lista":[]});', 'empleo({"Lista":[]});alert(1);'):
            with self.subTest(text=text), self.assertRaises(SourceLayoutError):
                ciber.parse_page(text)

    def test_fechas_campos_y_total_ilegibles_detienen(self):
        original = ciber.parse_jsonp(fixture("ciber-abiertas"))
        for key, value in (("FechaHasta", "31/02/2026"), ("FechaDesde", "22/11/2026"),
                           ("CategoriaProfesional", None), ("IdPerfil", ""), ("Plazas", "2")):
            data = copy.deepcopy(original)
            data["Lista"][0][key] = value
            with self.subTest(key=key), self.assertRaises(SourceLayoutError):
                ciber.parse_page(wrapped(data))
        for key, value in (("ElementosEncontrados", 6), ("Paginas", 0), ("PaginaActual", 2),
                           ("Paginas", True), ("Lista", [])):
            data = {**original, key: value}
            with self.subTest(key=key), self.assertRaises(SourceLayoutError):
                ciber.parse_page(wrapped(data))

    def test_perfil_contrato_y_condiciones_literales(self):
        detail = ciber.parse_detail(fixture("ciber-perfil-3919"), "3919")
        sections = {s["title"]: s["html"] for s in detail["sections"]}
        self.assertEqual(detail["data"]["TipoContrato"], "Interinidad")
        self.assertEqual(detail["deadline"], "2026-11-19")
        self.assertIn("Gestión y coordinación general", sections["Perfil del puesto"])
        self.assertIn("35,00", sections["Condiciones"])
        self.assertIn("37.300,35 €", sections["Condiciones"])
        self.assertIn("VALENCIA", detail["location"])

    def test_texto_escapado_y_saltos_doblemente_escapados(self):
        data = ciber.parse_jsonp(fixture("ciber-perfil-3918"))
        data["FuncionesDesarrollar"] = '<script>alert(1)</script>\\r\\nSegundo párrafo'
        detail = ciber.parse_detail(wrapped(data), "3918")
        html = next(s["html"] for s in detail["sections"] if s["title"] == "Funciones a desarrollar")
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("</p><p>Segundo párrafo</p>", html)

    def test_ficha_equivocada_sin_perfil_correccion_o_inscripcion_ajena_detienen(self):
        original = ciber.parse_jsonp(fixture("ciber-perfil-3919"))
        for key, value in (("IdPerfil", "3918"), ("Perfil", ""), ("FechaHasta", "mañana"),
                           ("ContieneErrores", True), ("URLPaginaSolicitud", "https://ejemplo.es/?PRFId=3919"),
                           ("URLPaginaSolicitud", "https://intranet.cientifis.com/?PRFId=3918")):
            with self.subTest(key=key), self.assertRaises(SourceLayoutError):
                ciber.parse_detail(wrapped({**original, key: value}), "3919")


class Source(unittest.TestCase):
    def test_ocho_anuncios_y_tres_listados_sin_confundir_plazas(self):
        http = Http()
        source = ciber.CiberSource(now=at(15))
        offers = source.list_offers(http)
        self.assertEqual(len(offers), 8)
        self.assertNotIn("3911", {o.ref for o in offers})  # «Abiertas», vencida el 13/11
        self.assertEqual(len(http.calls), 11)  # tres listados y ocho perfiles, sin listas de personas
        self.assertEqual({o.positions for o in offers}, {None})  # 3913 dice «dos personas», Plazas es null
        self.assertEqual({o.published_on for o in offers}, {None})  # FechaDesde es inicio, no publicación
        self.assertEqual({o.deadline_time for o in offers}, {None})
        self.assertEqual(source.list_announcements(http), [])

    def test_codigo_categoria_y_empleador_no_se_deducen_del_centro(self):
        source = ciber.CiberSource(now=at(15))
        offers = {o.ref: o for o in source.list_offers(Http())}
        self.assertEqual(offers["3918"].title, "Doctor · Doctorado en Medicina")
        self.assertEqual(offers["3902"].title, "Doctor · Doctor/a en Psicologia Clínica o afines")  # sin el punto
        self.assertEqual(ciber.title({"CategoriaProfesional": "Doctor", "TitulacionAcademica": " "}), "Doctor")
        self.assertEqual(offers["3919"].category, "Doctor")
        self.assertEqual(offers["3919"].code, "3392/3919")
        self.assertEqual(offers["3921"].category, "Titulado Superior")
        self.assertEqual(offers["3921"].contract, "Predoctoral Ley de la ciencia")
        self.assertEqual(offers["3902"].company, "CIBER")  # anfitrión Bellvitge, no IDIBELL
        self.assertEqual(source.enrich(Http())["3917"], {"department": "UT"})

    def test_tipo_de_contrato_y_lugar_sin_inventar_un_centro(self):
        source, http = ciber.CiberSource(now=at(15)), Http()
        offers = {o.ref: o for o in source.list_offers(http)}
        self.assertEqual(offers["3902"].kind, "indefinido")
        self.assertEqual(offers["3919"].kind, "temporal")
        before = len(http.calls)
        detail = source.fetch_detail(http, offers["3917"])
        self.assertEqual(len(http.calls), before)  # la ficha ya leída se reutiliza
        self.assertEqual(detail.location, "MADRID")  # Centro = «SIN ESPECIFICAR»
        self.assertEqual(detail.contract, "Indefinido")

    def test_contrato_nuevo_se_conserva_sin_inventarle_kind(self):
        data = ciber.parse_jsonp(fixture("ciber-perfil-3919"))
        data["TipoContrato"] = "Otra modalidad oficial"
        source = ciber.CiberSource(now=at(15))
        offers = source.list_offers(Http({ciber.detail_url("3919"): wrapped(data)}))
        offer = next(o for o in offers if o.ref == "3919")
        self.assertEqual(offer.contract, "Otra modalidad oficial")
        self.assertIsNone(offer.kind)

    def test_ultimo_dia_entero_en_madrid_y_al_dia_siguiente_fuera(self):
        self.assertEqual(len(ciber.CiberSource(now=at(15, 22)).list_offers(Http())), 8)  # 23:00 Madrid
        offers = ciber.CiberSource(now=at(15, 23)).list_offers(Http())  # ya es 16/11 en Madrid
        self.assertEqual(len(offers), 7)
        self.assertNotIn("3921", {o.ref for o in offers})

    def test_ficha_que_corrige_fecha_y_ficha_fuera_de_plazo(self):
        data = ciber.parse_jsonp(fixture("ciber-perfil-3919"))
        data["FechaHasta"] = "20/11/2026"
        source = ciber.CiberSource(now=at(15))
        offers = source.list_offers(Http({ciber.detail_url("3919"): wrapped(data)}))
        self.assertEqual(next(o.deadline for o in offers if o.ref == "3919"), "2026-11-20")
        for key, value in (("FechaHasta", "14/11/2026"), ("FechaDesde", "16/11/2026")):
            data = ciber.parse_jsonp(fixture("ciber-perfil-3919"))
            data[key] = value
            offers = source.list_offers(Http({ciber.detail_url("3919"): wrapped(data)}))
            self.assertNotIn("3919", {o.ref for o in offers})

    def test_no_se_lee_una_fila_que_aun_no_ha_abierto(self):
        data = ciber.parse_jsonp(fixture("ciber-abiertas"))
        data["Lista"][0]["FechaDesde"] = "16/11/2026"
        data["Lista"][0]["FechaHasta"] = "20/11/2026"
        http = Http({ciber.listing_url(ciber.METHODS[0]): wrapped(data)})
        offers = ciber.CiberSource(now=at(15)).list_offers(http)
        self.assertNotIn("3921", {o.ref for o in offers})
        self.assertNotIn(ciber.detail_url("3921"), http.calls)

    def test_ficha_de_otra_convocatoria_detiene(self):
        data = ciber.parse_jsonp(fixture("ciber-perfil-3919"))
        data["IdConvocatoria"] = "9999"
        with self.assertRaises(SourceLayoutError):
            ciber.CiberSource(now=at(15)).list_offers(Http({ciber.detail_url("3919"): wrapped(data)}))


class Pagination(unittest.TestCase):
    def setUp(self):
        # La paginación >1 no se observó en «Abiertas». Se ejercita con filas derivadas del fixture real.
        row = ciber.parse_jsonp(fixture("ciber-abiertas"))["Lista"][0]
        self.rows = [{**row, "IdPerfil": str(5000 + n)} for n in range(16)]
        self.first = {"ElementosEncontrados": 16, "Paginas": 2, "PaginaActual": 1, "Lista": self.rows[:15]}
        self.last = {"ElementosEncontrados": 16, "Paginas": 2, "PaginaActual": 2, "Lista": self.rows[15:]}
        self.url = ciber.listing_url(ciber.METHODS[0])
        self.next = ciber.listing_url(ciber.METHODS[0], 2)

    def test_start_es_numero_de_pagina_y_se_lee_todo(self):
        http = Http({self.url: wrapped(self.first), self.next: wrapped(self.last)})
        rows = ciber.CiberSource()._listing(http, ciber.METHODS[0])
        self.assertEqual(len(rows), 16)
        self.assertEqual(parse_qs(urlsplit(http.calls[1]).query)["start"], ["2"])

    def test_duplicados_cambio_de_total_y_tope_detienen_sin_truncar(self):
        for last in ({**self.last, "Lista": [self.rows[0]]},
                     {**self.last, "ElementosEncontrados": 17, "Lista": self.rows[14:]}):
            with self.subTest(last=last), self.assertRaises(SourceLayoutError):
                ciber.CiberSource()._listing(Http({self.url: wrapped(self.first), self.next: wrapped(last)}),
                                             ciber.METHODS[0])
        first = {**self.first, "ElementosEncontrados": 165, "Paginas": 11}
        http = Http({self.url: wrapped(first)})
        with self.assertRaises(SourceLayoutError):
            ciber.CiberSource()._listing(http, ciber.METHODS[0])
        self.assertEqual(len(http.calls), 1)

    def test_mismo_perfil_en_dos_listados_no_duplica(self):
        data = ciber.parse_jsonp(fixture("ciber-reposicion-correcta"))
        ordinary = ciber.parse_jsonp(fixture("ciber-abiertas"))["Lista"][0]
        data["Lista"][0] = ordinary
        http = Http({ciber.listing_url(ciber.METHODS[1]): wrapped(data)})
        offers = ciber.CiberSource(now=at(15)).list_offers(http)
        self.assertEqual(len(offers), 7)
        self.assertEqual(http.calls.count(ciber.detail_url("3921")), 1)
        data["Lista"][0] = {**ordinary, "CategoriaProfesional": "Otros"}
        with self.assertRaises(SourceLayoutError):
            ciber.CiberSource(now=at(15)).list_offers(Http({ciber.listing_url(ciber.METHODS[1]): wrapped(data)}))


if __name__ == "__main__":
    unittest.main()
