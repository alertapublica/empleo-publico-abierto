import json
import re
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from unittest import mock
from urllib.parse import urljoin, urlparse

from empleo import areas, site, store

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=timezone.utc)
BASE = "https://example.org/p/"


def offer(ref, **extra):
    base = {
        "id": f"tragsa:{ref}", "source": "tragsa", "ref": ref, "title": f"Oferta {ref}",
        "company": "Tragsatec", "url": f"https://www.tragsa.es/f/{ref}",
        "apply_url": f"https://www.tragsa.es/i/{ref}", "kind": "temporal", "positions": 2,
        "category": "Específica", "deadline": "2026-11-20", "status": "open",
        "first_seen": "2026-11-07T00:00:00+00:00", "closed_at": None, "missed_runs": 0,
        "detail_ok": True, "sections": [{"title": "Funciones", "level": 2, "html": "<p>Tareas</p>"}],
        "location": "Sevilla", "region": "Andalucía", "department": "Sevilla",
        "family": "Apoyo Administrativo", "published_on": "2026-11-05", "parent_ref": None,
        "portal_tries": 1,
    }
    return {**base, **extra}


RELLENO = "<p>" + " ".join(["Funciones de apoyo técnico al equipo del proyecto."] * 12) + "</p>"
TELETRABAJO = RELLENO + "<p>Posibilidad de trabajo a distancia hasta el 50 % de la jornada.</p>"


class Parser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags, self.ids, self.links, self.labels, self.controls = [], [], [], [], []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append(tag)
        if "id" in attrs:
            self.ids.append(attrs["id"])
        if tag == "a":
            self.links.append(attrs.get("href"))
        if tag == "label" and "for" in attrs:
            self.labels.append(attrs["for"])
        if tag in ("input", "select") and attrs.get("type") not in ("checkbox", "hidden"):
            self.controls.append(attrs.get("id"))
        if tag == "html":
            self.lang = attrs.get("lang")


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.out = root / "_site"
        offers = {
            "1": offer("1", title='Técnico <script>alert("x")</script> & Co'),
            "2": offer("2", deadline="2026-11-08", region="Galicia", location="Lugo", company="Tragsa"),
            "3": offer("3", status="closed", closed_at="2026-11-07T00:00:00+00:00", deadline="2026-11-06"),
            "4": offer("4", parent_ref="77", sections=[{"title": "Condiciones", "level": 2, "html": TELETRABAJO}]),
            "5": offer("5", title="Analista programador", sections=[{"title": "Funciones", "level": 2, "html": RELLENO}]),
        }
        events = [{"offer": f"tragsa:{r}", "kind": "new", "at": "2026-11-07T06:00:00+00:00"} for r in offers]
        events.append({"offer": "tragsa:2", "kind": "deadline_changed", "at": "2026-11-07T07:00:00+00:00",
                       "before": "2026-11-07", "after": "2026-11-08"})
        notice = {"date": "2026-11-01", "process": "Tasa", "source": "tragsa", "via": "tasa", "access": "libre",
                  "contract": "indefinido", "system": "concurso-oposicion", "state": "curso", "deadline": None,
                  "apply_url": None, "process_url": "https://www.tragsa.es/proceso",
                  "title": "SE PUBLICAN LAS BASES DE TRAGSA", "url": "https://www.tragsa.es/p",
                  "first_seen": "2026-11-07T00:00:00+00:00"}
        notices = {
            "tragsa:a": notice,
            "tragsa:b": {**notice, "date": "2026-10-01", "title": "Convocatoria anterior", "url": "https://www.tragsa.es/a.pdf"},
            "tragsa:c": {**notice, "date": "2026-11-03", "process": "PROCESO ABIERTO (AB-1)", "state": "abierto",
                         "deadline": "2026-11-10", "apply_url": "https://plataforma.example/entrar", "title": "Plazo"},
            "tragsa:d": {**notice, "date": "", "process": "Sin fecha", "title": "Plazo cerrado"},
            "tragsa:e": {**notice, "date": "2026-05-01", "process": "Terminado", "state": "finalizado", "title": "Proceso finalizado"},
            "tragsa:f": {**notice, "date": "2026-04-01", "process": "Retirado", "state": "retirado", "title": "Último"},
        }
        store.save(root / "data/tragsa/offers.json", offers)
        store.save(root / "data/tragsa/events.json", events)
        store.save(root / "data/tragsa/announcements.json", notices)
        with mock.patch.object(site, "PLANNED", [{"id": "futura", "name": "Empresa futura"}]):
            site.build(root / "data", cls.out, BASE, NOW)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def pages(self):
        return [p for p in self.out.rglob("*.html") if p.name != "404.html"]

    def read(self, path):
        return (self.out / path).read_text(encoding="utf-8")

    def test_estructura_accesible_en_todas_las_paginas(self):
        for path in self.pages():
            parser = Parser()
            parser.feed(path.read_text(encoding="utf-8"))
            self.assertEqual(parser.lang, "es", path)
            self.assertEqual(parser.tags.count("h1"), 1, path)
            self.assertEqual(parser.tags.count("main"), 1, path)
            self.assertEqual(len(parser.ids), len(set(parser.ids)), path)
            self.assertFalse(set(parser.controls) - set(parser.labels), path)

    def test_panel_de_apariencia_en_cada_pagina(self):
        for path in self.pages() + [self.out / "404.html"]:
            html = path.read_text(encoding="utf-8")
            for needle in ('id="ajustes"', 'id="btn-aa"', 'assets/tema.js', 'assets/ajustes.js'):
                self.assertIn(needle, html, f"{needle} en {path}")
            # tema.js bloquea a propósito para pintar sin parpadeo; el resto, diferido
            self.assertNotRegex(html, r'tema\.js"[^>]*defer')
            self.assertRegex(html, r'ajustes\.js"[^>]*defer')

    def test_los_ajustes_funcionan_con_la_politica_de_contenido(self):
        html = self.read("index.html")
        self.assertIn("script-src 'self'", html)
        self.assertNotRegex(html, r"<script(?![^>]*src=)")
        self.assertNotIn(" style=", html)
        for name in ("tema.js", "ajustes.js", "filtros.js", "guardadas.js", "estilos.css"):
            self.assertTrue((self.out / "assets" / name).exists(), name)

    def test_sin_javascript_la_navegacion_sigue_visible(self):
        css = self.read("assets/estilos.css")
        self.assertIn(".menu-js nav.principal:not(.abierto)", css)  # solo se pliega si JS activó el botón
        self.assertRegex(self.read("index.html"), r'id="btn-menu"[^>]*hidden')

    def test_enlaces_internos_existen(self):
        for path in self.pages():
            parser = Parser()
            parser.feed(path.read_text(encoding="utf-8"))
            rel = path.relative_to(self.out).as_posix()
            for link in parser.links:
                if link.startswith("#"):
                    continue
                target = urlparse(urljoin("https://x/" + rel, link))
                if target.netloc != "x":
                    continue
                local = self.out / target.path.lstrip("/")
                local = local / "index.html" if target.path.endswith("/") else local
                self.assertTrue(local.exists(), f"{rel}: {link}")

    def test_escapa_el_texto_ajeno(self):
        html = self.read("index.html") + self.read("ofertas/tragsa-1/index.html")
        self.assertNotIn("<script>alert", html)
        self.assertIn("&lt;script&gt;", html)

    def test_lista_solo_abiertas(self):
        html = self.read("index.html")
        self.assertIn("ofertas/tragsa-2/", html)
        self.assertNotIn("ofertas/tragsa-3/", html)
        self.assertIn("4 ofertas abiertas, con 8 plazas", html)

    def panel(self, html):
        """El panel plegado de «Filtros»: lo que va entre su apertura y la ayuda o el fin del formulario."""
        return re.split(r'<p class="ayuda"|</form>', html.split('id="mas-filtros"')[1])[0]

    def test_buscador_con_pastillas_debajo_y_quitar_junto_al_recuento(self):
        html = self.read("index.html")
        form = html.split('id="filtros"')[1].split("</form>")[0]
        # El buscador va solo en su fila; debajo, las pastillas y «Ordenar» al final.
        self.assertLess(form.index('id="q"'), form.index('class="pastillas"'))
        fila = form.split('class="pastillas"')[1].split('id="mas-filtros"')[0]
        self.assertNotIn('id="q"', fila)
        self.assertLess(fila.index('id="btn-filtros"'), fila.index('name="pronto"'))
        self.assertLess(fila.index('name="teletrabajo"'), fila.index('id="orden-campo"'))
        self.assertIn('<label for="q" class="sr-only">', form)
        # Sin banner de empresas: se filtra con el selector del panel.
        self.assertNotIn('class="empresas"', html)
        self.assertNotIn("button[data-empresa]", html)
        self.assertIn('id="empresa"', self.panel(html))
        # «Quitar filtros», junto al recuento y ligado al formulario; oculto hasta que haya filtros.
        resultados = html.split('class="resultados"')[1].split("</div>\n")[0]
        self.assertNotIn('type="reset"', form)
        self.assertIn('<button type="reset" form="filtros" class="quitar" hidden>Quitar filtros</button>', resultados)
        # El orden, junto al recuento y ligado al formulario.
        self.assertIn('<select id="orden" name="orden">', fila)
        self.assertNotIn('id="orden"', resultados)
        self.assertIn('<option value="empresa">', html)
        self.assertIn('data-procesos="anuncios/"', html)

    def test_acerca_explica_busqueda_avisos_y_datos(self):
        portada = self.read("index.html")
        self.assertNotIn("Ver en la web oficial", portada)  # sin notas por fuente al pie
        self.assertIn('<a class="como-buscar" href="acerca/#como-buscar">', portada)
        acerca = self.read("acerca/index.html")
        for key in ("que-hay", "antes-de-inscribirte", "como-buscar", "guardar", "avisos", "datos", "responsabilidad", "datos-personales",
                    "accesibilidad", "contacto"):
            self.assertIn(f'href="#{key}"', acerca)
            self.assertIn(f'id="{key}"', acerca)
        self.assertIn("adm trag", acerca)
        self.assertIn(f"Titular del portal: {site.TITULAR}", acerca)
        self.assertIn(f'href="mailto:{site.CONTACTO}"', acerca)
        self.assertIn('<a href="acerca/#quien">Aviso legal y privacidad</a>', portada.split("<footer")[1])
        self.assertIn('href="../datos/"', acerca)
        self.assertIn('href="../datos/"', self.read("avisos/index.html"))

    def test_menu_con_acerca_y_accesibilidad_en_el_pie(self):
        html = self.read("index.html")
        nav = html.split('id="nav-principal"')[1].split("</nav>")[0]
        self.assertEqual(nav.count("<li>"), 6)
        labels = re.findall(r"<a [^>]*>([^<]+)</a>", nav)  # Procesos tras Ofertas, Histórico al final
        self.assertEqual(labels, ["Ofertas", "Procesos", "Organismos", "Avisos", "Acerca de", "Histórico"])
        self.assertIn(">Procesos</a>", nav)
        self.assertIn('<a href="acerca/">Acerca de</a>', nav)
        self.assertIn('aria-current="page">Acerca de</a>', self.read("acerca/index.html").split("</nav>")[0])
        footer = html.split('<footer')[1]
        self.assertNotIn("Acerca de", footer)
        self.assertIn('<a href="accesibilidad/">Accesibilidad</a>', footer)
        self.assertIn('aria-current="page">Accesibilidad</a>', self.read("accesibilidad/index.html").split("<footer")[1])
        self.assertIn("accesibilidad/", self.read("sitemap.xml"))
        # Los controles van antes del menú: abierto en móvil, el foco pasa del botón a sus enlaces.
        self.assertLess(html.index('id="btn-menu"'), html.index('id="nav-principal"'))

    def test_busqueda_por_texto_del_contrato(self):
        record = offer("5", kind="indefinido", contract="Durada determinada", category="Específica")
        texto = site.plain_search(record)
        for palabra in ("durada determinada", "especifica", "indefinido"):
            self.assertIn(palabra, texto)

    def test_filtro_de_area_en_lugar_de_tipo_de_puesto(self):
        html = self.read("index.html")
        plegado = self.panel(html)
        self.assertIn('<select id="area" name="area"><option value="">Todas</option>', plegado)
        self.assertIn('<option value="ninguna">Sin área</option>', plegado)
        self.assertIn('data-area="ninguna"', html)
        self.assertNotIn('id="familia"', html)
        # El dato literal de la fuente sigue en la ficha.
        self.assertIn("Apoyo Administrativo", self.read("ofertas/tragsa-1/index.html"))

    def test_portada_sin_titulo_ni_resumen_visibles(self):
        html = self.read("index.html")
        self.assertIn('<h1 class="sr-only">', html)
        self.assertNotIn('class="resumen"', html)

    def test_anuncios_con_buscador_y_organismo(self):
        html = self.read("anuncios/index.html")
        for campo in ('id="filtros"', 'id="q"', 'id="organismo"', 'id="tipo"', 'id="lista-ofertas"', "data-texto="):
            self.assertIn(campo, html)
        self.assertIn("Grupo Tragsa", html.split('id="lista-ofertas"')[1])

    def test_guardadas_en_ofertas_procesos_y_ficha(self):
        portada = self.read("index.html")
        self.assertIn('data-guardar="o:tragsa-2"', portada)
        # La pastilla espera oculta en la fila de pastillas, antes de «Ordenar»; filtros.js la usa como casilla.
        fila = portada.split('class="pastillas"')[1].split('id="mas-filtros"')[0]
        self.assertRegex(fila, r'<label class="pastilla" id="pastilla-guardadas" data-tipo="o" hidden>'
                               r'<input type="checkbox" name="guardadas" value="1"> Guardadas')
        self.assertLess(fila.index('name="guardadas"'), fila.index('id="orden-campo"'))
        self.assertIn('"guardadas"', self.read("assets/filtros.js"))
        # guardadas.js marca las tarjetas antes de que filtros.js filtre.
        self.assertLess(portada.index("assets/guardadas.js"), portada.index("assets/filtros.js"))
        self.assertRegex(portada, r'guardadas\.js"[^>]*defer')
        anuncios = self.read("anuncios/index.html")
        self.assertIn('data-tipo="p" hidden><input type="checkbox" name="guardadas" value="1"> Guardados', anuncios)
        self.assertRegex(anuncios.split('id="lista-ofertas"')[1], r'data-guardar="p:[0-9a-f]{10}"')
        self.assertIn('data-guardar="p:', self.read("historico/procesos/index.html"))
        self.assertIn('data-guardar="o:tragsa-2"', self.read("organismos/tragsa/index.html"))
        # Ficha abierta y cerrada: un hueco oculto bajo el título para el botón.
        for ref in ("2", "3"):
            self.assertIn(f'<p class="guardar-ficha" data-guardar="o:tragsa-{ref}" hidden></p>',
                          self.read(f"ofertas/tragsa-{ref}/index.html"))
        self.assertIn("solo en este navegador", self.read("acerca/index.html"))

    def test_historico_con_buscador_solo_si_hay_cerradas(self):
        html = self.read("historico/index.html")
        self.assertIn('id="filtros"', html)
        self.assertIn('data-empresa="', html)
        vacio = site.history_page([], "ahora")
        self.assertNotIn('id="filtros"', vacio)

    def test_cerrada_conservada_sin_boton_de_inscripcion(self):
        html = self.read("ofertas/tragsa-3/index.html")
        self.assertIn("está cerrada", html)
        self.assertNotIn("Inscribirse", html)
        self.assertIn("ofertas/tragsa-3/", self.read("historico/index.html"))

    def test_abierta_enlaza_a_inscripcion_oficial(self):
        self.assertIn("https://www.tragsa.es/i/1", self.read("ofertas/tragsa-1/index.html"))

    def test_republicacion_visible(self):
        self.assertIn("nueva publicación de la oferta 77", self.read("ofertas/tragsa-4/index.html"))

    def test_urgencia_no_depende_solo_del_color(self):
        self.assertIn("Finaliza mañana.", self.read("index.html"))

    def test_mayusculas_sostenidas_se_normalizan(self):
        html = self.read("anuncios/index.html")
        self.assertIn("Se publican las bases de Tragsa", html)
        self.assertNotIn("SE PUBLICAN", html)

    def test_declara_no_oficial_en_cada_pagina(self):
        for path in self.pages():
            self.assertIn("no oficial", path.read_text(encoding="utf-8"), path)

    def test_feeds_validos_y_con_novedades(self):
        root = ET.fromstring(self.read("feed.xml"))
        titles = [item.findtext("title") for item in root.iter("item")]
        guids = [item.findtext("guid") for item in root.iter("item")]
        self.assertEqual(len(guids), len(set(guids)))
        self.assertTrue(any(t.startswith("Plazo modificado: ") for t in titles))
        self.assertTrue(any("bases de Tragsa" in t for t in titles))
        self.assertTrue(all(item.findtext("pubDate") for item in root.iter("item")))

    def test_feeds_por_comunidad_y_empresa(self):
        galicia = ET.fromstring(self.read("feeds/comunidad-galicia.xml"))
        self.assertEqual({i.findtext("link") for i in galicia.iter("item")}, {BASE + "ofertas/tragsa-2/"})
        empty = ET.fromstring(self.read("feeds/comunidad-cantabria.xml"))
        self.assertEqual(list(empty.iter("item")), [])
        self.assertTrue((self.out / "feeds/empresa-tragsa.xml").exists())

    def test_feeds_por_area_y_teletrabajo(self):
        links = lambda path: {i.findtext("link") for i in ET.fromstring(self.read(path)).iter("item")}
        self.assertEqual(links("feeds/area-tic.xml"), {BASE + "ofertas/tragsa-5/"})
        self.assertEqual(links("feeds/area-sanidad.xml"), set())
        self.assertTrue(all((self.out / f"feeds/area-{a}.xml").exists() for a in areas.AREAS))
        self.assertEqual(links("feeds/teletrabajo.xml"), {BASE + "ofertas/tragsa-4/"})
        avisos = self.read("avisos/index.html")
        self.assertIn(f'Por área <span class="dato">({len(areas.AREAS)})</span>', avisos)
        self.assertIn('href="../feeds/area-tic.xml"', avisos)
        self.assertIn('href="../feeds/teletrabajo.xml"', avisos)

    def test_api_publica_sin_campos_internos(self):
        data = json.loads(self.read("api/ofertas.json"))
        self.assertEqual(len(data["ofertas"]), 5)
        self.assertNotIn("sections", data["ofertas"][0])
        self.assertNotIn("portal_tries", data["ofertas"][0])

    def test_api_v1_en_castellano(self):
        """Contrato público: cambiar estas claves obliga a subir API_VERSION y avisar en el README."""
        for name in ("ofertas", "novedades", "procesos", "listas"):
            data = json.loads(self.read(f"api/{name}.json"))
            self.assertEqual((data["version"], data["documentacion"]), (1, BASE + "datos/"), name)
            self.assertIn("CC BY 4.0", data["licencia"])
        ofertas = {o["id"]: o for o in json.loads(self.read("api/ofertas.json"))["ofertas"]}
        self.assertEqual(list(ofertas["tragsa:2"]), [
            "id", "organismo", "codigo", "titulo", "titulo_original", "empresa", "estado", "ubicacion", "localidad",
            "comunidad", "ccaa", "provincia", "municipio", "plazas", "tipo_contrato", "contrato", "convocatoria", "tipo_puesto",
            "departamento", "plazo_inicio", "plazo_fin", "plazo_hora", "publicada", "detectada", "cerrada",
            "republica", "areas", "teletrabajo", "teletrabajo_estado", "teletrabajo_detalle",
            "url", "url_inscripcion", "url_portal"])
        self.assertEqual((ofertas["tragsa:2"]["estado"], ofertas["tragsa:3"]["estado"]), ("abierta", "cerrada"))
        self.assertEqual(ofertas["tragsa:4"]["republica"], "77")
        self.assertEqual(ofertas["tragsa:2"]["url_portal"], BASE + "ofertas/tragsa-2/")
        proceso = next(p for p in json.loads(self.read("api/procesos.json"))["procesos"] if p["nombre"] == "PROCESO ABIERTO (AB-1)")
        self.assertEqual((proceso["tipo"], proceso["acceso"], proceso["estado"], proceso["plazo_fin"], proceso["url_inscripcion"]),
                         ("tasa", "libre", "abierto", "2026-11-10", "https://plataforma.example/entrar"))
        self.assertEqual(proceso["comunicados"], [{"fecha": "2026-11-03", "titulo": "Plazo", "url": "https://www.tragsa.es/p",
                                                   "detectado": "2026-11-07T00:00:00+00:00"}])
        listas = json.loads(self.read("api/listas.json"))
        for clave, valor in (("tipos_contrato", "temporal"), ("tipos_proceso", "tasa"), ("accesos", "libre"),
                             ("sistemas", "concurso-oposicion"), ("estados_proceso", "abierto"), ("grupos", "sepi")):
            self.assertIn(valor, {i["id"] for i in listas[clave]}, clave)

    def test_datos_abiertos_documenta_todas_las_claves(self):
        """«Datos abiertos» describe cada clave de la API: una clave nueva sin documentar hace fallar el test."""
        documented = lambda fields: {key for keys, _ in fields for key in keys}
        novedades = json.loads(self.read("api/novedades.json"))
        self.assertEqual(set(novedades) - {"dias", "novedades"}, documented(site.FILE_FIELDS))
        self.assertEqual({k for o in json.loads(self.read("api/ofertas.json"))["ofertas"] for k in o},
                         documented(site.OFFER_FIELDS))
        self.assertEqual({k for p in json.loads(self.read("api/procesos.json"))["procesos"] for k in p},
                         documented(site.PROCESS_FIELDS))
        self.assertEqual({k for n in novedades["novedades"] for k in n}, documented(site.NEWS_FIELDS))
        self.assertEqual(set(json.loads(self.read("api/listas.json"))) - documented(site.FILE_FIELDS),
                         documented(site.LIST_FIELDS))
        datos = self.read("datos/index.html")
        self.assertEqual(datos.count('<table class="campos">'), 5)
        self.assertIn('<form id="buscar-campos"', datos)
        self.assertIn("api/ofertas.json | jq", datos)  # ejemplo con la URL absoluta de la API
        self.assertIn("(Invoke-RestMethod " + BASE + "api/ofertas.json)", datos)  # y para Windows
        self.assertIn("api/procesos.json | jq", datos)
        self.assertEqual(datos.count('class="ejemplo-bloque"'), 9)
        self.assertIn('src="../assets/datos.js"', datos)
        self.assertTrue((site.ASSETS / "datos.js").exists())
        self.assertIn('aria-current="page">Datos abiertos</a>', datos.split("<footer")[1])
        self.assertIn("datos/", self.read("sitemap.xml"))

    def test_prevalece_la_web_oficial_en_la_ficha_y_no_en_el_pie(self):
        ficha = self.read("ofertas/tragsa-1/index.html")
        self.assertNotIn("prevalece", ficha.split('<footer class="sitio">')[1])
        self.assertIn("prevalece la información publicada por el organismo", ficha)
        self.assertEqual(self.read("acerca/index.html").count("prevalece"), 1)

    def test_api_con_codigos_ine(self):
        data = json.loads(self.read("api/ofertas.json"))
        for offer in data["ofertas"]:
            self.assertTrue({"ccaa", "provincia", "municipio"} <= offer.keys(), offer["id"])

    def test_api_de_novedades_para_los_avisos(self):
        data = json.loads(self.read("api/novedades.json"))
        items = {i["id"]: i for i in data["novedades"]}
        ofertas = [i for i in items.values() if i["tipo"] == "oferta"]
        # Solo altas y republicaciones de ofertas abiertas: ni cambios de plazo ni cerradas.
        self.assertEqual({i["id"].split("/")[0] for i in ofertas}, {"tragsa:1", "tragsa:2", "tragsa:4", "tragsa:5"})
        galicia = next(i for i in ofertas if i["id"].startswith("tragsa:2/"))
        self.assertEqual((galicia["ccaa"], galicia["organismo"]), ("12", "tragsa"))
        self.assertEqual(galicia["url"], BASE + "ofertas/tragsa-2/")
        self.assertIsInstance(galicia["areas"], list)
        comunicados = [i for i in items.values() if i["tipo"] == "comunicado"]
        self.assertEqual(len(comunicados), 6)
        self.assertTrue(all(i["proceso"] and i["url"] for i in comunicados))
        # Cada comunicado se enlaza con su proceso por el id, aunque el nombre aquí vaya en minúsculas.
        procesos = {p["id"]: p for p in json.loads(self.read("api/procesos.json"))["procesos"]}
        self.assertTrue(all(i["proceso_id"] in procesos for i in comunicados))
        abierto = next(i for i in comunicados if i["titulo"] == "Plazo")
        self.assertEqual(abierto["proceso"], "Proceso abierto (AB-1)")
        self.assertEqual(procesos[abierto["proceso_id"]]["nombre"], "PROCESO ABIERTO (AB-1)")

    def test_api_de_procesos_y_listas(self):
        procesos = json.loads(self.read("api/procesos.json"))["procesos"]
        self.assertEqual(len(procesos), 5)
        self.assertNotIn("first_seen", procesos[0]["comunicados"][0])
        # «Datos abiertos» promete una lista RSS por proceso en marcha, con su id.
        self.assertIn("feeds/proceso-<var>id</var>.xml", self.read("datos/index.html"))
        for proceso in procesos:
            en_marcha = proceso["estado"] in ("abierto", "curso")
            self.assertEqual((self.out / f"feeds/proceso-{proceso['id']}.xml").exists(), en_marcha, proceso["nombre"])
        listas = json.loads(self.read("api/listas.json"))
        self.assertEqual(len(listas["comunidades"]), 19)
        self.assertEqual(len(listas["provincias"]), 52)
        self.assertIn({"provincia": "03", "nombre": "Alicante", "ccaa": "10"}, listas["provincias"])
        self.assertIn({"provincia": "15", "nombre": "A Coruña", "ccaa": "12"}, listas["provincias"])
        self.assertIn("tragsa", {o["id"] for o in listas["organismos"]})
        self.assertTrue(all(o["url"].startswith("https://") for o in listas["organismos"]))
        self.assertIn("tic", {a["id"] for a in listas["areas"]})

    def test_teletrabajo_con_la_frase_literal_y_sin_inventar(self):
        portada = self.read("index.html")
        self.assertIn('name="teletrabajo"', portada)
        # Las ofertas 1 y 2 solo tienen «Tareas»: no se sabe, y se dice.
        self.assertIn("En 2 ofertas no es posible comprobarlo", portada)
        tarjetas = {m.group(1): m.group(0) for m in re.finditer(r'<li data-texto="[^"]*" .*?href="ofertas/tragsa-(\d)/".*?</li>', portada, re.S)}
        self.assertIn('data-teletrabajo="1"', tarjetas["4"])
        self.assertIn("Menciona teletrabajo: hasta el 50 %", tarjetas["4"])
        self.assertIn('data-teletrabajo="0"', tarjetas["5"])
        self.assertIn("«Posibilidad de trabajo a distancia hasta el 50 % de la jornada.»", self.read("ofertas/tragsa-4/index.html"))
        self.assertIn("La ficha no lo menciona", self.read("ofertas/tragsa-5/index.html"))
        self.assertIn("No consta: consulte las bases", self.read("ofertas/tragsa-1/index.html"))
        api = {o["id"]: o for o in json.loads(self.read("api/ofertas.json"))["ofertas"]}
        self.assertEqual([api[f"tragsa:{r}"]["teletrabajo"] for r in "145"],
                         [None, "Posibilidad de trabajo a distancia hasta el 50 % de la jornada.", False])
        self.assertEqual([(api[f"tragsa:{r}"]["teletrabajo_estado"], api[f"tragsa:{r}"]["teletrabajo_detalle"]) for r in "145"],
                         [("no_consta", None), ("menciona", "hasta el 50 %"), ("no_menciona", None)])
        self.assertIsInstance(api["tragsa:1"]["areas"], list)
        novedades = {i["id"].split("/")[0]: i for i in json.loads(self.read("api/novedades.json"))["novedades"]}
        self.assertTrue(novedades["tragsa:4"]["teletrabajo"])
        self.assertEqual(novedades["tragsa:4"]["teletrabajo_estado"], "menciona")
        # «Sin teletrabajo» solo con la frase de la ficha; no entra en el filtro ni en el RSS de teletrabajo.
        presencial = offer("9", sections=[{"title": "Lugar", "level": 2, "html": RELLENO + "<p>Móstoles. 100% presencial</p>"}])
        self.assertEqual(site.remote_fields(presencial),
                         {"teletrabajo": False, "teletrabajo_estado": "sin", "teletrabajo_detalle": None})
        tarjeta = site.offer_card(presencial, NOW.date())
        self.assertIn('data-teletrabajo="0"', tarjeta)
        self.assertNotIn("teletrabajo:", tarjeta.lower().split("data-guardar")[1])
        self.assertIn("Sin teletrabajo, según la ficha: «Móstoles. 100% presencial»",
                      site.offer_page(presencial, {s.id: s for s in site.ACTIVE}, NOW.date(), ""))

    def test_comunicados_sin_fecha_por_deteccion_y_lo_que_ya_estaba_al_final(self):
        base = {"source": "sepi", "process": "P", "url": "u", "state": "curso", "date": ""}
        primera = {**base, "first_seen": "2026-11-01T08:00:00+00:00", "baseline": True}
        notices = [
            {**primera, "title": "Bases", "position": 2},
            {**primera, "title": "Estado", "position": 0},
            {**primera, "title": "Admitidos", "position": 1},
            {**base, "title": "Resolución nueva", "first_seen": "2026-11-09T10:00:00+00:00", "position": 0},
            {**base, "title": "Con fecha", "date": "2026-11-05", "first_seen": "2026-11-05T09:00:00+00:00"},
        ]
        (proceso,) = site.processes(notices)
        self.assertEqual([c["titulo"] for c in proceso["comunicados"]],
                         ["Resolución nueva", "Con fecha", "Estado", "Admitidos", "Bases"])
        self.assertEqual([c["fecha"] for c in proceso["comunicados"]], [None, "2026-11-05", None, None, None])
        # Un proceso del que solo se sabe lo que ya estaba va detrás de cualquiera con fecha.
        otro = {**base, "process": "Q", "title": "Q1", "date": "2026-10-01", "first_seen": "2026-11-01T08:00:00+00:00"}
        self.assertEqual([p["nombre"] for p in site.processes(notices[:3] + [otro])], ["Q", "P"])

    def test_ubicacion_de_los_procesos_sin_municipio(self):
        base = {"source": "puertos", "url": "u", "state": "curso", "date": "", "first_seen": "2026-11-06T10:00:00+00:00"}
        notices = [{**base, "process": "A", "title": "a", "location": "Pasaia"},
                   {**base, "process": "B", "title": "b", "location": "Vilagarcía"},  # nombre corto, no oficial
                   {**base, "process": "C", "title": "c"}]  # guardado antes de existir el dato
        api = {p["nombre"]: p for p in site.processes(notices)}
        self.assertEqual((api["A"]["ubicacion"], api["A"]["ccaa"], api["A"]["provincia"]), ("Pasaia", "16", "20"))
        self.assertNotIn("municipio", api["A"])
        self.assertEqual((api["B"]["ubicacion"], api["B"]["ccaa"]), ("Vilagarcía", None))  # no deja claro dónde
        self.assertEqual((api["C"]["ubicacion"], api["C"]["ccaa"], api["C"]["provincia"]), (None, None, None))
        novedades = site.news({}, [], notices, {}, BASE, NOW)
        self.assertEqual({n["proceso"]: n["ccaa"] for n in novedades}, {"A": "16", "B": None, "C": None})

    def test_sin_menciones_no_hay_casilla(self):
        portada = site.index_page([offer("1")], NOW.date(), "hoy", {})
        self.assertNotIn('name="teletrabajo"', portada)

    def test_telegram_solo_si_hay_bot(self):
        self.assertNotIn("Telegram", self.read("avisos/index.html"))
        self.assertNotIn("Telegram", self.read("acerca/index.html"))
        avisos = site.alerts_page([], [], "hoy", bot="@empleo_bot")
        self.assertIn('href="https://t.me/empleo_bot"', avisos)
        self.assertIn('href="#telegram"', avisos)
        self.assertIn('id="telegram"', avisos)
        self.assertIn('href="#rss"', avisos)
        self.assertIn('id="rss"', avisos)
        self.assertIn("/baja", site.about_page({}, "hoy", bot="empleo_bot"))

    def test_correo_solo_si_hay_clave_de_turnstile(self):
        avisos = self.read("avisos/index.html")
        self.assertNotIn("form-correo", avisos)
        self.assertNotIn(site.TURNSTILE, avisos)
        self.assertNotIn("avisos-correo", self.read("acerca/index.html"))

    def test_formulario_de_correo(self):
        organismos = [("Grupo SEPI", [("tragsa", "Grupo Tragsa"), ("enusa", "Enusa")])]
        html = site.alerts_page([], [], "hoy", sitekey="clave-publica", mail_organisms=organismos)
        self.assertIn(f'<form class="form-correo" method="post" action="{site.AVISOS_URL}/correo/alta">', html)
        self.assertIn('name="correo" type="email" autocomplete="email" required', html)
        self.assertIn('<div class="cf-turnstile" data-sitekey="clave-publica" data-language="es"></div>', html)
        self.assertIn(f'<script src="{site.TURNSTILE}/turnstile/v0/api.js" async defer></script>', html)
        # Las casillas llevan las claves de api/listas.json, que son las que valida el worker.
        listas = site.lists({})
        for area in listas["areas"]:
            self.assertIn(f'name="areas" value="{area["id"]}"', html)
        for comunidad in listas["comunidades"]:
            self.assertIn(f'name="ccaa" value="{comunidad["ccaa"]}"', html)
        self.assertIn('<input type="checkbox" name="organismos" value="tragsa"> Grupo Tragsa</label>', html)
        self.assertIn('name="sin_ccaa" value="1" checked', html)
        self.assertIn('href="#correo"', html)
        self.assertIn("de dos formas", html)
        self.assertIn("de tres formas", site.alerts_page([], [], "hoy", bot="bot", sitekey="c"))
        # La CSP se abre solo en esta página, para Turnstile y para enviar el formulario al worker.
        self.assertIn(f"script-src 'self' {site.TURNSTILE}; frame-src {site.TURNSTILE};", html)
        self.assertIn(f"form-action 'self' {site.AVISOS_URL}", html)
        self.assertIn(f'content="{site.CSP}"', site.alerts_page([], [], "hoy"))

    def test_privacidad_del_correo(self):
        acerca = site.about_page({}, "hoy", mail=True)
        self.assertIn('id="avisos-correo"', acerca)
        self.assertIn("Piensa Solutions", acerca)
        self.assertIn("solo solicita datos personales para los avisos", acerca)
        self.assertIn("por correo electrónico o RSS", acerca)
        self.assertIn("formulario de avisos por correo", site.accessibility_page("hoy", mail=True))
        self.assertNotIn("formulario de avisos por correo", site.accessibility_page("hoy"))

    def test_avisos_en_grupos_plegados_con_buscador(self):
        html = site.alerts_page([("Galicia", "feeds/comunidad-galicia.xml")],
                                [("Grupo SEPI", [("Grupo Tragsa", "feeds/organismo-tragsa.xml", [])])], "hoy")
        self.assertEqual(html.count('<details class="grupo-listas">'), 2)  # cerrados de inicio
        self.assertIn("Por comunidad <span class=\"dato\">(1)</span>", html)
        self.assertIn('<form id="buscar-listas" class="buscador" role="search" aria-label="Buscar listas" hidden>', html)
        self.assertIn('<caption class="sr-only">Por comunidad</caption>', html)
        self.assertIn('<tr><th scope="row"><a href="../feeds/comunidad-galicia.xml">Galicia</a></th>'
                      '<td><button type="button" class="copiar" hidden>'
                      'Copiar<span class="sr-only"> el enlace de Galicia</span></button></td></tr>', html)
        # Las listas generales siguen como lista, con su botón al lado.
        self.assertIn('<li><a href="../feed.xml">Todas las novedades</a><button type="button" class="copiar" hidden>', html)
        self.assertIn('src="../assets/listas.js"', html)
        self.assertTrue((site.ASSETS / "listas.js").exists())

    def test_avisos_por_organismo_en_grupos_y_empresas_debajo(self):
        grupos = [("Grupo SEPI", [("Enusa", "feeds/organismo-enusa.xml", []),
                                  ("Grupo Tragsa", "feeds/organismo-tragsa.xml",
                                   [("Solo Tragsa", "feeds/empresa-tragsa.xml"),
                                    ("Solo Tragsatec", "feeds/empresa-tragsatec.xml")])]),
                  ("Otras empresas del Estado", [("ENAIRE", "feeds/organismo-enaire.xml", [])])]
        html = site.alerts_page([], grupos, "hoy")
        self.assertIn('Por organismo <span class="dato">(3)</span>', html)
        self.assertNotIn("Por empresa", html)
        self.assertIn('<table class="tabla-listas"><caption>Grupo SEPI</caption>', html)
        self.assertLess(html.index("<caption>Grupo SEPI</caption>"), html.index("<caption>Otras empresas del Estado</caption>"))
        self.assertEqual(html.count('<th scope="col">Enlace</th>'), 3)  # comunidad y dos grupos
        self.assertIn('el enlace de Grupo Tragsa</span></button></td></tr>'
                      '<tr class="sublista"><th scope="row"><a href="../feeds/empresa-tragsa.xml">Solo Tragsa</a>', html)
        self.assertEqual(html.count('<tr class="sublista">'), 2)
        # En la web generada: listas de empresa siguen existiendo aunque no se enseñen sueltas.
        avisos = self.read("avisos/index.html")
        self.assertNotIn("Por empresa", avisos)
        self.assertIn('<caption>Grupo SEPI</caption>', avisos)
        # La matriz encabeza su grupo y se distingue de él.
        self.assertIn('<caption>Grupo SEPI</caption>\n<thead><tr><th scope="col">Lista</th><th scope="col">Enlace</th></tr></thead>\n'
                      '<tbody><tr><th scope="row"><a href="../feeds/organismo-sepi.xml">SEPI (matriz)</a>', avisos)
        self.assertTrue((self.out / "feeds/empresa-tragsa.xml").exists())

    def test_paginas_y_feed_por_organismo(self):
        listing = self.read("organismos/index.html")
        self.assertIn('href="tragsa/"', listing)
        self.assertIn("Enusa", listing)
        page = self.read("organismos/tragsa/index.html")
        self.assertIn('href="../../ofertas/tragsa-1/"', page)
        self.assertNotIn("Oferta 3", page)  # la cerrada no aparece
        feed = ET.fromstring(self.read("feeds/organismo-tragsa.xml"))
        self.assertTrue(list(feed.iter("item")))
        self.assertIn("feeds/organismo-tragsa.xml", self.read("avisos/index.html").replace("../", ""))

    def test_organismo_busca_en_la_portada_filtrada(self):
        sources = {"a": type("S", (), {"id": "a", "name": "Uno", "homepage": "https://a.example/"})()}
        offers = [{"source": "a", "title": f"Puesto {n}", "ref": str(n), "first_seen": "2026-11-01T00:00:00",
                   "url": f"https://a.example/{n}"}
                  for n in (1, 2)]
        html = site.organism_page(sources["a"], offers, NOW.date(), "ahora")
        form = html.split('<form class="buscador"')[1].split("</form>")[0]
        self.assertIn('action="../../" method="get"', form)
        self.assertIn('<input type="hidden" name="organismo" value="a">', form)
        self.assertIn('name="q"', form)
        self.assertIn("Buscar en las 2 ofertas de Uno", form)  # etiqueta accesible
        self.assertLess(html.index("<form"), html.index('<ol class="ofertas">'))
        # El navegador debe dejar enviarlo: la política de contenido permite formularios propios.
        self.assertIn("form-action 'self'", html)
        una = site.organism_page(sources["a"], offers[:1], NOW.date(), "ahora")
        self.assertNotIn("<form", una)

    def test_volver_arriba_desde_el_pie(self):
        for path in ("index.html", "organismos/index.html", "avisos/index.html"):
            html = self.read(path)
            # El destino es el body: la cabecera es sticky en móvil y, como destino, apenas desplazaba.
            self.assertIn('<body id="arriba">', html)
            self.assertIn('<header class="sitio">', html)
            pie = html.split('<footer class="sitio">')[1]
            self.assertIn('<a href="#arriba">Volver arriba</a>', pie)
            # Flotante: oculto sin JS; el script lo muestra al bajar.
            self.assertIn('<a class="subir-flotante" id="subir-flotante" href="#arriba" hidden>', html)
            self.assertIn("assets/subir.js", html)
        self.assertTrue((site.ASSETS / "subir.js").exists())

    def test_apariencia_en_un_boton_de_la_cabecera(self):
        html = self.read("index.html")
        self.assertNotIn('id="franja"', html)
        acciones = html.split('<div class="cab-acciones">')[1].split("</div>")[0]
        # Sin JS no hace nada: nace oculto. Va antes de «Menú».
        self.assertIn('<button type="button" id="btn-aa" class="btn-cab" aria-haspopup="dialog" hidden>', acciones)
        self.assertIn('<span class="aa-texto">Apariencia</span>', acciones)
        self.assertLess(acciones.index('id="btn-aa"'), acciones.index('id="btn-menu"'))
        # El diálogo enlaza a la página de accesibilidad, con la ruta de cada página.
        dialogo = html.split('<dialog id="ajustes"')[1].split("</dialog>")[0]
        self.assertIn('<a href="accesibilidad/">Accesibilidad del portal</a>', dialogo)
        self.assertIn('<a href="../accesibilidad/">', self.read("acerca/index.html").split('<dialog id="ajustes"')[1])

    def test_organismos_sin_ofertas_no_son_enlace(self):
        def source(ident, name):
            return type("S", (), {"id": ident, "name": name, "homepage": f"https://{ident}.example/",
                                  "group": "sepi", "scope": "Estatal"})()
        sources = {"a": source("a", "Con ofertas"), "b": source("b", "Sin ofertas")}
        html = site.organisms_page(sources, [{"source": "a"}], "ahora")
        con, sin = html.split("Sin ofertas abiertas en este momento")
        self.assertIn('href="a/"', con)
        self.assertNotIn('href="b/"', html)
        self.assertIn("Sin ofertas", sin)
        self.assertIn("https://b.example/", sin)
        self.assertNotIn("0 ofertas abiertas", html)

    def test_matriz_primera_de_su_grupo(self):
        def source(ident, name):
            return type("S", (), {"id": ident, "name": name, "homepage": f"https://{ident}.example/",
                                  "group": "sepi", "scope": "Estatal"})()
        sources = {"a": source("a", "Agencia"), "sepi": source("sepi", "SEPI"), "z": source("z", "Zeta")}
        html = site.organisms_page(sources, [{"source": "a"}, {"source": "sepi"}, {"source": "a"}], "ahora")
        self.assertLess(html.index("SEPI (matriz)"), html.index("Agencia"))  # aunque tenga menos ofertas
        con, sin = html.split("Sin ofertas abiertas en este momento")
        self.assertIn('<a href="sepi/">SEPI (matriz)</a>', con)
        self.assertNotIn("(matriz)", sin)

    def test_organismo_solo_con_procesos_tiene_pagina_y_los_muestra(self):
        def source(ident, name):
            return type("S", (), {"id": ident, "name": name, "homepage": f"https://{ident}.example/",
                                  "group": "sepi", "scope": "Estatal"})()
        sources = {"a": source("a", "Con ofertas"), "r": source("r", "Solo procesos"), "b": source("b", "Nada")}
        html = site.organisms_page(sources, [{"source": "a"}], "ahora", {"r": 21})
        con, sin = html.split("Sin ofertas abiertas en este momento")
        self.assertIn('href="r/"', con)
        self.assertIn('<p class="dato">21 procesos en marcha</p>', con)
        self.assertIn("1 oferta abierta · 21 procesos en marcha", con)
        self.assertNotIn("0 ofertas abiertas", html)
        self.assertIn("Nada", sin)
        # Su página: sin ofertas que filtrar, y los procesos debajo, en su sección.
        page = self.read("organismos/tragsa/index.html")
        self.assertIn('<section class="procesos"', page)
        self.assertIn("<h3><a", page.split('<section class="procesos"')[1])
        self.assertLess(page.index('href="../../ofertas/tragsa-1/"'), page.index('<section class="procesos"'))
        sola = site.organism_page(sources["r"], [], NOW.date(), "ahora")
        self.assertIn("No tiene ofertas abiertas en este momento", sola)
        self.assertNotIn('role="search"', sola)
        self.assertNotIn('<section class="procesos"', sola)

    def test_filtro_organismo_solo_con_varias_fuentes(self):
        def source(ident, name, group="sepi"):
            return type("S", (), {"id": ident, "name": name, "group": group})()
        one = {"tragsa": source("tragsa", "Tragsa")}
        two = {**one, "enusa": source("enusa", "Enusa")}
        offers = [offer("1"), offer("9", source="enusa")]
        self.assertNotIn('id="organismo"', site.index_page(offers, NOW.date(), "ahora", one))
        html = site.index_page(offers, NOW.date(), "ahora", two)
        self.assertIn('id="organismo"', html)
        self.assertIn('data-organismo="enusa"', html)
        self.assertIn('<optgroup label="Grupo SEPI"><option value="enusa">Enusa</option>', html)
        self.assertNotIn('id="grupo"', html)  # un solo grupo: no hay nada que elegir
        three = {**two, "aena": source("aena", "Aena", "estatal")}
        html = site.index_page(offers + [offer("8", source="aena")], NOW.date(), "ahora", three)
        self.assertIn('<label for="grupo">Grupo de organismos</label>', html)
        self.assertIn('data-grupo="estatal"', html)
        self.assertLess(html.index('<option value="sepi">'), html.index('<option value="estatal">'))
        self.assertLess(html.index('label="Grupo SEPI"'), html.index('label="Otras empresas del Estado"'))

    def test_ficha_de_efe_usa_ruta_sin_espacios_y_su_propio_boton(self):
        record = offer("CT2026 10-01", id="efe:CT2026 10-01", source="efe")
        self.assertEqual(site.offer_path(record), "ofertas/efe-ct2026-10-01/")
        efe = type("S", (), {"name": "Agencia EFE", "apply_label": "Ver las bases y cómo presentarse"})()
        html = site.offer_page(record, {"efe": efe}, NOW.date(), "ahora")
        self.assertIn("Ver las bases y cómo presentarse", html)
        self.assertNotIn("Inscribirse en la web oficial", html)

    def test_anuncios_indican_el_tipo_de_proceso(self):
        from empleo.model import process_type
        self.assertEqual(process_type("Tasa de reposición 2025-2026"), "tasa")
        self.assertEqual(process_type("Concurso-oposición Enusa 2026"), "otro")
        self.assertEqual(process_type("Banco de datos"), "bolsa")
        self.assertIn("Tasa de reposición", self.read("anuncios/index.html"))

    def test_el_sistema_de_seleccion_no_excluye_la_via(self):
        from empleo.model import selection_system
        self.assertEqual(selection_system("mediante concurso-oposición"), "concurso-oposicion")
        self.assertEqual(selection_system("Fase Concurso y examen de FASE II – Oposición"), "concurso-oposicion")
        self.assertEqual(selection_system("Examen de oposición"), "oposicion")
        self.assertEqual(selection_system("Listado definitivo – Fase Concurso"), "concurso")
        self.assertIsNone(selection_system("Listado de admitidos"))

    def test_anuncios_agrupados_por_proceso(self):
        html = self.read("anuncios/index.html")
        self.assertIn("Ver 1 comunicado anterior", html)
        self.assertIn("Convocatoria anterior (PDF)", html)
        self.assertIn('<a href="https://www.tragsa.es/proceso">Tasa</a>', html)
        self.assertIn("3 procesos en marcha, con 4 comunicados.", html)
        self.assertNotIn("procesos indefinidos", html)
        self.assertNotIn("en curso.</p>\n<ol", html)

    def test_inscripcion_abierta_primero_con_plazo_y_plataforma(self):
        html = self.read("anuncios/index.html")
        self.assertLess(html.index("Proceso abierto (AB-1)"), html.index(">Tasa</a>"))
        self.assertIn("Inscripción abierta", html)
        self.assertIn("https://plataforma.example/entrar", html)

    def test_filtros_de_anuncios_solo_con_valores_reales(self):
        html = self.read("anuncios/index.html")
        for campo in ('id="acceso"', 'id="sistema"', 'id="contrato"', 'data-acceso="libre"', 'data-sistema="concurso-oposicion"'):
            self.assertIn(campo, html)
        self.assertNotIn('value="oposicion"', html)
        self.assertNotIn('value="oep"', html)

    def test_comunicado_sin_fecha_no_rompe_la_pagina_ni_los_avisos(self):
        self.assertIn("Último comunicado. <a", self.read("anuncios/index.html"))
        self.assertIn("Sin fecha: Plazo cerrado", self.read("feeds/anuncios.xml"))

    def test_finalizados_en_su_pagina_y_no_entre_los_activos(self):
        live = self.read("anuncios/index.html")
        self.assertNotIn("Terminado", live)
        self.assertIn("Ver 2 procesos finalizados o sin novedades", live)
        closed = self.read("historico/procesos/index.html")
        self.assertIn("Terminado", closed)
        self.assertIn("Sin novedades en la web oficial", closed)
        self.assertNotIn(">Tasa</a>", closed)
        self.assertIn("historico/procesos/", self.read("sitemap.xml"))
        self.assertIn('href="procesos/"', self.read("historico/index.html"))

    def test_mayusculas_conservan_codigo_y_siglas(self):
        self.assertEqual(site.humane_caps("OPERARIO/A ALMACEN (865-OPEALM)"), "Operario/a almacen (865-OPEALM)")
        self.assertEqual(site.humane_caps("PERSONAL EN EL C.A. EL CABRIL"), "Personal en el C.A. el cabril")

    def test_avisos_de_anuncios_por_organismo_y_por_proceso(self):
        self.assertIn("Convocatoria anterior", self.read("feeds/organismo-tragsa.xml"))
        html = self.read("anuncios/index.html")
        feed = re.search(r'feeds/proceso-[0-9a-f]{10}\.xml', html).group(0)
        self.assertIn("<item>", self.read(feed))
        self.assertNotIn("Terminado", html)
        self.assertIn("incluyen solo ofertas", self.read("avisos/index.html"))

    def test_organismo_enlaza_a_sus_procesos(self):
        self.assertIn("anuncios/?organismo=tragsa", self.read("organismos/tragsa/index.html"))

    def test_la_convocatoria_se_ve_en_tarjeta_y_ficha(self):
        card = self.read("index.html")
        self.assertIn("Apoyo Administrativo · Específica · Temporal", card)
        sheet = next(self.out.glob("ofertas/*/index.html")).read_text(encoding="utf-8")
        self.assertIn("<dt>Convocatoria</dt><dd>Específica</dd>", sheet)

    def test_organismos_agrupados_por_entidad(self):
        html = self.read("organismos/index.html")
        self.assertIn('<h2 id="grupo-sepi">Grupo SEPI</h2>', html)
        self.assertIn('<h2 id="grupo-estatal">Otras empresas del Estado</h2>', html)
        self.assertLess(html.index("Grupo SEPI"), html.index("Otras empresas del Estado"))
        self.assertLess(html.index("Grupo SEPI"), html.index('href="tragsa/"'))
        self.assertLess(html.index("Otras empresas del Estado"), html.index("ENAIRE"))
        acerca = self.read("acerca/index.html")
        self.assertIn('<a href="../organismos/#grupo-sepi">Grupo SEPI</a> (', acerca)
        self.assertIn('<a href="../organismos/">Organismos</a>', acerca)
        self.assertNotIn("<h3>Grupo SEPI</h3>", acerca)

    def test_organismos_ordenados_con_indice_buscador_y_avisos(self):
        def source(ident, name, scope="Estatal"):
            return type("S", (), {"id": ident, "name": name, "homepage": f"https://{ident}.example/",
                                  "group": "sepi", "scope": scope})()
        sources = {k: source(k, n) for k, n in (("a", "Alfa"), ("b", "Beta"), ("c", "Gamma"), ("d", "Delta"))}
        sources["e"] = source("e", "Épsilon", "Galicia")
        offers = [{"source": s, "title": f"Puesto {n}", "ref": str(n), "first_seen": "2026-11-01T00:00:00",
                   "url": f"https://a.example/{n}"}
                  for n, s in enumerate("bba")]
        html = site.organisms_page(sources, offers, "ahora", {"c": 3}, bot="empleo_bot")
        # Más ofertas primero; luego más procesos.
        self.assertLess(html.index('href="b/"'), html.index('href="a/"'))
        self.assertLess(html.index('href="a/"'), html.index('href="c/"'))
        self.assertIn('<li><a href="#grupo-sepi">Grupo SEPI</a> <span class="dato">(5)</span></li>', html)
        self.assertIn('<form id="buscar-organismos" class="buscador" role="search" aria-label="Buscar organismos" hidden>', html)
        self.assertIn('<p id="estado-organismos" role="status"></p>', html)
        self.assertIn('data-texto="Épsilon Galicia"', html)
        self.assertIn('<details class="sin-ofertas-grupo"><summary>Sin ofertas abiertas en este momento <span class="dato">(2)</span>', html)
        self.assertIn('avisos por Telegram o RSS', html)
        self.assertIn('src="../assets/organismos.js"', html)
        self.assertTrue((site.ASSETS / "organismos.js").exists())
        self.assertIn("avisos por RSS</a>", site.organisms_page(sources, offers, "ahora"))
        ficha = site.organism_page(sources["b"], offers, NOW.date(), "ahora", bot="empleo_bot")
        self.assertIn('<a href="../../avisos/#telegram">por Telegram</a>', ficha)
        self.assertNotIn("#telegram", site.organism_page(sources["b"], offers, NOW.date(), "ahora"))

    def test_grupo_sin_organismos_no_aparece(self):
        fuente = type("S", (), {"group": "sepi"})()
        self.assertEqual([key for key, _, _ in site.by_group({"x": fuente})], ["sepi"])

    def test_ambito_autonomico_visible(self):
        sarga = type("S", (), {"id": "sarga", "name": "SARGA", "homepage": "https://sarga.example/",
                               "group": "autonomica", "scope": "Aragón"})()
        html = site.organisms_page({"sarga": sarga}, [{"source": "sarga"}], "ahora")
        self.assertIn("Empresas públicas autonómicas", html)
        self.assertIn("Aragón · <a", html)

    def test_contrato_con_el_texto_de_la_fuente(self):
        literal = "Contrato indefinido de actividades científico-técnicas (art. 23 bis Ley 14/2011)"
        record = offer("5", kind="indefinido", contract=literal)
        sheet = site.offer_page(record, self.sources(), NOW.date(), "ahora")
        self.assertIn(f"<dt>Contrato</dt><dd>{literal}</dd>", sheet)
        self.assertIn("Indefinido</span></p>", site.offer_card(record, NOW.date()))  # en la tarjeta, corto
        ambiguous = offer("6", kind=None, contract="Durada determinada / Indefinit")
        self.assertIn("Durada determinada / Indefinit</span></p>", site.offer_card(ambiguous, NOW.date()))
        self.assertIn("<dt>Contrato</dt><dd>No consta</dd>",
                      site.offer_page(offer("7", kind=None), self.sources(), NOW.date(), "ahora"))

    def test_abrir_original_y_compartir_en_la_ficha_no_en_la_tarjeta(self):
        record = offer("8", title="Técnico & analista")
        base = "https://ejemplo.org/"
        portal = base + site.offer_path(record)
        card = site.offer_card(record, NOW.date())
        self.assertNotIn("Abrir original", card)
        self.assertNotIn("Compartir", card)
        self.assertIn('<div class="tarjeta-acciones"></div>', card)  # el hueco de «Guardar»
        html = site.offer_page(record, self.sources(), NOW.date(), "ahora", base)
        self.assertIn('<a class="original" href="https://www.tragsa.es/f/8" target="_blank" rel="noopener">Abrir original', html)
        self.assertIn("(se abre en una pestaña nueva)</span>", html)
        self.assertIn(f'data-url="{portal}"', html)
        # Sin JavaScript, compartir abre el correo con el título y la ficha del portal.
        self.assertIn("mailto:?subject=T%C3%A9cnico%20%26%20analista&amp;body=", html)
        self.assertIn("%0A" + portal.replace(":", "%3A"), html)
        self.assertNotIn("Ver la oferta original", html)
        closed = offer("9", status="closed", closed_at="2026-01-01")
        self.assertNotIn("Compartir", site.offer_page(closed, self.sources(), NOW.date(), "ahora"))

    def test_ficha_en_otro_idioma_marca_titulo_y_texto_oficial(self):
        idibell = type("S", (), {"name": "IDIBELL", "apply_label": "Ver", "text_lang": "en"})()
        sections = [{"title": "Convocatoria", "level": 2, "html": "<p>About</p>", "lang": "en"},
                    {"title": "Documentos de la convocatoria", "level": 2, "html": "<p>Bases</p>"}]
        record = offer("8", source="idibell", title="Biostatistician", sections=sections)
        sheet = site.offer_page(record, {"idibell": idibell}, NOW.date(), "ahora")
        self.assertIn('<h1 lang="en">Biostatistician</h1>', sheet)
        self.assertIn('<div class="texto-oficial" lang="en"><p>About</p></div>', sheet)
        self.assertIn('<div class="texto-oficial"><p>Bases</p></div>', sheet)
        plain = site.offer_page(offer("9"), self.sources(), NOW.date(), "ahora")
        self.assertNotIn(" lang=", plain.split("<html lang=\"es\">", 1)[1])

    def test_codigo_de_oferta_solo_si_lo_publica_el_portal(self):
        sheet = site.offer_page(offer("5", code=None), self.sources(), NOW.date(), "ahora")
        self.assertNotIn("Código de oferta", sheet)
        self.assertNotIn("Título en la web oficial", sheet)
        record = offer("6", title="Médico de Empresa", code="OE 25/26", source_title="OE 25/26 - Médico de Empresa")
        sheet = site.offer_page(record, self.sources(), NOW.date(), "ahora")
        self.assertIn("<dt>Código de oferta</dt><dd>OE 25/26</dd>", sheet)
        self.assertIn("<dt>Título en la web oficial</dt><dd>OE 25/26 - Médico de Empresa</dd>", sheet)
        self.assertIn("<h1>Médico de Empresa</h1>", sheet)
        self.assertIn("oe 25/26", site.plain_search(record))  # se puede buscar por código

    def test_plazo_que_aun_no_ha_empezado_y_hora_de_cierre(self):
        future = offer("5", opens_on="2026-11-09", deadline="2026-11-13", deadline_time="13:00")
        card = site.offer_card(future, NOW.date())
        self.assertIn("Plazo aún no iniciado", card)
        self.assertIn("Inscripción desde el", card)
        self.assertIn("13 de noviembre de 2026</time>, a las 13:00", card)
        sheet = site.offer_page(future, self.sources(), NOW.date(), "ahora")
        self.assertIn("<dt>Plazo</dt><dd>Del <time", sheet)
        started = offer("6", opens_on="2026-11-01", deadline="2026-11-08", deadline_time="08:00")
        self.assertIn("Finaliza mañana.", site.offer_card(started, NOW.date()))
        self.assertIn("a las 08:00", site.offer_card(started, NOW.date()))
        self.assertNotIn("a las", site.offer_card(offer("7"), NOW.date()))

    def sources(self):
        tragsa = type("S", (), {"name": "Tragsa", "apply_label": "Inscribirse en la web oficial"})()
        return {"tragsa": tragsa}

    def test_empresa_prevista_visible(self):
        self.assertIn("Empresa futura · prevista", self.read("organismos/index.html"))
        self.assertIn("Previstas: Empresa futura.", self.read("acerca/index.html"))


def luminance(color):
    channels = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    r, g, b = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels]
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class Contrast(unittest.TestCase):
    def test_tokens_cumplen_4_5_en_todos_los_temas(self):
        css = (site.ASSETS / "estilos.css").read_text(encoding="utf-8")
        blocks = [b for b in re.findall(r"\{([^{}]*)\}", css) if "--ink:" in b]
        self.assertEqual(len(blocks), 5)  # claro, oscuro del sistema, oscuro, sepia y contraste alto
        for block in blocks:
            tokens = dict(re.findall(r"--([a-z-]+):\s*(#[0-9a-f]{6})", block))
            pairs = [
                ("ink", "bg"), ("ink", "surface"), ("titulos", "bg"), ("titulos", "surface"),
                ("muted", "bg"), ("muted", "surface"), ("accent", "bg"), ("accent", "surface"),
                ("accent-ink", "accent"), ("alert", "bg"), ("alert", "alert-bg"), ("ink", "alert-bg"),
            ]
            for fg, bg in pairs:
                self.assertGreaterEqual(contrast(tokens[fg], tokens[bg]), 4.5, f"{fg} sobre {bg}")


class Where(unittest.TestCase):
    def test_muestra_la_localidad_si_la_ubicacion_solo_dice_la_comunidad(self):
        galicia = {"location": "Comunidad de Galicia", "region": "Galicia", "place": "Santiago de Compostela"}
        self.assertEqual(site.where(galicia), "Santiago de Compostela, Galicia")
        madrid = {"location": "Sede Madrid Tragsa", "region": "Comunidad de Madrid", "place": "Madrid"}
        self.assertEqual(site.where(madrid), "Madrid")
        repetida = {"location": "Comunidad de Asturias", "region": "Asturias", "place": "Sobrescobio, Asturias"}
        self.assertEqual(site.where(repetida), "Sobrescobio, Asturias")

    def test_no_toca_las_ubicaciones_ya_concretas(self):
        self.assertEqual(site.where({"location": "Sevilla", "region": "Andalucía", "place": "Dos Hermanas"}), "Sevilla")
        self.assertEqual(site.where({"location": "Sevilla", "region": "Andalucía"}), "Sevilla")
        self.assertEqual(site.where({"region": "Galicia"}), "Sin ubicación")
