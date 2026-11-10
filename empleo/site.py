"""Genera la web estática: ofertas, fichas, anuncios, histórico y feeds."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from datetime import date, datetime, timedelta, timezone
from html import escape as e
from pathlib import Path
from urllib.parse import quote

from . import areas, feeds, store, teletrabajo
from .model import (ACCESS, GROUPS, KINDS, LIVE_STATES, MADRID, PROCESS_TYPES, STATE_SCOPE, STATES,
                    SYSTEMS, process_type)
from .regions import CCAA, REGIONS, UNKNOWN, codes_of, location_from_title, provinces
from .sources import ACTIVE, PLANNED
from .text import humane_caps

ASSETS = Path(__file__).parent / "assets"
SITE_NAME = "Empleo en Empresas Públicas"
TAGLINE = "Ofertas de empleo de las empresas y entidades del sector público, reunidas en un único portal"
REPO = "https://github.com/alertapublica/empleo-publico-abierto"
# Titular del portal y responsable de los datos del bot (LSSI art. 10, RGPD art. 13).
TITULAR = "Voceiro - JJAA"
CONTACTO = "legal@alertapublica.es"
MAILTO = f'<a href="mailto:{CONTACTO}">{CONTACTO}</a>'
DEFAULT_BASE_URL = "https://alertapublica.es/"
# Usuario del bot de avisos (sin @). Vacío: la web no lo menciona. Se fija en actualizar.yml.
TELEGRAM_BOT = os.environ.get("TELEGRAM_BOT", "").lstrip("@")
# Clave pública del widget de Turnstile del formulario de avisos por correo. Vacía: la web no ofrece
# el correo. Se fija en actualizar.yml.
CORREO_SITEKEY = os.environ.get("CORREO_SITEKEY", "")
AVISOS_URL = "https://avisos.alertapublica.es"  # worker de avisos (avisos/)
TURNSTILE = "https://challenges.cloudflare.com"
CSP = "default-src 'none'; style-src 'self'; script-src 'self'; img-src 'self'; base-uri 'none'; form-action 'self'"
# Solo en «Recibir avisos» con el formulario de correo: el widget de Turnstile y el envío al worker.
CSP_CORREO = (f"default-src 'none'; style-src 'self'; script-src 'self' {TURNSTILE}; frame-src {TURNSTILE}; "
              f"img-src 'self'; base-uri 'none'; form-action 'self' {AVISOS_URL}")
# Va en el pie de todas las páginas. Que prevalece la web oficial se dice en la ficha y en «Acerca de».
DISCLAIMER = "Portal independiente y no oficial, sin vinculación con la Administración ni con los organismos citados."
MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
WEEKDAYS = "lunes martes miércoles jueves viernes sábado domingo".split()
SOON_DAYS = 7
URGENT_DAYS = 3
NEWS_DAYS = 14  # días que guarda api/novedades.json
# Cabecera común de los ficheros de api/. Cambiar o quitar una clave obliga a subir la versión.
API_VERSION = 1
API_HEAD = {
    "version": API_VERSION,
    "licencia": "CC BY 4.0 (https://creativecommons.org/licenses/by/4.0/deed.es). Los textos y enlaces "
                "de cada oferta y comunicado pertenecen a su organismo.",
}
NAV = [
    ("index", "", "Ofertas"),
    ("anuncios", "anuncios/", "Procesos"),
    ("organismos", "organismos/", "Organismos"),
    ("avisos", "avisos/", "Avisos"),
    ("acerca", "acerca/", "Acerca de"),
    ("historico", "historico/", "Histórico"),
]
# En el pie, y enlazada también desde el diálogo de apariencia.
FOOTER_NAV = [
    ("accesibilidad", "accesibilidad/", "Accesibilidad"),
    ("datos", "datos/", "Datos abiertos"),
]


def slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text)
    plain = "".join(c for c in plain if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")


def long_date(value: str | None, weekday: bool = False) -> str:
    if not value:
        return "Sin indicar"
    day = date.fromisoformat(value[:10])
    text = f"{day.day} de {MONTHS[day.month - 1]} de {day.year}"
    return f"{WEEKDAYS[day.weekday()]}, {text}" if weekday else text


def time_tag(value: str | None, weekday: bool = False) -> str:
    if not value:
        return "Sin indicar"
    return f'<time datetime="{e(value[:10])}">{e(long_date(value, weekday))}</time>'


def lang_attr(lang: str | None) -> str:
    """` lang="en"` para el texto de una fuente que no escribe en castellano; nada si lo hace."""
    return f' lang="{e(lang)}"' if lang else ""


def open_count(count: int) -> str:
    return "1 oferta abierta" if count == 1 else f"{count} ofertas abiertas"


def seats(count: int | None) -> str:
    if count is None:
        return "Plazas: no consta"
    return "1 plaza" if count == 1 else f"{count} plazas"


GENERIC_PLACES = ("Comunidad de", "Sede", "Varios", "Nacional")


def where(offer: dict) -> str:
    """Ubicación para mostrar: la localidad cuando la ubicación guardada solo dice la comunidad."""
    location = offer.get("location") or UNKNOWN
    place = offer.get("place")
    if not place or not location.startswith(GENERIC_PLACES):
        return location
    region = offer.get("region") or ""
    plain = lambda text: unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    if plain(place) in plain(region) or plain(region) in plain(place) or region in ("", UNKNOWN):
        return place
    return f"{place}, {region}"


def offer_path(offer: dict) -> str:
    return f"ofertas/{offer['source']}-{slug(offer['ref'])}/"


def saved_id(offer: dict) -> str:
    """Clave de la oferta en «Guardadas» (guardadas.js): no cambia mientras exista su ficha."""
    return f"o:{offer['source']}-{slug(offer['ref'])}"


def saved_filter(kind: str, label: str) -> str:
    """Pastilla «Guardadas»: oculta hasta que guardadas.js sabe que hay alguna en este navegador."""
    return (f'<label class="pastilla" id="pastilla-guardadas" data-tipo="{kind}" hidden>'
            f'<input type="checkbox" name="guardadas" value="1"> {label}<span id="n-guardadas"></span></label>\n')


def radios(name: str, options: list[tuple[str, str]]) -> str:
    return "".join(
        f'<div class="opcion"><input type="radio" id="{name}-{value}" name="{name}" value="{value}">'
        f'<label for="{name}-{value}">{label}</label></div>'
        for value, label in options
    )


def color_row(key: str, label: str, contrast: bool = True) -> str:
    check = f'<output id="contraste-{key}" for="color-{key}"></output>' if contrast else ""
    return (f'<div class="color-fila"><input type="color" id="color-{key}" value="#000000">'
            f'<label for="color-{key}">{label}</label>{check}</div>')


def settings_dialog(root: str) -> str:
    return f"""<dialog id="ajustes" class="ajustes" aria-labelledby="ajustes-titulo">
<div class="aj-cab"><h2 id="ajustes-titulo">Apariencia</h2>
<button type="button" id="ajustes-cerrar">Cerrar</button></div>
<div class="aj-cuerpo">
<fieldset><legend>Tema</legend>
<div class="opciones">{radios("tema", [("auto", "Automático"), ("light", "Claro"), ("sepia", "Sepia"),
                                       ("dark", "Oscuro"), ("contrast", "Contraste alto"), ("custom", "Personalizado")])}</div>
<p class="aj-nota">La opción Automático aplica el tema configurado en su dispositivo.</p>
<div class="colores" id="colores" hidden>
{color_row("fondo", "Fondo", False)}{color_row("texto", "Texto")}{color_row("enlaces", "Enlaces")}{color_row("titulos", "Títulos")}
<p class="aj-nota">Seleccione cuatro colores; el resto se calcula de forma automática. Se indica si alguno no alcanza un contraste de 4,5:1 con el fondo.</p>
</div></fieldset>
<fieldset><legend>Letra</legend>
<div class="opciones">{radios("fuente", [("sans", "Sans"), ("serif", "Serif"), ("dyslexic", "Dislexia")])}</div>
</fieldset>
<fieldset><legend>Tamaño de letra</legend>
<div class="paso"><button type="button" id="fs-menos" aria-label="A menos: reducir el tamaño de letra">A−</button>
<output id="fs-val" for="fs-menos fs-mas"></output>
<button type="button" id="fs-mas" aria-label="A más: aumentar el tamaño de letra">A+</button></div>
<p class="aj-nota">Porcentaje sobre el tamaño de letra configurado en su navegador.</p>
</fieldset>
<fieldset><legend>Ancho del contenido</legend>
<div class="paso"><button type="button" id="ancho-menos" aria-label="Reducir el ancho del contenido">−</button>
<output id="ancho-val" for="ancho-menos ancho-mas"></output>
<button type="button" id="ancho-mas" aria-label="Aumentar el ancho del contenido">+</button></div>
</fieldset>
<fieldset><legend>Ayudas de lectura</legend>
<label class="casilla-ajuste"><input type="checkbox" name="extra" value="just"><span>Justificar el texto</span></label>
<label class="casilla-ajuste"><input type="checkbox" name="extra" value="bionic"><span>Negrita en el inicio de cada palabra<span>Algunos lectores de pantalla pueden leer peor el texto con esta opción.</span></span></label>
<label class="casilla-ajuste"><input type="checkbox" name="extra" value="focus"><span>Foco: atenuar las ofertas que no se están leyendo<span>Las ofertas atenuadas tienen menos contraste de forma intencionada.</span></span></label>
</fieldset>
<p class="aj-nota">Sus ajustes se guardan únicamente en este navegador y no se envían a ningún servidor.</p>
<p class="aj-nota"><a href="{root}accesibilidad/">Accesibilidad del portal</a></p>
</div>
<div class="aj-pie"><button type="button" id="ajustes-reset">Restablecer apariencia</button></div>
</dialog>"""


# Abre el diálogo de apariencia. Sin JavaScript no hace nada, así que nace oculto y lo muestra ajustes.js.
SETTINGS_BUTTON = ('<button type="button" id="btn-aa" class="btn-cab" aria-haspopup="dialog" hidden>'
                   '<span class="aa" aria-hidden="true">Aa</span> <span class="aa-texto">Apariencia</span></button>')


def page(title: str, body: str, root: str, current: str = "", description: str = TAGLINE, checked: str = "",
         csp: str = CSP) -> str:
    links = "".join(
        f'<li><a href="{root}{href}"{" aria-current=\"page\"" if key == current else ""}>{label}</a></li>'
        for key, href, label in NAV
    )
    footer_links = "".join(
        f'<a href="{root}{href}"{" aria-current=\"page\"" if key == current else ""}>{label}</a> · '
        for key, href, label in FOOTER_NAV
    )
    full_title = title if title == SITE_NAME else f"{title} · {SITE_NAME}"
    stamp = f"<p>Última consulta a las webs oficiales: {e(checked)}.</p>" if checked else ""
    return f"""<!doctype html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="Content-Security-Policy" content="{csp}">
<title>{e(full_title)}</title>
<meta name="description" content="{e(description)}">
<link rel="stylesheet" href="{root}assets/estilos.css">
<script src="{root}assets/tema.js"></script>
<link rel="icon" href="{root}assets/icono.svg" type="image/svg+xml">
<link rel="alternate" type="application/rss+xml" title="Todas las novedades" href="{root}feed.xml">
</head>
<body id="arriba">
<a class="salto" href="#contenido">Saltar al contenido</a>
<header class="sitio">
<div class="ancho cab">
<a class="marca" href="{root}">{SITE_NAME}</a>
<div class="cab-acciones">
{SETTINGS_BUTTON}
<button type="button" id="btn-menu" class="btn-cab" hidden aria-expanded="false" aria-controls="nav-principal">Menú</button>
</div>
<nav id="nav-principal" class="principal" aria-label="Principal"><ul>{links}</ul></nav>
</div></header>
<main id="contenido" class="ancho" tabindex="-1">
{body}
</main>
<footer class="sitio"><div class="ancho">
<p class="subir"><a href="#arriba">Volver arriba</a></p>
<p>{TAGLINE}. {DISCLAIMER}</p>
{stamp}
<p>{footer_links}<a href="{root}acerca/#quien">Aviso legal y privacidad</a> · <a href="{REPO}">Código fuente en GitHub</a></p>
</div></footer>
<a class="subir-flotante" id="subir-flotante" href="#arriba" hidden><span aria-hidden="true">↑</span> Arriba</a>
{settings_dialog(root)}
<script src="{root}assets/guardadas.js" defer></script>
<script src="{root}assets/filtros.js" defer></script>
<script src="{root}assets/subir.js" defer></script>
<script src="{root}assets/ajustes.js" defer></script>
<script src="{root}assets/compartir.js" defer></script>
</body>
</html>
"""


def plain_search(offer: dict) -> str:
    text = " ".join(
        str(offer.get(key) or "")
        for key in ("title", "source_title", "code", "company", "location", "place", "region", "department",
                    "family", "category", "contract")
    ) + " " + KINDS.get(offer.get("kind"), "")
    plain = unicodedata.normalize("NFD", text)
    return "".join(c for c in plain if not unicodedata.combining(c)).lower()


def until(offer: dict) -> str:
    """«el lunes, 10 de noviembre de 2026», con la hora si la fuente la da."""
    hour = f", a las {e(offer['deadline_time'])}" if offer.get("deadline_time") else ""
    return f"{time_tag(offer['deadline'], weekday=True)}{hour}"


def deadline_text(offer: dict, today: date) -> str:
    opens = offer.get("opens_on")
    if opens and date.fromisoformat(opens) > today:
        end = f" hasta el {until(offer)}" if offer.get("deadline") else ""
        return f"<strong>Plazo aún no iniciado.</strong> Inscripción desde el {time_tag(opens, weekday=True)}{end}"
    if not offer.get("deadline"):
        return "Plazo: no consta"
    days = (date.fromisoformat(offer["deadline"]) - today).days
    label = f"Plazo: hasta el {until(offer)}"
    if days == 0:
        return f'<span class="urgente">Finaliza hoy.</span> {label}'
    if days == 1:
        return f'<span class="urgente">Finaliza mañana.</span> {label}'
    if days <= URGENT_DAYS:
        return f'<span class="urgente">Quedan {days} días.</span> {label}'
    return label


def contract_label(offer: dict) -> str:
    """Contrato en pocas palabras: el tipo si la fuente lo dice claro; si no, su texto literal."""
    return KINDS.get(offer.get("kind")) or offer.get("contract") or ""


def original_link(offer: dict) -> str:
    """«Abrir original» abre el portal de la empresa en una pestaña nueva, y lo dice al lector de pantalla."""
    return (f'<a class="original" href="{e(offer["url"])}" target="_blank" rel="noopener">Abrir original'
            f'<span class="sr-only">: {e(offer["title"])} (se abre en una pestaña nueva)</span></a>')


def share_link(offer: dict, base_url: str) -> str:
    """«Compartir» la ficha del portal. Sin JavaScript, o donde no hay menú nativo, abre el correo
    (mailto:); con él, compartir.js abre el menú de compartir del sistema."""
    url = base_url + offer_path(offer)
    mailto = f"mailto:?subject={quote(offer['title'])}&body={quote(offer['title'] + chr(10) + url)}"
    return (f'<a class="compartir" href="{e(mailto)}" data-url="{e(url)}" data-titulo="{e(offer["title"])}">'
            f'Compartir<span class="sr-only">: {e(offer["title"])}</span></a>')


def offer_card(offer: dict, today: date, root: str = "", group: str = "") -> str:
    days = (date.fromisoformat(offer["deadline"]) - today).days if offer.get("deadline") else 9999
    facts = [offer.get("company"), where(offer), seats(offer.get("positions"))]
    remote = teletrabajo.mention(offer)
    extra = [offer.get("family"), offer.get("category"), contract_label(offer),
             "Menciona teletrabajo" if isinstance(remote, str) else None]
    extra = " · ".join(f for f in extra if f)
    extra = f' <span class="dato">· {e(extra)}</span>' if extra else ""
    published = (
        f" <span class=\"dato\">· Publicada el {time_tag(offer['published_on'])}</span>"
        if offer.get("published_on") else ""
    )
    area = " ".join(areas.offer_areas(offer, group)[0]) or areas.NONE
    return f"""<li data-texto="{e(plain_search(offer))}" data-comunidad="{e(offer.get('region') or UNKNOWN)}" data-organismo="{e(offer['source'])}" data-grupo="{e(group)}" data-empresa="{e(offer.get('company') or '')}" data-area="{e(area)}" data-tipo="{e(offer.get('kind') or '')}" data-teletrabajo="{1 if isinstance(remote, str) else 0}" data-plazas="{offer.get('positions') or 0}" data-plazo="{e(offer.get('deadline') or '9999')}" data-publicada="{e(offer.get('published_on') or offer['first_seen'][:10])}" data-pronto="{1 if days <= SOON_DAYS else 0}" data-guardar="{e(saved_id(offer))}">
<h2><a href="{root}{offer_path(offer)}">{e(offer['title'])}</a></h2>
<p>{e(' · '.join(str(f) for f in facts if f))}{extra}</p>
<p class="plazo">{deadline_text(offer, today)}{published}</p>
<div class="tarjeta-acciones"></div>
</li>"""


def options(values, labels: dict | None = None) -> str:
    labels = labels or {}
    return "".join(
        f'<option value="{e(value)}">{e(labels.get(value, value))}</option>'
        for value in sorted(v for v in set(values) if v)
    )


def area_options(open_offers: list[dict], group_of: dict) -> str:
    """Áreas con alguna oferta abierta, por nombre; «Sin área» al final."""
    present = set()
    for offer in open_offers:
        present.update(areas.offer_areas(offer, group_of.get(offer["source"], ""))[0] or [areas.NONE])
    choices = [(key, label) for key, label in areas.BY_NAME if key in present]
    if areas.NONE in present:
        choices.append((areas.NONE, "Sin área"))
    return "".join(f'<option value="{key}">{e(label)}</option>' for key, label in choices)


def index_page(open_offers: list[dict], today: date, checked: str, sources: dict) -> str:
    ordered = sorted(
        open_offers,
        key=lambda o: (o.get("published_on") or o["first_seen"][:10]),
        reverse=True,
    )
    total_seats = sum(o.get("positions") or 0 for o in open_offers)
    group_of = {s.id: s.group for s in sources.values()}
    cards = "\n".join(offer_card(o, today, group=group_of.get(o["source"], "")) for o in ordered)
    empty = "" if open_offers else '<p class="nota">En este momento no hay ofertas abiertas.</p>'
    remote = [teletrabajo.mention(o) for o in open_offers]
    remote_filter = remote_hint = ""
    if any(isinstance(r, str) for r in remote):
        unknown = sum(r is None for r in remote)
        hint = (f" En {'1 oferta' if unknown == 1 else f'{unknown} ofertas'} no es posible comprobarlo, porque la"
                " ficha no recoge las condiciones y remite a las bases." if unknown else "")
        remote_filter = (
            '<label class="pastilla"><input type="checkbox" name="teletrabajo" value="1" aria-describedby="ayuda-teletrabajo">'
            ' Menciona teletrabajo</label>\n'
        )
        # Solo se ve con la casilla marcada (estilos.css); el lector de pantalla la lee siempre.
        remote_hint = f'<p class="ayuda" id="ayuda-teletrabajo">Teletrabajo: se busca la mención en el texto de la ficha.{hint}</p>\n'
    organism_filter = ""
    if len(sources) > 1:
        present = {o["source"] for o in open_offers}
        organism_filter = (
            '<div class="campo"><label for="organismo">Organismo</label>\n'
            '<select id="organismo" name="organismo"><option value="">Todos</option>'
            f"{organism_options(sources, present)}</select></div>\n"
        )
    groups = {sources[o["source"]].group for o in open_offers if o["source"] in sources}
    if len(groups) > 1:
        choices = "".join(f'<option value="{key}">{e(label)}</option>' for key, label in GROUPS.items() if key in groups)
        organism_filter = (
            '<div class="campo"><label for="grupo">Grupo de organismos</label>\n'
            f'<select id="grupo" name="grupo"><option value="">Todos</option>{choices}</select></div>\n'
        ) + organism_filter
    body = f"""<h1 class="sr-only">Ofertas de empleo abiertas</h1>
{empty}
<noscript><p class="nota">Los filtros requieren JavaScript. Sin él, puede consultar la lista completa o suscribirse a los <a href="avisos/">avisos por comunidad autónoma</a>.</p></noscript>
<form id="filtros" class="filtros" role="search" aria-label="Buscar ofertas" data-procesos="anuncios/" hidden>
{search_bar("Buscar ofertas por palabra", "Puesto, empresa o localidad")}
<div class="pastillas">
{FILTERS_BUTTON}
<label class="pastilla"><input type="checkbox" name="pronto" value="1"> Cierran en {SOON_DAYS} días</label>
{remote_filter}{saved_filter("o", "Guardadas")}<a class="como-buscar" href="acerca/#como-buscar">Cómo buscar</a>
{order_field(ORDER_OPTIONS)}</div>
<div class="panel rejilla" id="mas-filtros" hidden>
<div class="campo"><label for="comunidad">Comunidad autónoma</label>
<select id="comunidad" name="comunidad"><option value="">Todas</option>{options(o.get('region') for o in open_offers)}</select></div>
<div class="campo"><label for="area">Área (orientativa)</label>
<select id="area" name="area"><option value="">Todas</option>{area_options(open_offers, group_of)}</select></div>
<div class="campo"><label for="tipo">Tipo de contrato</label>
<select id="tipo" name="tipo"><option value="">Todos</option>{options((o.get('kind') for o in open_offers), KINDS)}</select></div>
<div class="campo"><label for="empresa">Empresa</label>
<select id="empresa" name="empresa"><option value="">Todas</option>{options(o.get('company') for o in open_offers)}</select></div>
{organism_filter}</div>
{remote_hint}</form>
{results_bar(f"{open_count(len(open_offers))}, con {seats(total_seats)}.", reset=True)}
<ol class="ofertas" id="lista-ofertas">
{cards}
</ol>"""
    return page(SITE_NAME, body, "", "index", checked=checked)


ORDER_OPTIONS = (
    '<option value="reciente">Más recientes</option><option value="plazo">Plazo más próximo</option>'
    '<option value="empresa">Empresa (A-Z)</option>'
)
# Abre y cierra el panel de filtros (filtros.js); el número de filtros activos va en n-filtros.
FILTERS_BUTTON = ('<button type="button" class="pastilla" id="btn-filtros" aria-expanded="false" '
                  'aria-controls="mas-filtros">Filtros<span id="n-filtros"></span></button>')


def search_bar(label: str, placeholder: str) -> str:
    return (f'<div class="buscador"><label for="q" class="sr-only">{label}</label>\n'
            f'<input id="q" name="q" type="search" autocomplete="off" placeholder="{placeholder}">\n'
            '<button type="submit">Buscar</button></div>')


def order_field(order: str) -> str:
    """«Ordenar», al final de la fila de pastillas. Oculto hasta que filtros.js puede ordenar."""
    return ('<div class="orden" id="orden-campo" hidden><label for="orden">Ordenar por</label>\n'
            f'<select id="orden" name="orden">{order}</select></div>')


def results_bar(status: str, reset: bool = False) -> str:
    """Recuento de resultados y, si hay, «Quitar filtros» (del formulario por su atributo form).

    En la portada «Quitar filtros» va aquí y no junto a las pastillas: al aparecer no mueve la fila de pastillas."""
    reset_html = ('<button type="reset" form="filtros" class="quitar" hidden>Quitar filtros</button>'
                  if reset else "")
    return (f'<div class="resultados"><p id="estado-filtros" role="status">{status}</p>{reset_html}</div>\n'
            '<p class="nota" id="sin-resultados" hidden></p>')


def plazo(offer: dict) -> str:
    if not offer.get("deadline"):
        return "No consta"
    if offer.get("opens_on"):
        return f"Del {time_tag(offer['opens_on'], weekday=True)} al {until(offer)}"
    return until(offer)


def remote_text(remote: str | bool | None) -> str:
    if isinstance(remote, str):
        return f"Según la ficha: «{e(remote)}»"
    if remote is False:
        return "La ficha no lo menciona"
    return "No consta: consulte las bases"


def offer_page(offer: dict, sources: dict, today: date, checked: str,
               base_url: str = DEFAULT_BASE_URL) -> str:
    root = "../../"
    closed = offer["status"] == "closed"
    rows = [
        ("Empresa", e(offer.get("company") or "No consta")),
        ("Plazas", e(str(offer.get("positions") or "No consta"))),
        ("Ubicación", e(where(offer))),
        ("Comunidad autónoma", e(offer.get("region") or UNKNOWN)),
        ("Contrato", e(offer.get("contract") or KINDS.get(offer.get("kind"), "No consta"))),
        ("Convocatoria", e(offer.get("category") or "No consta")),
        ("Tipo de puesto", e(offer.get("family") or "No consta")),
        ("Departamento", e(offer.get("department") or "No consta")),
        ("Plazo", plazo(offer)),
        ("Teletrabajo", remote_text(teletrabajo.mention(offer))),
        ("Fecha de publicación", time_tag(offer.get("published_on") or offer["first_seen"])),
    ]
    if offer.get("code"):
        rows.append(("Código de oferta", e(offer["code"])))
    if offer.get("source_title"):
        rows.append(("Título en la web oficial", e(offer["source_title"])))
    facts = "".join(f"<dt>{label}</dt><dd>{value}</dd>" for label, value in rows)
    sections = "".join(
        f"<h{s['level']}>{e(s['title'])}</h{s['level']}>"
        f"<div class=\"texto-oficial\"{lang_attr(s.get('lang'))}>{s['html']}</div>"
        for s in offer.get("sections", [])
    )
    if not sections:
        sections = '<p class="nota">El texto de esta oferta no está disponible en este portal. Puede consultarlo en la web oficial.</p>'
    if closed:
        status = (
            f'<p class="nota alerta">Esta oferta está cerrada desde el {e(long_date(offer["closed_at"]))}. '
            "Se conserva como registro histórico y ya no admite inscripciones.</p>"
        )
        action = ""
    else:
        status = ""
        action = (
            f'<div class="acciones"><a class="boton" href="{e(offer["apply_url"])}">{e(sources[offer["source"]].apply_label)}</a>'
            f'{original_link(offer)}{share_link(offer, base_url)}</div>'
        )
    parent = ""
    if offer.get("parent_ref"):
        parent = (
            f'<p class="nota">Esta oferta es una nueva publicación de la oferta {e(offer["parent_ref"])}.</p>'
        )
    body = f"""<p><a href="{root}">Volver al listado de ofertas</a></p>
<h1{lang_attr(getattr(sources[offer['source']], 'text_lang', None))}>{e(offer['title'])}</h1>
<p class="guardar-ficha" data-guardar="{e(saved_id(offer))}" hidden></p>
{status}{parent}
<dl class="ficha">{facts}</dl>
{action}
{sections}
<p class="nota">Texto reproducido de la web oficial de {e(sources[offer['source']].name)}. En caso de discrepancia, prevalece la información publicada por el organismo.</p>"""
    description = f"{offer.get('company')}, {where(offer)}. {seats(offer.get('positions'))}."
    return page(offer["title"], body, root, description=description, checked=checked)


def by_group(sources: dict) -> list[tuple[str, str, list]]:
    """Organismos por grupo, en el orden del catálogo. Los grupos vacíos no aparecen."""
    return [
        (key, label, [s for s in sources.values() if s.group == key])
        for key, label in GROUPS.items()
        if any(s.group == key for s in sources.values())
    ]


def is_holding(source) -> bool:
    """La sociedad matriz de un grupo (SEPI en el Grupo SEPI) comparte clave con él: va la primera."""
    return source.id == source.group


def member_name(source) -> str:
    """Nombre en las listas por grupo, donde la matriz se distingue del grupo que encabeza."""
    return f"{source.name} (matriz)" if is_holding(source) else source.name


def organism_options(sources: dict, present: set) -> str:
    """Opciones del filtro de organismo, agrupadas como en el catálogo."""
    html = ""
    for _, label, members in by_group(sources):
        choices = "".join(
            f'<option value="{e(s.id)}">{e(s.name)}</option>'
            for s in sorted(members, key=lambda s: s.name) if s.id in present
        )
        if choices:
            html += f'<optgroup label="{e(label)}">{choices}</optgroup>'
    return html


def scope_note(source) -> str:
    return "" if source.scope == STATE_SCOPE else f"{e(source.scope)} · "


def running_count(count: int) -> str:
    return "1 proceso en marcha" if count == 1 else f"{count} procesos en marcha"


def organisms_page(sources: dict, open_offers: list[dict], checked: str, processes: dict | None = None,
                   bot: str = "") -> str:
    """Organismos por grupo, primero los que más ofertas tienen. Los que tienen ofertas o procesos en
    marcha llevan a su página; los procesos se muestran como dato secundario. Un buscador (con JS)
    filtra por nombre o comunidad."""
    processes = processes or {}

    def count(source_id: str) -> int:
        return sum(o["source"] == source_id for o in open_offers)

    def summary(source) -> str:
        offers, running = count(source.id), processes.get(source.id, 0)
        html = f"<p>{open_count(offers)}</p>" if offers else ""
        return html + (f'<p class="dato">{running_count(running)}</p>' if running else "")

    def searchable(source) -> str:
        return e(f"{source.name} {source.scope}")

    blocks, index = [], []
    for key, label, members in by_group(sources):
        con = sorted((s for s in members if count(s.id) or processes.get(s.id)),
                     key=lambda s: (not is_holding(s), -count(s.id), -processes.get(s.id, 0), s.name.lower()))
        sin = sorted((s for s in members if s not in con), key=lambda s: (not is_holding(s), s.name.lower()))
        active = "".join(
            f'<li data-texto="{searchable(s)}"><h3><a href="{e(s.id)}/">{e(member_name(s))}</a></h3>'
            f'{summary(s)}'
            f'<p class="dato">{scope_note(s)}<a href="{e(s.homepage)}">Web oficial</a></p></li>'
            for s in con
        )
        # Sin ofertas no hay nada que abrir aquí: solo se informa, con enlace a su web oficial, y plegado.
        ninguna = "".join(
            f'<li data-texto="{searchable(s)}">{e(member_name(s))} · {scope_note(s)}<a href="{e(s.homepage)}">Web oficial</a></li>'
            for s in sin
        )
        total = sum(count(s.id) for s in members)
        word = "1 organismo" if len(members) == 1 else f"{len(members)} organismos"
        running = sum(processes.get(s.id, 0) for s in members)
        running = f" · {running_count(running)}" if running else ""
        index.append(f'<li><a href="#grupo-{key}">{e(label)}</a> <span class="dato">({len(members)})</span></li>')
        blocks.append(
            f'<section class="grupo-organismos" aria-labelledby="grupo-{key}"><h2 id="grupo-{key}">{e(label)}</h2>\n'
            f'<p class="dato">{word} · {open_count(total)}{running}</p>\n'
            + (f'<ol class="ofertas organismos">\n{active}\n</ol>\n' if con else "")
            + (f'<details class="sin-ofertas-grupo"><summary>Sin ofertas abiertas en este momento <span class="dato">({len(sin)})</span></summary>\n'
               f'<ul class="sin-ofertas">{ninguna}</ul></details>\n' if sin else "")
            + "</section>"
        )
    planned = "".join(f'<li>{e(p["name"])} · prevista; sus ofertas aún no se incorporan</li>' for p in PLANNED)
    planned_html = f'<h2>Incorporaciones previstas</h2>\n<ul class="sin-ofertas">{planned}</ul>\n' if planned else ""
    via = "Telegram o RSS" if bot else "RSS"
    body = f"""<h1>Organismos</h1>
<p class="resumen">Cada organismo publica sus ofertas de empleo en su propia web. Los organismos se agrupan por tipo de entidad y, dentro de cada grupo, se ordenan por número de ofertas abiertas. La página de cada organismo muestra sus ofertas y sus procesos selectivos en marcha.</p>
<p>Para recibir las novedades de un organismo, puede suscribirse a los <a href="../avisos/">avisos por {via}</a>.</p>
<nav aria-label="Grupos de organismos"><ul class="indice-grupos">{"".join(index)}</ul></nav>
<form id="buscar-organismos" class="buscador" role="search" aria-label="Buscar organismos" hidden>
<label for="q-organismos" class="sr-only">Buscar un organismo por nombre o comunidad autónoma</label>
<input id="q-organismos" type="search" autocomplete="off" placeholder="Nombre o comunidad autónoma">
</form>
<p id="estado-organismos" role="status"></p>
{"".join(blocks)}
{planned_html}<script src="../assets/organismos.js" defer></script>"""
    return page("Organismos", body, "../", "organismos", checked=checked)


def organism_page(source, open_offers: list[dict], today: date, checked: str,
                  processes: list[list[dict]] | None = None, bot: str = "") -> str:
    """Ofertas del organismo y, debajo y con menos peso, sus procesos selectivos en marcha."""
    root = "../../"
    processes = processes or []
    ordered = sorted(
        (o for o in open_offers if o["source"] == source.id),
        key=lambda o: (o.get("published_on") or o["first_seen"][:10]),
        reverse=True,
    )
    cards = "\n".join(offer_card(o, today, root) for o in ordered)
    offers = open_count(len(ordered)) if ordered else "No tiene ofertas abiertas en este momento"
    # Se busca en la portada, ya filtrada por el organismo, con el resto de filtros a mano.
    search = (f"""<form class="buscador" role="search" aria-label="Buscar en sus ofertas" action="{root}" method="get">
<input type="hidden" name="organismo" value="{e(source.id)}">
<label class="sr-only" for="q-organismo">Buscar en las {len(ordered)} ofertas de {e(source.name)}</label>
<input type="search" id="q-organismo" name="q" placeholder="Buscar en sus {len(ordered)} ofertas">
<button type="submit">Buscar</button>
</form>
""" if len(ordered) > 1 else "")
    offer_list = f'<ol class="ofertas">\n{cards}\n</ol>' if ordered else ""
    telegram = f' · <a href="{root}avisos/#telegram">por Telegram</a>' if bot else ""
    running = ""
    if processes:
        names = {source.id: source.name}
        process_cards = "\n".join(process_card(g, names, today, root, level=3) for g in processes)
        running = f"""<section class="procesos" aria-labelledby="procesos-titulo">
<h2 id="procesos-titulo">{running_count(len(processes)).capitalize()}</h2>
<p class="dato">Procesos selectivos convocados y sus comunicados. <a href="{root}anuncios/?organismo={e(source.id)}">Ver en la sección Procesos</a>.</p>
<ol class="ofertas">
{process_cards}
</ol>
</section>"""
    body = f"""<p><a href="../">Volver al listado de organismos</a></p>
<h1>{e(source.name)}</h1>
{search}<p class="resumen">{offers}. <a href="{e(source.homepage)}">Web oficial</a> · <a href="{root}feeds/organismo-{e(source.id)}.xml">Avisos por RSS</a>{telegram}.</p>
{offer_list}
{running}"""
    return page(source.name, body, root, "organismos", checked=checked)


def process_groups(items: list[dict]) -> list[list[dict]]:
    """Comunicados agrupados por proceso, cada grupo del más reciente al más antiguo."""
    groups: dict[tuple[str, str], list[dict]] = {}
    for item in items:
        groups.setdefault((item["source"], item["process"]), []).append(item)
    for notices in groups.values():
        notices.sort(key=lambda a: a["date"], reverse=True)
    return sorted(
        groups.values(),
        key=lambda notices: (notices[0].get("state") == "abierto", notices[0]["date"]),
        reverse=True,
    )


def process_id(notices: list[dict]) -> str:
    return hashlib.sha1(f"{notices[0]['source']}|{notices[0]['process']}".encode()).hexdigest()[:10]


def is_pdf(url: str) -> bool:
    return url.lower().split("?")[0].endswith(".pdf")


def notice_link(notice: dict) -> str:
    when = f"{time_tag(notice['date'])}: " if notice["date"] else ""
    pdf = " (PDF)" if is_pdf(notice["url"]) else ""
    return f'{when}<a href="{e(notice["url"])}">{e(humane_caps(notice["title"]))}{pdf}</a>'


def via_of(notice: dict) -> str:
    return notice.get("via") or process_type(notice["process"])


def process_card(notices: list[dict], names: dict, today: date, root: str, feed: bool = True, level: int = 2) -> str:
    latest = notices[0]
    name = humane_caps(latest["process"])
    state = latest.get("state", "curso")
    url = latest.get("process_url") or latest["url"]
    heading = f'<a href="{e(url)}">{e(name)}{" (PDF)" if is_pdf(url) else ""}</a>'
    facts = [
        names.get(latest["source"], ""), PROCESS_TYPES[via_of(latest)],
        ACCESS.get(latest.get("access"), ""), KINDS.get(latest.get("contract"), ""),
        SYSTEMS.get(latest.get("system"), ""),
    ]
    if state == "abierto":
        status = (f'<p class="plazo"><strong>Inscripción abierta.</strong> {deadline_text(latest, today)} · '
                  f'<a href="{e(latest["apply_url"])}">Inscribirse en la plataforma oficial</a></p>')
    else:
        status = f'<p class="dato">Situación: {e(STATES[state])}</p>'
    older = ""
    if len(notices) > 1:
        rows = "".join(f"<li>{notice_link(n)}</li>" for n in notices[1:])
        count = "1 comunicado anterior" if len(notices) == 2 else f"{len(notices) - 1} comunicados anteriores"
        older = f'<details class="comunicados"><summary>Ver {count}</summary><ol>{rows}</ol></details>'
    rss = (f'<p class="dato proceso-acciones"><a href="{root}feeds/proceso-{process_id(notices)}.xml">'
           f'Avisos de este proceso por RSS</a></p>') if feed else ""
    search = plain_search({
        "title": " ".join(n["title"] for n in notices),
        "company": names.get(latest["source"], ""), "family": latest["process"],
    })
    return f"""<li data-texto="{e(search)}" data-organismo="{e(latest['source'])}" data-tipo="{e(via_of(latest))}" data-acceso="{e(latest.get('access') or '')}" data-contrato="{e(latest.get('contract') or '')}" data-sistema="{e(latest.get('system') or '')}" data-guardar="p:{process_id(notices)}">
<h{level}>{heading}</h{level}>
<p class="dato">{e(' · '.join(f for f in facts if f))}</p>
{status}
<p>Último comunicado. {notice_link(latest)}</p>
{older}{rss}
</li>"""


def select_field(name: str, label: str, values: list, labels: dict) -> str:
    """Desplegable con los valores que existen de verdad; sin valores, no se ofrece."""
    choices = options(values, labels)
    if not choices:
        return ""
    return (f'<div class="campo"><label for="{name}">{label}</label>\n'
            f'<select id="{name}" name="{name}"><option value="">Todos</option>{choices}</select></div>\n')


def is_live(notices: list[dict]) -> bool:
    return notices[0].get("state", "curso") in LIVE_STATES


def announcements_page(items: list[dict], checked: str, sources: dict, today: date) -> str:
    names = {s.id: s.name for s in sources.values()}
    groups = process_groups(items)
    live = [g for g in groups if is_live(g)]
    finished = len(groups) - len(live)
    cards = "\n".join(process_card(g, names, today, "../") for g in live)
    latest = [g[0] for g in live]
    more = "".join([
        select_field("acceso", "Tipo de acceso", [n.get("access") for n in latest], ACCESS),
        select_field("sistema", "Sistema de selección", [n.get("system") for n in latest], SYSTEMS),
        select_field("contrato", "Tipo de contrato", [n.get("contract") for n in latest], KINDS),
    ])
    more_button = FILTERS_BUTTON if more else ""
    more_filters = f'<div class="panel rejilla" id="mas-filtros" hidden>{more}</div>' if more else ""
    notices = sum(len(g) for g in live)
    process_word = "1 proceso en marcha" if len(live) == 1 else f"{len(live)} procesos en marcha"
    notice_word = "1 comunicado" if notices == 1 else f"{notices} comunicados"
    closed_link = (f'<p><a href="../historico/procesos/">Ver {finished} procesos finalizados o sin novedades</a>.</p>'
                   if finished else "")
    empty = "" if live else '<p class="nota">En este momento no hay procesos en marcha.</p>'
    body = f"""<h1>Anuncios de procesos selectivos</h1>
<p class="nota">Cada proceso agrupa sus comunicados y enlaza a la página o al documento oficial correspondiente. Este portal muestra solo los títulos: las relaciones de personas candidatas deben consultarse en la web oficial del organismo.</p>
{empty}
<noscript><p class="nota">Los filtros requieren JavaScript. Sin él, puede consultar la lista completa.</p></noscript>
<form id="filtros" class="filtros" role="search" aria-label="Buscar procesos" data-uno="proceso encontrado" data-varios="procesos encontrados" hidden>
{search_bar("Buscar procesos por palabra", "Puesto u organismo")}
<div class="pastillas">
<div class="campo en-linea"><label for="organismo">Organismo</label>
<select id="organismo" name="organismo"><option value="">Todos</option>{options((n['source'] for n in latest), names)}</select></div>
<div class="campo en-linea"><label for="tipo">Tipo de proceso</label>
<select id="tipo" name="tipo"><option value="">Todos</option>{options((via_of(n) for n in latest), PROCESS_TYPES)}</select></div>
{saved_filter("p", "Guardados")}{more_button}<button type="reset" class="quitar">Quitar filtros</button></div>
{more_filters}
</form>
{results_bar(f"{process_word}, con {notice_word}.")}
<ol class="ofertas" id="lista-ofertas">
{cards}
</ol>
{closed_link}"""
    return page("Anuncios de procesos", body, "../", "anuncios", checked=checked)


def closed_processes_page(items: list[dict], checked: str, sources: dict, today: date) -> str:
    names = {s.id: s.name for s in sources.values()}
    groups = [g for g in process_groups(items) if not is_live(g)]
    groups.sort(key=lambda notices: notices[0]["date"], reverse=True)
    cards = "\n".join(process_card(g, names, today, "../../", feed=False) for g in groups)
    empty = "" if groups else '<p class="nota">Aún no hay procesos finalizados.</p>'
    body = f"""<p><a href="../">Volver al histórico de ofertas</a> · <a href="../../anuncios/">Ver los procesos en marcha</a></p>
<h1>Procesos finalizados o sin novedades</h1>
<p class="resumen">«Finalizado» indica que el organismo ha dado el proceso por concluido. «Sin novedades» indica que el proceso ya no figura entre los activos de la web oficial, sin que conste cómo concluyó.</p>
{empty}
<ol class="ofertas">
{cards}
</ol>"""
    return page("Procesos finalizados", body, "../../", "historico", checked=checked)


def history_page(closed: list[dict], checked: str, closed_processes: int = 0) -> str:
    ordered = sorted(closed, key=lambda o: o["closed_at"] or "", reverse=True)
    rows = "\n".join(
        f"""<li data-texto="{e(plain_search(o))}" data-empresa="{e(o.get('company') or '')}">
<h2><a href="../{offer_path(o)}">{e(o['title'])}</a></h2>
<p>{e(o.get('company') or '')} · {e(where(o))} · {e(seats(o.get('positions')))}</p>
<p class="dato">Cerrada el {time_tag(o['closed_at'])}</p></li>"""
        for o in ordered
    )
    empty = "" if closed else '<p class="nota">Aún no hay ofertas cerradas. Se recogen desde el 7 de noviembre de 2026.</p>'
    search = f"""<noscript><p class="nota">El buscador requiere JavaScript. Sin él, puede consultar la lista completa.</p></noscript>
<form id="filtros" class="filtros" role="search" aria-label="Buscar en el histórico" hidden>
{search_bar("Buscar ofertas cerradas por palabra", "Puesto, empresa o localidad")}
<div class="pastillas">
<div class="campo en-linea"><label for="empresa">Empresa</label>
<select id="empresa" name="empresa"><option value="">Todas</option>{options(o.get('company') for o in closed)}</select></div>
<button type="reset" class="quitar">Quitar filtros</button></div>
</form>
{results_bar("")}""" if closed else ""
    process_link = (
        f'<p><a href="procesos/">Ver {closed_processes} procesos selectivos finalizados o sin novedades</a>.</p>'
        if closed_processes else ""
    )
    body = f"""<h1>Histórico de ofertas cerradas</h1>
<p class="resumen">Las webs oficiales suelen retirar cada ficha cuando finaliza el plazo. Este portal las conserva desde el inicio de su funcionamiento: {len(closed)} ofertas hasta la fecha.</p>
{process_link}
{empty}
{search}
<ol class="ofertas" id="lista-ofertas">
{rows}
</ol>"""
    return page("Histórico", body, "../", "historico", checked=checked)


COPY_BUTTON = ('<button type="button" class="copiar" hidden>Copiar'
               '<span class="sr-only"> el enlace de {}</span></button>')


def feed_list(entries: list[tuple[str, str]]) -> str:
    """Enlaces a feeds, cada uno con su botón «Copiar», que muestra listas.js."""
    return '<ul class="listas">' + "".join(
        f'<li><a href="../{e(href)}">{e(label)}</a>{COPY_BUTTON.format(e(label))}</li>' for label, href in entries
    ) + "</ul>"


def feed_table(entries: list[tuple], caption: str, show_caption: bool = True) -> str:
    """Tabla de feeds: el nombre y, en su columna, el botón «Copiar». Una entrada puede traer un tercer
    elemento, sus sublistas (las empresas de un organismo), que van como filas sangradas debajo."""
    def row(label: str, href: str, css: str = "") -> str:
        return (f'<tr{css}><th scope="row"><a href="../{e(href)}">{e(label)}</a></th>'
                f'<td>{COPY_BUTTON.format(e(label))}</td></tr>')
    rows = "".join(
        row(entry[0], entry[1]) + "".join(row(*sub, ' class="sublista"') for sub in (entry[2] if len(entry) > 2 else ()))
        for entry in entries
    )
    hidden = "" if show_caption else ' class="sr-only"'
    return (f'<table class="tabla-listas"><caption{hidden}>{e(caption)}</caption>\n'
            '<thead><tr><th scope="col">Lista</th><th scope="col">Enlace</th></tr></thead>\n'
            f"<tbody>{rows}</tbody></table>")


def feed_group(label: str, entries: list[tuple[str, str]]) -> str:
    return (f'<details class="grupo-listas"><summary>{e(label)} <span class="dato">({len(entries)})</span></summary>\n'
            f'{feed_table(entries, label, show_caption=False)}</details>')


def organism_feed_group(groups: list[tuple[str, list[tuple]]]) -> str:
    """«Por organismo»: una tabla por tipo de entidad, como en la página Organismos."""
    total = sum(len(members) for _, members in groups)
    tables = "\n".join(feed_table(members, label) for label, members in groups)
    return (f'<details class="grupo-listas"><summary>Por organismo <span class="dato">({total})</span></summary>\n'
            f"{tables}</details>")


def telegram_section(bot: str) -> str:
    bot = bot.lstrip("@")
    if not bot:
        return ""
    return f"""<h2 id="telegram">Por Telegram</h2>
<ol>
<li>Abra <a href="https://t.me/{e(bot)}">@{e(bot)}</a> en Telegram y pulse «Iniciar».</li>
<li>Escriba <code>/nuevo</code> y responda a las preguntas: palabras del título, áreas, comunidades autónomas y organismos. Puede omitir las que no le interesen.</li>
<li>A partir de ese momento, el bot le enviará un mensaje cada vez que se publique una oferta que cumpla sus criterios.</li>
</ol>
<p>La oferta debe cumplir todos los criterios elegidos: «analista» y Galicia avisa solo de las ofertas de analista en Galicia. Si elige organismos, también puede recibir los comunicados de sus procesos selectivos.</p>
<p>Las palabras se buscan en el título por su comienzo y sin distinguir tildes: «ingenier» encuentra «Ingeniero/a» e «Ingeniera». El título se compara tal como lo publica cada organismo, por lo que las ofertas en inglés o en catalán solo coinciden con palabras en ese idioma.</p>
<p>El bot avisa de las ofertas nuevas y de las que se vuelven a publicar. Los cambios de plazo o de número de plazas solo se notifican por RSS.</p>
<p>Puede tener hasta 10 avisos. Con <code>/avisos</code> puede consultar y borrar sus avisos, y con <code>/ayuda</code>, obtener la explicación completa. El bot solo guarda el identificador del chat y sus criterios; con <code>/baja</code> se borran de inmediato. Más información en <a href="../acerca/#datos-personales">Datos personales</a>.</p>
"""


def casillas(name: str, options: list[tuple[str, str]]) -> str:
    return "".join(f'<label class="casilla"><input type="checkbox" name="{name}" value="{e(value)}"> {e(label)}</label>\n'
                   for value, label in options)


def mail_section(sitekey: str, organisms: list) -> str:
    """Formulario de avisos por correo. Lo envía el navegador al worker (POST normal, sin JavaScript
    propio); el único script es el de Turnstile. Los valores son las claves de api/listas.json.
    organisms: [(grupo, [(id, nombre), …]), …]."""
    if not sitekey:
        return ""
    groups = "".join(
        f'<details><summary>{e(label)} <span class="dato">({len(members)})</span></summary>\n'
        f'<div class="opciones">\n{casillas("organismos", members)}</div></details>\n'
        for label, members in organisms)
    return f"""<h2 id="correo">Por correo electrónico</h2>
<p>Recibirá un correo cada mañana, solo los días en que haya ofertas nuevas o vueltas a publicar que cumplan sus criterios. La oferta debe cumplir todos los apartados que elija y, dentro de cada uno, basta con una opción. Los apartados que deje en blanco no filtran.</p>
<form class="form-correo" method="post" action="{AVISOS_URL}/correo/alta">
<p><label for="correo-direccion">Correo electrónico</label>
<input id="correo-direccion" name="correo" type="email" autocomplete="email" required></p>
<p><label for="correo-palabras">Palabras del título <span class="dato">(separadas por comas)</span></label>
<input id="correo-palabras" name="palabras" type="text" autocomplete="off" aria-describedby="ayuda-palabras">
<span id="ayuda-palabras" class="dato">Se buscan por su comienzo y sin distinguir tildes: «ingenier» encuentra «Ingeniero/a» e «Ingeniera». Hasta 10.</span></p>
<fieldset><legend>Áreas</legend>
<div class="opciones">
{casillas("areas", areas.BY_NAME)}</div></fieldset>
<fieldset><legend>Comunidades autónomas</legend>
<div class="opciones">
{casillas("ccaa", [(code, name) for name, code in CCAA.items()])}</div>
<label class="casilla"><input type="checkbox" name="sin_ccaa" value="1" checked> Incluir también las ofertas sin comunidad concreta</label></fieldset>
<fieldset><legend>Organismos</legend>
<p class="dato">Si no marca ninguno, recibirá avisos de todos, también de los que se incorporen al portal.</p>
{groups}<label class="casilla"><input type="checkbox" name="comunicados" value="1"> Recibir también los comunicados de los procesos selectivos de los organismos elegidos</label></fieldset>
<fieldset><legend>Teletrabajo</legend>
<label class="casilla"><input type="checkbox" name="teletrabajo" value="1"> Solo las ofertas cuya ficha menciona el teletrabajo</label></fieldset>
<div class="cf-turnstile" data-sitekey="{e(sitekey)}" data-language="es"></div>
<noscript><p class="nota">El formulario necesita JavaScript para la comprobación contra el envío automatizado. Sin él, puede usar los avisos por RSS.</p></noscript>
<p>Le enviaremos un enlace para confirmar el aviso: sin confirmar no se activa. Para añadir otro aviso, vuelva a rellenar el formulario con el mismo correo (hasta 10). Cada correo incluye un enlace para darse de baja, que borra su dirección y todos sus avisos. Más información en <a href="../acerca/#avisos-correo">Datos personales</a>.</p>
<p><button type="submit" class="boton">Crear el aviso</button></p>
</form>
<script src="{TURNSTILE}/turnstile/v0/api.js" async defer></script>
"""


def alerts_page(region_feeds: list, organism_feeds: list, checked: str, bot: str = "",
                area_feeds: list = (), sitekey: str = "", mail_organisms: list = ()) -> str:
    """organism_feeds: (grupo, [(organismo, feed, [(«Solo empresa», feed), …]), …]). Las sublistas solo
    aparecen si el organismo publica ofertas de varias empresas."""
    ways = []
    if bot:
        ways.append('<li><a href="#telegram"><strong>Por Telegram</strong><span>Un bot le envía un mensaje cuando se publica una oferta que cumple sus criterios.</span></a></li>')
    if sitekey:
        ways.append('<li><a href="#correo"><strong>Por correo electrónico</strong><span>Dos resúmenes al día, mañana y tarde, con las ofertas que cumplen sus criterios.</span></a></li>')
    if ways:
        ways.append('<li><a href="#rss"><strong>Por RSS</strong><span>Siga una lista desde su lector de RSS, sin registrarse ni facilitar datos personales.</span></a></li>')
        intro = (f'<p>Puede recibir los avisos de {"dos" if len(ways) == 2 else "tres"} formas:</p>\n'
                 f'<ul class="vias">\n{chr(10).join(ways)}\n</ul>')
    else:
        intro = ("<p>Los avisos funcionan mediante RSS. No es necesario registrarse ni facilitar un correo electrónico: "
                 "este portal no guarda ningún dato personal.</p>")
    body = f"""<h1>Recibir avisos de ofertas nuevas</h1>
{intro}
{telegram_section(bot)}{mail_section(sitekey, mail_organisms)}<h2 id="rss">{"Por RSS" if ways else "Cómo empezar"}</h2>
<p>RSS es un formato abierto para seguir las novedades de una web: un lector de RSS consulta las listas elegidas y reúne en un solo lugar lo que se va publicando. No requiere registro ni datos personales.</p>
<ol>
<li>Instale un lector de RSS, como Feedly o Inoreader, o la aplicación NetNewsWire en Mac y iPhone.</li>
<li>Elija una de las listas que figuran más abajo y copie su enlace.</li>
<li>Pegue el enlace en el lector, en la opción «Añadir fuente» o «Suscribirse».</li>
</ol>
<p>Las webs oficiales se consultan varias veces al día: cada 30 minutos por la mañana entre semana y con menos frecuencia por la tarde, de noche y en fin de semana. Cada lista incluye lo siguiente:</p>
<ul>
<li>«Todas las novedades» y las listas por organismo incluyen las ofertas y los anuncios de procesos.</li>
<li>Las listas por comunidad autónoma, por área, de teletrabajo y por empresa incluyen solo ofertas.</li>
<li>Las áreas se asignan de forma automática a partir del título y de la ficha, por lo que pueden contener errores. Una oferta puede figurar en más de un área.</li>
<li>«Ofertas que mencionan el teletrabajo» incluye las ofertas cuya ficha lo menciona. Las ofertas sin texto en la ficha no pueden comprobarse.</li>
<li>Cada oferta aparece al publicarse y de nuevo si cambia el plazo o el número de plazas, o si se reabre o se vuelve a publicar.</li>
<li>Algunos organismos publican ofertas de varias empresas: bajo su nombre puede seguirse una sola de ellas.</li>
<li>En <a href="../anuncios/">Procesos</a>, cada proceso en marcha dispone además de su propia lista.</li>
</ul>
<h3>Listas generales</h3>
{feed_list([("Todas las novedades", "feed.xml"), ("Solo anuncios de procesos", "feeds/anuncios.xml"),
            ("Ofertas que mencionan el teletrabajo", "feeds/teletrabajo.xml")])}
<h3>Otras listas</h3>
<form id="buscar-listas" class="buscador" role="search" aria-label="Buscar listas" hidden>
<label for="q-listas" class="sr-only">Buscar una comunidad autónoma, área, organismo o empresa</label>
<input id="q-listas" type="search" autocomplete="off" placeholder="Comunidad, área, organismo o empresa">
</form>
<p id="estado-listas" role="status"></p>
{feed_group("Por comunidad", region_feeds)}
{feed_group("Por área", list(area_feeds)) if area_feeds else ""}
{organism_feed_group(organism_feeds)}
<p id="estado-copia" class="sr-only" role="status"></p>
<h2>Reutilización de los datos</h2>
<p>Los datos también están disponibles en formato JSON, sin clave de acceso. La descripción de los ficheros y algunos ejemplos de uso figuran en <a href="../datos/">Datos abiertos</a>.</p>
<script src="../assets/listas.js" defer></script>"""
    return page("Recibir avisos", body, "../", "avisos", checked=checked, csp=CSP_CORREO if sitekey else CSP)


def and_join(items: list[str]) -> str:
    return " y ".join(filter(None, [", ".join(items[:-1]), items[-1]])) if items else ""


def about_page(sources: dict, checked: str, bot: str = "", base_url: str = DEFAULT_BASE_URL, mail: bool = False) -> str:
    # Solo un resumen por grupo: la lista completa, con ofertas y web oficial, está en Organismos.
    groups = by_group(sources)
    links = and_join([f'<a href="../organismos/#grupo-{key}">{e(label)}</a> ({len(members)})'
                      for key, label, members in groups])
    count = len(sources)
    webs = "1 web" if count == 1 else f"{count} webs"
    grupos = "un grupo" if len(groups) == 1 else f"{len(groups)} grupos"
    planned = f" Previstas: {e(and_join([p['name'] for p in PLANNED]))}." if PLANNED else ""
    via = "por " + and_join(["Telegram"] * bool(bot) + ["correo electrónico"] * mail + ["RSS"]).replace(" y ", " o ")
    telegram = ("<li><strong>Telegram:</strong> un bot le envía un mensaje cuando se publica una oferta que cumple "
                "sus criterios: palabras del título, áreas, comunidades autónomas u organismos.</li>\n") if bot else ""
    if mail:
        telegram += ("<li><strong>Correo electrónico:</strong> dos resúmenes al día (mañana y tarde) con las ofertas que cumplen sus "
                     "criterios, con los mismos apartados que el bot.</li>\n")
    sections = [("que-hay", "Contenido del portal"), ("organismos", "Organismos incluidos"),
                ("antes-de-inscribirte", "Antes de inscribirse"), ("como-buscar", "Cómo buscar"),
                ("guardar", "Guardar"), ("avisos", "Avisos"), ("de-donde", "Origen de los datos"), ("datos", "Datos abiertos"),
                ("quien", "Quién mantiene el portal"), ("responsabilidad", "Responsabilidad"),
                ("datos-personales", "Datos personales"), ("accesibilidad", "Accesibilidad"), ("contacto", "Contacto")]
    index = "".join(f'<li><a href="#{key}">{label}</a></li>' for key, label in sections)
    body = f"""<h1>Acerca de este portal</h1>
<p>{SITE_NAME} reúne las ofertas de empleo que las empresas públicas, las fundaciones y los centros de investigación del sector público publican en sus propias webs. Estas webs tienen formatos distintos, rara vez ofrecen alertas, no siempre son accesibles y sus ofertas no suelen figurar en otros buscadores de empleo. Este portal las consulta de forma periódica, presenta sus ofertas en un único lugar y avisa de las novedades.</p>
<nav aria-label="En esta página"><ul class="indice-grupos">{index}</ul></nav>
<h2 id="que-hay">Contenido del portal</h2>
<ul>
<li><strong>Incluye</strong> los puestos de entidades del sector público que contratan directamente, con su plazo y su ficha, y los procesos selectivos que anuncian, con sus comunicados por fases.</li>
<li><strong>No incluye</strong> las oposiciones de las Administraciones públicas (Administración General del Estado, comunidades autónomas y entidades locales). Para ellas, consulte los buscadores oficiales de empleo público y los boletines oficiales.</li>
</ul>
<h2 id="organismos">Organismos incluidos</h2>
<p>Actualmente se consultan {webs}, en {grupos}: {links}. La lista completa, con sus ofertas y su web oficial, figura en <a href="../organismos/">Organismos</a>.{planned} Para proponer la incorporación de un organismo, abra una <a href="{REPO}/issues">incidencia en GitHub</a>.</p>
<h2 id="antes-de-inscribirte">Antes de inscribirse, consulte la web oficial</h2>
<p>Este portal sirve para localizar ofertas; la inscripción se realiza siempre en la web oficial de cada organismo. Antes de presentar su candidatura, compruebe allí el plazo, los requisitos, las bases, la documentación necesaria y la forma de presentación. En caso de discrepancia, prevalece la información publicada por el organismo.</p>
<ul>
<li>Cada organismo tiene sus propias normas y procedimientos. Algunos requieren la inscripción en su portal; otros, el envío de la candidatura por correo electrónico o su presentación en persona; y algunos fijan el plazo únicamente en las bases.</li>
<li>Algunos organismos publican también ofertas o procesos en otros portales que no se recogen aquí. Si le interesa un organismo concreto, consulte también su web.</li>
<li>Los datos se obtienen de forma automática. Las personas que mantienen el portal comprueban periódicamente que se lean correctamente, pero no revisan cada oferta de forma individual: puede haber errores, retrasos o cambios que aún no figuren aquí.</li>
</ul>
<h2 id="como-buscar">Cómo buscar</h2>
<p>El buscador de la portada filtra las ofertas a medida que se escribe.</p>
<ul>
<li><strong>Basta con parte de una palabra:</strong> «adm» encuentra «administrativo» y «administración».</li>
<li><strong>Admite varias palabras:</strong> se muestran las ofertas que contienen todas ellas. «adm trag» encuentra las de Tragsa con «adm» en algún dato; «administrativ trag» es más precisa.</li>
<li><strong>No distingue mayúsculas ni tildes:</strong> «tecnico» encuentra «Técnico».</li>
<li><strong>Dónde busca:</strong> en el título, el código, la empresa, la ubicación y la comunidad autónoma, el departamento, el tipo de puesto, la convocatoria y el contrato. No busca en el texto completo de la ficha.</li>
<li><strong>Filtros:</strong> la búsqueda puede combinarse con «Filtros» (comunidad autónoma, área, tipo de contrato, empresa u organismo), con «Cierran en {SOON_DAYS} días» y, cuando hay ofertas que lo mencionan, con «Menciona teletrabajo». «Quitar filtros» restablece la búsqueda inicial.</li>
<li><strong>Orden:</strong> «Ordenar por» muestra primero las ofertas más recientes, las de plazo más próximo o las ordenadas por empresa.</li>
<li><strong>Sin resultados:</strong> si ninguna oferta abierta coincide, el portal ofrece buscar el mismo término en los procesos selectivos.</li>
<li><strong>Enlace a la búsqueda:</strong> la dirección de la página conserva la búsqueda y los filtros. Si la guarda en marcadores o la comparte, se abrirá con los mismos criterios.</li>
</ul>
<p>Los buscadores de <a href="../anuncios/">Procesos</a> y del <a href="../historico/">Histórico</a> funcionan del mismo modo.</p>
<h2 id="guardar">Guardar ofertas y procesos</h2>
<p>El botón «Guardar» de cada oferta o proceso lo añade a su selección. Al guardar el primero aparece el filtro «Guardadas» («Guardados» en Procesos), que muestra solo los seleccionados. Si una oferta se cierra o un proceso deja de estar en marcha, se indica en ese apartado, con su enlace y la opción de quitarlo.</p>
<p>Lo guardado se conserva solo en este navegador: no se sincroniza con otros dispositivos ni navegadores y se pierde si se borran los datos de este sitio web.</p>
<h2 id="avisos">Avisos</h2>
<p>Muchas de estas webs no permiten suscribirse ni recibir alertas. Este portal ofrece avisos de todas ellas {via}:</p>
<ul>
{telegram}<li><strong>RSS:</strong> permite seguir una lista desde un lector de RSS, como Feedly o Inoreader: todas las novedades, una comunidad autónoma, un área, un organismo o un único proceso. No requiere registro ni datos personales.</li>
</ul>
<p>Todas las listas y las instrucciones paso a paso figuran en <a href="../avisos/">Recibir avisos</a>.</p>
<h2 id="de-donde">Origen de los datos</h2>
<p>Las páginas públicas de empleo de cada organismo se consultan varias veces al día: cada 30 minutos por la mañana entre semana y con menos frecuencia por la tarde, de noche y en fin de semana. Solo se utilizan datos publicados y accesibles sin necesidad de cuenta, y nunca se realizan inscripciones de forma automatizada. El texto de cada oferta se reproduce tal como lo publica su organismo.</p>
<p>El área de cada oferta (en «Filtros») no la facilita la empresa: este portal la asigna a partir del título y, si no es suficiente, de la ficha o del sector del organismo. Tiene carácter orientativo y solo sirve para filtrar; una oferta puede tener dos áreas o ninguna.</p>
<p>El dato «Menciona teletrabajo» procede de la ficha: se buscan expresiones como «teletrabajo» o «trabajo a distancia» y se reproduce la frase literal, ya que las condiciones varían mucho entre ofertas. Si la ficha solo remite a las bases, no es posible saberlo y así se indica.</p>
<h2 id="datos">Datos abiertos</h2>
<p>Toda la información del portal está disponible en ficheros JSON, sin clave ni registro, con licencia CC BY 4.0, para su reutilización en webs, aplicaciones o análisis. La descripción de cada fichero y de cada campo, con ejemplos, figura en <a href="../datos/">Datos abiertos</a>.</p>
<h2 id="quien">Quién mantiene el portal</h2>
<p>{SITE_NAME} es un proyecto independiente, sin vinculación con la Administración ni con los organismos citados. Lo mantienen personas ajenas a la Administración, con sus propios recursos y limitaciones, y se sostiene gracias a las contribuciones y donaciones de la comunidad. Su código es abierto: cualquier persona puede consultarlo y proponer mejoras en <a href="{REPO}">GitHub</a>.</p>
<p>Titular del portal: {TITULAR}. Correo de contacto: {MAILTO}.</p>
<h2 id="responsabilidad">Responsabilidad</h2>
<p>La información de este portal tiene carácter orientativo. Aunque se procura que sea exacta y esté actualizada, puede contener errores u omisiones o no reflejar los últimos cambios, y no sustituye a las webs oficiales de los organismos ni a los boletines oficiales. El titular no responde de las decisiones que se tomen a partir de ella.</p>
<p>Los enlaces llevan a webs de terceros cuyo contenido y funcionamiento no dependen de este portal. Los nombres, las marcas y los textos de las ofertas y comunicados pertenecen a sus respectivos titulares; su mención no implica relación ni respaldo.</p>
<p>Se ruega hacer un uso responsable del portal, de sus avisos y de sus datos. Un uso abusivo, como las consultas automatizadas masivas, puede perjudicar el servicio para el resto de personas usuarias.</p>
<h2 id="datos-personales">Datos personales</h2>
<p>Este portal no utiliza cookies ni herramientas de analítica y {"solo solicita datos personales para los avisos" if bot or mail else "no solicita datos personales"}. Los ajustes de apariencia y las ofertas y procesos guardados se almacenan únicamente en su navegador. Tampoco reproduce las relaciones de personas candidatas de los procesos selectivos.</p>
<p>Las páginas se alojan en GitHub Pages (GitHub, Inc.), que registra la dirección IP de las visitas por motivos de seguridad, conforme a su propia política de privacidad.</p>{telegram_privacy(bot)}{mail_privacy(mail)}
<h2 id="accesibilidad">Accesibilidad</h2>
<p>Este portal pretende ser accesible para todas las personas. Las medidas adoptadas y las limitaciones conocidas se detallan en <a href="../accesibilidad/">Accesibilidad</a>. Las webs oficiales, sus bases en PDF y sus formularios de inscripción no dependen de este portal y pueden no ser accesibles.</p>
<h2 id="contacto">Contacto</h2>
<p>Para cualquier consulta, incluido el ejercicio de sus derechos sobre datos personales, puede escribir a {MAILTO}. Los errores y las propuestas de mejora también pueden comunicarse mediante una <a href="{REPO}/issues">incidencia en GitHub</a>.</p>"""
    return page("Acerca de", body, "../", "acerca", checked=checked)


def telegram_privacy(bot: str) -> str:
    if not bot:
        return ""
    return f"""
<h3 id="bot-telegram">Bot de avisos de Telegram</h3>
<p>Información sobre el tratamiento de datos del bot, conforme al Reglamento General de Protección de Datos (RGPD) y a la Ley Orgánica 3/2018, de Protección de Datos Personales:</p>
<ul>
<li><strong>Responsable:</strong> {TITULAR} ({MAILTO}).</li>
<li><strong>Datos:</strong> el identificador del chat y los criterios de sus avisos. No se guardan su nombre, su usuario ni sus mensajes.</li>
<li><strong>Finalidad:</strong> únicamente enviarle los avisos que solicite.</li>
<li><strong>Base jurídica:</strong> su consentimiento, que presta al guardar un aviso (artículo 6.1.a del RGPD). Puede retirarlo en cualquier momento.</li>
<li><strong>Conservación:</strong> hasta que los borre. Con <code>/baja</code> se borran todos sus datos de inmediato; si bloquea el bot, se borran en el siguiente envío.</li>
<li><strong>Destinatarios:</strong> no se ceden a terceros. Los datos se alojan en Cloudflare, Inc., que presta el servicio como encargada del tratamiento. Por ser una empresa estadounidense, pueden tratarse fuera del Espacio Económico Europeo, con las garantías del Marco de Privacidad de Datos UE-EE. UU. Los mensajes pasan además por Telegram, que los trata conforme a su propia política de privacidad.</li>
<li><strong>Derechos:</strong> con <code>/avisos</code> puede consultar sus datos y con <code>/baja</code>, suprimirlos. Para ejercer cualquier otro derecho (acceso, rectificación, supresión, oposición, limitación o portabilidad), escriba a {MAILTO}. Si considera que no se han atendido, puede reclamar ante la <a href="https://www.aepd.es/">Agencia Española de Protección de Datos</a>.</li>
</ul>"""


def mail_privacy(mail: bool) -> str:
    if not mail:
        return ""
    return f"""
<h3 id="avisos-correo">Avisos por correo electrónico</h3>
<p>Información sobre el tratamiento de datos de los avisos por correo, conforme al Reglamento General de Protección de Datos (RGPD) y a la Ley Orgánica 3/2018, de Protección de Datos Personales:</p>
<ul>
<li><strong>Responsable:</strong> {TITULAR} ({MAILTO}).</li>
<li><strong>Datos:</strong> su dirección de correo, los criterios de sus avisos y la fecha de alta.</li>
<li><strong>Finalidad:</strong> únicamente enviarle los avisos que solicite.</li>
<li><strong>Base jurídica:</strong> su consentimiento, que presta al confirmar el aviso desde el enlace que recibe por correo (artículo 6.1.a del RGPD). Puede retirarlo en cualquier momento.</li>
<li><strong>Conservación:</strong> hasta que se dé de baja con el enlace que incluye cada correo, que borra su dirección y todos sus avisos de inmediato. Si no confirma el aviso, sus datos se borran a las 48 horas.</li>
<li><strong>Destinatarios:</strong> no se ceden a terceros. Prestan el servicio como encargadas del tratamiento Cloudflare, Inc., que aloja los datos y comprueba con Turnstile que el formulario no lo envía un programa automático, y Piensa Solutions, que envía los correos. Por ser Cloudflare una empresa estadounidense, los datos pueden tratarse fuera del Espacio Económico Europeo, con las garantías del Marco de Privacidad de Datos UE-EE. UU.</li>
<li><strong>Derechos:</strong> para ejercer sus derechos de acceso, rectificación, supresión, oposición, limitación o portabilidad, escriba a {MAILTO}. Si considera que no se han atendido, puede reclamar ante la <a href="https://www.aepd.es/">Agencia Española de Protección de Datos</a>.</li>
</ul>"""


def accessibility_page(checked: str, mail: bool = False) -> str:
    body = f"""<h1>Accesibilidad</h1>
<p>Este portal pretende cumplir el nivel AA de las Pautas de Accesibilidad para el Contenido Web (WCAG) 2.2. Se trata de un objetivo de diseño, no de una certificación.</p>
<h2>Medidas adoptadas</h2>
<ul>
<li>Páginas estructuradas con encabezados, listas y etiquetas, que pueden utilizarse con teclado.</li>
<li>Toda la información está disponible sin JavaScript. Solo lo requieren los filtros y buscadores,{" el formulario de avisos por correo (por la comprobación contra el envío automatizado)," if mail else ""} el panel de apariencia, el menú desplegable en móvil, los botones «Copiar» de los avisos y «Guardar», y el botón flotante «Arriba» (sin él, queda el enlace «Volver arriba» al pie de página).</li>
<li>Texto de gran tamaño y contraste alto por defecto, con tema oscuro automático.</li>
<li>Panel «Aa» para elegir el tema (claro, sepia, oscuro, contraste alto o colores personalizados), la letra, el tamaño, el ancho del contenido y ayudas de lectura.</li>
<li>Revisión con la herramienta automática axe, en todos los temas y con los paneles principales abiertos.</li>
</ul>
<p>Los ajustes de apariencia y las selecciones guardadas se almacenan únicamente en su navegador y no se envían a ningún servidor.</p>
<h2>Limitaciones conocidas</h2>
<ul>
<li>Aún no se ha probado con personas usuarias de lectores de pantalla.</li>
<li>Los colores personalizados y el modo «Foco» pueden quedar por debajo del contraste recomendado si así se elige. En el caso de los colores, el panel lo advierte.</li>
<li>El texto de las ofertas se reproduce tal como lo publica cada organismo, para no alterar su sentido. Puede contener mayúsculas, abreviaturas o listas mal marcadas que no se corrigen.</li>
<li>Muchas ofertas remiten a bases y documentos en PDF que pueden no ser accesibles.</li>
<li>Los enlaces conducen a webs oficiales cuya accesibilidad no depende de este portal. Si encuentra una barrera en ellas, comuníquela al organismo que la publica, que es quien puede resolverla.</li>
</ul>
<h2>Comunicar una barrera</h2>
<p>Si encuentra una barrera en este portal, puede comunicarla mediante una <a href="{REPO}/issues">incidencia en GitHub</a> o escribiendo a {MAILTO}, para su corrección.</p>"""
    return page("Accesibilidad", body, "../", "accesibilidad", checked=checked)


# Documentación de la API en la página «Datos abiertos»: (claves, descripción). Un test comprueba que
# cubre todas las claves de cada fichero; al añadir una clave a la API hay que describirla aquí.
FILE_FIELDS = [
    (("version",), "Versión del formato (actualmente, 1). Dentro de una versión solo se añaden campos; renombrar o quitar uno obliga a cambiarla."),
    (("licencia",), "Licencia de reutilización."),
    (("documentacion",), "Enlace a esta página."),
    (("generado",), "Momento de generación del fichero (ISO 8601)."),
]
OFFER_FIELDS = [
    (("id",), "Identificador estable: la clave del organismo, dos puntos y el identificador interno de la oferta en su portal."),
    (("organismo",), "Clave del organismo (<code>organismos</code> en listas.json)."),
    (("codigo",), "Código o referencia que el portal publica con la oferta; <code>null</code> si no publica ninguno."),
    (("titulo", "titulo_original"), "Título sin el código interno que algunos portales añaden, y título literal del portal."),
    (("empresa",), "Empresa o entidad que contrata."),
    (("estado",), "<code>abierta</code> o <code>cerrada</code>, según las fechas del plazo y no según la etiqueta de la web."),
    (("ubicacion", "localidad", "comunidad"), "Ubicación literal, localidad deducida del título o de la ficha, y nombre de la comunidad autónoma."),
    (("ccaa", "provincia", "municipio"), "Códigos del INE de comunidad autónoma, provincia y municipio. Solo se asignan cuando el texto no deja dudas: «Sevilla» puede ser la provincia o la capital, y se queda en provincia."),
    (("plazas",), "Número de plazas."),
    (("tipo_contrato", "contrato"), "Tipo de contrato (<code>tipos_contrato</code> en listas.json), solo si la fuente lo indica con claridad, y texto literal del contrato."),
    (("convocatoria", "tipo_puesto", "departamento"), "Datos que la fuente publica con esas denominaciones, si los publica."),
    (("plazo_inicio", "plazo_fin", "plazo_hora"), "Fechas de inicio y fin del plazo (<code>AAAA-MM-DD</code>) y hora de cierre (<code>HH:MM</code>, hora peninsular). Sin hora, el último día cuenta completo."),
    (("publicada",), "Fecha de publicación según la fuente."),
    (("detectada", "cerrada"), "Momentos (ISO 8601) en que este portal detectó la oferta y en que se cerró."),
    (("republica",), "Código de la oferta anterior, si es una nueva publicación de aquella."),
    (("areas",), "Áreas profesionales (<code>areas</code> en listas.json). Clasificación orientativa que asigna este portal; puede haber varias o ninguna."),
    (("teletrabajo",), "Frase literal de la ficha que menciona el teletrabajo; <code>false</code> si la ficha tiene texto y no lo menciona; <code>null</code> si no puede saberse porque la ficha solo remite a las bases."),
    (("url", "url_inscripcion", "url_portal"), "Enlaces a la ficha oficial, a la inscripción oficial y a la ficha en este portal."),
]
PROCESS_FIELDS = [
    (("id",), "Identificador estable del proceso."),
    (("organismo",), "Clave del organismo (<code>organismos</code> en listas.json)."),
    (("nombre",), "Nombre literal del proceso."),
    (("tipo", "acceso", "tipo_contrato", "sistema"), "Tipo de proceso, tipo de acceso, tipo de contrato y sistema de selección (<code>tipos_proceso</code>, <code>accesos</code>, <code>tipos_contrato</code> y <code>sistemas</code> en listas.json), si constan."),
    (("estado",), "Situación del proceso (<code>estados_proceso</code> en listas.json)."),
    (("plazo_fin", "plazo_hora", "url_inscripcion"), "Fin del plazo, hora de cierre y enlace de inscripción, solo mientras la inscripción está abierta."),
    (("url",), "Página o documento oficial del proceso."),
    (("comunicados",), "Comunicados del proceso, del más reciente al más antiguo, con <code>fecha</code> (<code>AAAA-MM-DD</code> o <code>null</code>), <code>titulo</code> y <code>url</code>. No incluye relaciones de personas."),
]
NEWS_FIELDS = [
    (("id",), "Identificador estable: la misma novedad conserva siempre el mismo <code>id</code>, de modo que puede avisarse una sola vez."),
    (("fecha",), "Momento (ISO 8601) en que este portal detectó la novedad."),
    (("tipo",), "<code>oferta</code> o <code>comunicado</code>."),
    (("evento",), "Solo ofertas: <code>new</code> (nueva) o <code>republished</code> (nueva publicación)."),
    (("organismo",), "Clave del organismo (<code>organismos</code> en listas.json)."),
    (("ccaa", "areas", "teletrabajo"), "Solo ofertas: como en ofertas.json."),
    (("proceso",), "Solo comunicados: nombre del proceso."),
    (("titulo",), "Título de la oferta o del comunicado."),
    (("detalle",), "Solo ofertas: resumen en una línea con la empresa, la ubicación, las plazas y el plazo."),
    (("url",), "Ofertas: ficha en este portal. Comunicados: documento oficial."),
]


LIST_FIELDS = [
    (("comunidades",), "Comunidades autónomas: <code>ccaa</code> (código del INE) y <code>nombre</code>."),
    (("provincias",), "Provincias: <code>provincia</code> (código del INE), <code>nombre</code> en castellano y <code>ccaa</code>, su comunidad autónoma."),
    (("organismos",), "Organismos: <code>id</code>, <code>nombre</code> y <code>grupo</code>."),
    (("areas", "grupos", "tipos_contrato", "tipos_proceso", "accesos", "sistemas", "estados_proceso"),
     "Áreas profesionales, grupos de organismos, tipos de contrato, tipos de proceso, tipos de acceso, sistemas de selección y estados de los procesos, cada uno con <code>id</code> y <code>nombre</code>."),
]


def field_table(fields: list[tuple[tuple[str, ...], str]], caption: str) -> str:
    """Tabla «Campo | Descripción» de un fichero de la API; datos.js filtra sus filas con el buscador."""
    rows = "".join(f'<tr><th scope="row">{"<br>".join(f"<code>{key}</code>" for key in keys)}</th><td>{text}</td></tr>'
                   for keys, text in fields)
    return (f'<table class="campos"><caption class="sr-only">{caption}</caption>\n'
            f'<thead><tr><th scope="col">Campo</th><th scope="col">Descripción</th></tr></thead>\n<tbody>{rows}</tbody></table>')


def code_example(unix: str, windows: str, js: str) -> str:
    """Un ejemplo para cada sistema. Sin JavaScript se ven los tres seguidos; datos.js los convierte en pestañas."""
    blocks = (("unix", "macOS y Linux (Terminal)", unix), ("windows", "Windows (PowerShell)", windows),
              ("js", "JavaScript (navegador)", js))
    return '<div class="ejemplo">' + "".join(
        f'<div class="ejemplo-bloque" data-sistema="{key}"><p class="sistema">{label}</p><pre><code>{code}</code></pre></div>'
        for key, label, code in blocks) + "</div>"


def open_data_page(checked: str, base_url: str = DEFAULT_BASE_URL) -> str:
    api = f"{base_url}api/"
    link = '<li><a href="#{}">{}</a></li>'.format
    fields = "".join(link(*item) for item in (("formato", "Formato común"), ("ofertas", "Ofertas"),
                                              ("procesos", "Procesos"), ("novedades", "Novedades"), ("listas", "Listas")))
    index = (link("ficheros", "Ficheros") + link("ejemplos", "Ejemplos")
             + f'<li><a href="#campos">Campos</a>: <ul>{fields}</ul></li>'
             + link("uso-responsable", "Uso responsable") + link("licencia", "Licencia"))
    example_open = code_example(
        f"""curl -s {e(api)}ofertas.json | jq '.ofertas[] | select(.estado == "abierta" and .ccaa == "01") | {{titulo, empresa, plazo_fin, url}}'""",
        f"""(Invoke-RestMethod {e(api)}ofertas.json).ofertas |
  Where-Object {{ $_.estado -eq "abierta" -and $_.ccaa -eq "01" }} |
  Select-Object titulo, empresa, plazo_fin, url""",
        f"""const datos = await (await fetch("{e(api)}ofertas.json")).json();
const abiertas = datos.ofertas.filter(o =&gt; o.estado === "abierta" &amp;&amp; o.ccaa === "01");""")
    example_news = code_example(
        f"""curl -s {e(api)}novedades.json | jq '.novedades[] | select(.tipo == "oferta" and .ccaa == "12") | {{titulo, url}}'""",
        f"""(Invoke-RestMethod {e(api)}novedades.json).novedades |
  Where-Object {{ $_.tipo -eq "oferta" -and $_.ccaa -eq "12" }} |
  Select-Object titulo, url""",
        f"""const datos = await (await fetch("{e(api)}novedades.json")).json();
const galicia = datos.novedades.filter(n =&gt; n.tipo === "oferta" &amp;&amp; n.ccaa === "12");""")
    body = f"""<h1>Datos abiertos</h1>
<p>Toda la información de este portal está disponible en ficheros JSON para su reutilización en webs, aplicaciones o análisis. No se requiere clave ni registro, y los ficheros pueden leerse desde cualquier web (CORS abierto). Se generan de nuevo con cada actualización del portal, hasta cada 30 minutos en horario laboral.</p>
<nav class="indice-datos" aria-label="En esta página"><ul>{index}</ul></nav>
<h2 id="ficheros">Ficheros</h2>
<ul>
<li><a href="../api/ofertas.json">ofertas.json</a>: todas las ofertas, abiertas y cerradas.</li>
<li><a href="../api/procesos.json">procesos.json</a>: los procesos selectivos y sus comunicados, por fases.</li>
<li><a href="../api/novedades.json">novedades.json</a>: las ofertas y los comunicados nuevos de los últimos {NEWS_DAYS} días. Es el fichero más adecuado para crear avisos propios.</li>
<li><a href="../api/listas.json">listas.json</a>: el nombre de cada clave que usan los demás ficheros (comunidades autónomas, organismos, áreas, tipos de contrato…).</li>
</ul>
<p>Las <a href="../avisos/">listas RSS de avisos</a> también pueden reutilizarse.</p>
<h2 id="ejemplos">Ejemplos</h2>
<p>En macOS (15 o posterior) y en muchas distribuciones de Linux, <code>curl</code> y <code>jq</code> vienen instalados; si falta <code>jq</code>, puede instalarse con el gestor de paquetes. En Windows, PowerShell no necesita nada más.</p>
<h3>Ofertas abiertas en Andalucía</h3>
<p>Con el código del INE de la comunidad autónoma (<code>01</code>), y su título, empresa, fin del plazo y enlace:</p>
{example_open}
<h3>Novedades de ofertas en Galicia</h3>
<p>Con el código del INE <code>12</code>, y su título y su enlace:</p>
{example_news}
<p id="estado-copia" class="sr-only" role="status"></p>
<h2 id="campos">Campos de cada fichero</h2>
<form id="buscar-campos" class="buscador" role="search" aria-label="Buscar campos" hidden>
<label for="q-campos" class="sr-only">Buscar un campo por nombre o descripción</label>
<input id="q-campos" type="search" autocomplete="off" placeholder="Campo o descripción (p. ej., plazo)">
</form>
<p id="estado-campos" role="status"></p>
<section class="campos-fichero" aria-labelledby="formato">
<h3 id="formato">Formato común</h3>
<p>Todos los ficheros comienzan con estos campos:</p>
{field_table(FILE_FIELDS, "Campos comunes a todos los ficheros")}
<p>Un dato que la fuente no facilita vale <code>null</code>. Los textos de ofertas y comunicados se reproducen tal como los publica cada organismo.</p>
</section>
<section class="campos-fichero" aria-labelledby="ofertas">
<h3 id="ofertas">Ofertas (ofertas.json)</h3>
<p>El campo <code>ofertas</code> contiene todas las ofertas guardadas desde el inicio del portal, abiertas y cerradas, con estos campos:</p>
{field_table(OFFER_FIELDS, "Campos de cada oferta en ofertas.json")}
</section>
<section class="campos-fichero" aria-labelledby="procesos">
<h3 id="procesos">Procesos (procesos.json)</h3>
<p>El campo <code>procesos</code> contiene los procesos selectivos, con los datos de su comunicado más reciente:</p>
{field_table(PROCESS_FIELDS, "Campos de cada proceso en procesos.json")}
</section>
<section class="campos-fichero" aria-labelledby="novedades">
<h3 id="novedades">Novedades (novedades.json)</h3>
<p>El campo <code>dias</code> indica el periodo que abarca el fichero ({NEWS_DAYS} días), y <code>novedades</code> contiene, de la más reciente a la más antigua, las ofertas nuevas o publicadas de nuevo que siguen abiertas y los comunicados nuevos de los procesos:</p>
{field_table(NEWS_FIELDS, "Campos de cada novedad en novedades.json")}
</section>
<section class="campos-fichero" aria-labelledby="listas">
<h3 id="listas">Listas (listas.json)</h3>
<p>Relaciona cada clave con su nombre:</p>
{field_table(LIST_FIELDS, "Listas de listas.json")}
</section>
<h2 id="uso-responsable">Uso responsable</h2>
<p>Este portal lo mantienen personas ajenas a la Administración, con recursos limitados, gracias a las contribuciones y donaciones de la comunidad. Se ruega hacer un uso responsable de los datos:</p>
<ul>
<li>Los ficheros se actualizan, como mucho, cada 30 minutos; no es necesario consultarlos con mayor frecuencia.</li>
<li>Para detectar novedades, utilice novedades.json en lugar de descargar ofertas.json completo en cada consulta.</li>
<li>Si su servicio tiene muchas personas usuarias, guarde una copia de los ficheros en su servidor en lugar de que cada navegador los descargue de este portal.</li>
</ul>
<h2 id="licencia">Licencia y atribución</h2>
<p>Los datos pueden reutilizarse con la licencia <a href="https://creativecommons.org/licenses/by/4.0/deed.es">CC BY 4.0</a>, citando «{SITE_NAME}» y enlazando este portal. Los textos, documentos y enlaces de cada oferta y comunicado pertenecen a su organismo.</p>
<p>Si ofrece un servicio basado en estos datos, indique a sus personas usuarias que la inscripción se realiza en la web oficial de cada organismo: cada oferta incluye sus enlaces en <code>url</code> y <code>url_inscripcion</code>.</p>
<script src="../assets/datos.js" defer></script>"""
    return page("Datos abiertos", body, "../", "datos", checked=checked,
                description="Ofertas de empleo del sector público en ficheros JSON abiertos, con licencia CC BY 4.0")


def write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def offer_summary(offer: dict) -> str:
    parts = [
        offer.get("company"), where(offer), seats(offer.get("positions")),
        f"Plazo: {long_date(offer.get('deadline'))}"
        + (f", a las {offer['deadline_time']}" if offer.get("deadline") and offer.get("deadline_time") else ""),
    ]
    return " · ".join(str(p) for p in parts if p)


def load_all(data: Path) -> tuple[dict, list, list]:
    offers, events, announcements = {}, [], []
    for source in ACTIVE:
        folder = data / source.id
        for record in store.load(folder / "offers.json", {}).values():
            offers[record["id"]] = record
        events += store.load(folder / "events.json", [])
        announcements += list(store.load(folder / "announcements.json", {}).values())
    return offers, events, announcements


def news(offers: dict, events: list, announcements: list, sources: dict, base_url: str,
         now: datetime) -> list[dict]:
    """Ofertas nuevas o republicadas que siguen abiertas y comunicados de procesos, de los últimos
    NEWS_DAYS días. Es lo que el worker de avisos cruza con las suscripciones: el id no cambia
    entre ejecuciones, así que cada novedad se avisa una sola vez."""
    since = now - timedelta(days=NEWS_DAYS)
    group_of = {s.id: s.group for s in sources.values()}
    items = []
    for event in events:
        offer = offers.get(event["offer"])
        if (offer is None or offer["status"] != "open" or event["kind"] not in ("new", "republished")
                or datetime.fromisoformat(event["at"]) < since):
            continue
        items.append({
            "id": f"{event['offer']}/{event['kind']}/{event['at']}", "fecha": event["at"],
            "tipo": "oferta", "evento": event["kind"], "organismo": offer["source"],
            "ccaa": CCAA.get(offer.get("region") or ""),
            "areas": areas.offer_areas(offer, group_of.get(offer["source"], ""))[0],
            "teletrabajo": teletrabajo.mention(offer),
            "titulo": humane_caps(offer["title"]), "detalle": offer_summary(offer),
            "url": base_url + offer_path(offer),
        })
    for item in announcements:
        seen = item.get("first_seen")
        if item.get("baseline") or not seen or datetime.fromisoformat(seen) < since:
            continue
        items.append({
            "id": f"anuncio/{item['process']}/{item['date']}/{item['title'][:80]}", "fecha": seen,
            "tipo": "comunicado", "organismo": item["source"], "proceso": humane_caps(item["process"]),
            "titulo": humane_caps(item["title"]), "url": item["url"],
        })
    return sorted(items, key=lambda item: item["fecha"], reverse=True)


def lists(sources: dict) -> dict:
    """Claves de la API con su nombre: las de los avisos (comunidades, organismos y áreas) y las de
    los campos codificados de ofertas y procesos."""
    named = lambda labels: [{"id": key, "nombre": label} for key, label in labels.items()]
    return {
        "comunidades": [{"ccaa": code, "nombre": name} for name, code in CCAA.items()],
        "provincias": [{"provincia": code, "nombre": name, "ccaa": ccaa} for code, name, ccaa in provinces()],
        "organismos": [{"id": s.id, "nombre": s.name, "grupo": s.group} for s in sources.values()],
        "areas": named(dict(areas.BY_NAME)),
        "grupos": named(GROUPS),
        "tipos_contrato": named(KINDS),
        "tipos_proceso": named(PROCESS_TYPES),
        "accesos": named(ACCESS),
        "sistemas": named(SYSTEMS),
        "estados_proceso": named(STATES),
    }


def processes(announcements: list) -> list[dict]:
    """Procesos con sus comunicados. Los datos del proceso son los de su lectura más reciente."""
    result = []
    for notices in process_groups(announcements):
        latest = notices[0]
        result.append({
            "id": process_id(notices), "organismo": latest["source"], "nombre": latest["process"],
            "tipo": via_of(latest), "acceso": latest.get("access"), "tipo_contrato": latest.get("contract"),
            "sistema": latest.get("system"), "estado": latest.get("state", "curso"),
            "plazo_fin": latest.get("deadline"), "plazo_hora": latest.get("deadline_time"),
            "url": latest.get("process_url"), "url_inscripcion": latest.get("apply_url"),
            "comunicados": [{"fecha": n.get("date") or None, "titulo": n["title"], "url": n["url"]} for n in notices],
        })
    return result


def public_offer(offer: dict, group: str, base_url: str) -> dict:
    """Oferta de api/ofertas.json: el texto de la fuente tal cual, con claves en castellano."""
    return {
        "id": offer["id"], "organismo": offer["source"], "codigo": offer.get("code"), "titulo": offer["title"],
        "titulo_original": offer.get("source_title") or offer["title"],
        "empresa": offer.get("company"), "estado": "abierta" if offer["status"] == "open" else "cerrada",
        "ubicacion": offer.get("location"), "localidad": offer.get("place"), "comunidad": offer.get("region"),
        **codes_of(offer.get("region"), offer.get("location"), offer.get("place"), location_from_title(offer["title"])),
        "plazas": offer.get("positions"), "tipo_contrato": offer.get("kind"), "contrato": offer.get("contract"),
        "convocatoria": offer.get("category"), "tipo_puesto": offer.get("family"),
        "departamento": offer.get("department"),
        "plazo_inicio": offer.get("opens_on"), "plazo_fin": offer.get("deadline"),
        "plazo_hora": offer.get("deadline_time"), "publicada": offer.get("published_on"),
        "detectada": offer["first_seen"], "cerrada": offer.get("closed_at"), "republica": offer.get("parent_ref"),
        "areas": areas.offer_areas(offer, group)[0], "teletrabajo": teletrabajo.mention(offer),
        "url": offer["url"], "url_inscripcion": offer.get("apply_url"), "url_portal": base_url + offer_path(offer),
    }


def build(data: Path, out: Path, base_url: str, now: datetime, checked_at: datetime | None = None) -> None:
    offers, events, announcements = load_all(data)
    sources = {s.id: s for s in ACTIVE}
    today = now.astimezone(MADRID).date()
    moment = (checked_at or now).astimezone(MADRID)
    checked = f"{long_date(moment.date().isoformat())} a las {moment:%H:%M}"
    open_offers = [o for o in offers.values() if o["status"] == "open"]
    closed = [o for o in offers.values() if o["status"] == "closed"]
    group_of = {s.id: s.group for s in ACTIVE}

    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(ASSETS, out / "assets")
    write(out / ".nojekyll", "")
    write(out / "index.html", index_page(open_offers, today, checked, sources))
    groups = process_groups(announcements)
    live = [g for g in groups if is_live(g)]
    running = {s.id: sum(g[0]["source"] == s.id for g in live) for s in ACTIVE}
    write(out / "organismos/index.html", organisms_page(sources, open_offers, checked, running, TELEGRAM_BOT))
    for source in ACTIVE:
        write(out / "organismos" / source.id / "index.html", organism_page(
            source, open_offers, today, checked, [g for g in live if g[0]["source"] == source.id], TELEGRAM_BOT))
    for offer in offers.values():
        write(out / offer_path(offer) / "index.html", offer_page(offer, sources, today, checked, base_url))
    write(out / "anuncios/index.html", announcements_page(announcements, checked, sources, today))
    write(out / "historico/index.html", history_page(closed, checked, sum(not is_live(g) for g in groups)))
    write(out / "historico/procesos/index.html", closed_processes_page(announcements, checked, sources, today))
    write(out / "acerca/index.html", about_page(sources, checked, TELEGRAM_BOT, base_url, bool(CORREO_SITEKEY)))
    write(out / "accesibilidad/index.html", accessibility_page(checked, bool(CORREO_SITEKEY)))
    write(out / "datos/index.html", open_data_page(checked, base_url))
    write(out / "404.html", page(
        "Página no encontrada",
        '<h1>Página no encontrada</h1><p>La página solicitada no existe o ha cambiado de dirección.</p>'
        '<p><a href="/">Ir al listado de ofertas</a>.</p>',
        "/",
    ))

    offer_url = lambda offer: base_url + offer_path(offer)
    offer_feed = feeds.offer_items(offers, events, offer_url, offer_summary)
    notice_feed = feeds.announcement_items(announcements)

    def emit(path: str, title: str, items: list) -> None:
        write(out / path, feeds.render(
            f"{title} · {SITE_NAME}", TAGLINE, base_url + path, base_url, items, now,
        ))

    emit("feed.xml", "Todas las novedades", offer_feed + notice_feed)
    emit("feeds/anuncios.xml", "Anuncios de procesos", notice_feed)
    region_feeds = []
    for region in REGIONS:
        path = f"feeds/comunidad-{slug(region)}.xml"
        emit(path, region, [i for i in offer_feed if (i["offer"].get("region") or UNKNOWN) == region])
        region_feeds.append((region, path))
    offer_area = {id_: areas.offer_areas(o, group_of.get(o["source"], ""))[0] for id_, o in offers.items()}
    area_feeds = []
    for area, name in areas.BY_NAME:
        path = f"feeds/area-{area}.xml"
        emit(path, name, [i for i in offer_feed if area in offer_area[i["offer"]["id"]]])
        area_feeds.append((name, path))
    emit("feeds/teletrabajo.xml", "Ofertas que mencionan el teletrabajo",
         [i for i in offer_feed if isinstance(teletrabajo.mention(i["offer"]), str)])
    organism_paths = {}
    for source in ACTIVE:
        path = f"feeds/organismo-{source.id}.xml"
        emit(path, source.name, [i for i in offer_feed if i["offer"]["source"] == source.id]
             + [i for i in notice_feed if i["source"] == source.id])
        organism_paths[source.id] = path
    for notices in groups:
        if is_live(notices):
            items = [i for i in notice_feed
                     if (i["source"], i["process"]) == (notices[0]["source"], notices[0]["process"])]
            emit(f"feeds/proceso-{process_id(notices)}.xml", humane_caps(notices[0]["process"]), items)
    # Se generan todas las listas por empresa (hay suscripciones), pero en la página solo se enseñan
    # bajo su organismo cuando este publica de varias: las demás repetirían el organismo con otro nombre.
    companies = {}
    for company in sorted({o["company"] for o in offers.values() if o.get("company")}):
        path = f"feeds/empresa-{slug(company)}.xml"
        emit(path, company, [i for i in offer_feed if i["offer"].get("company") == company])
        companies[company] = path
    organism_feeds = []
    for _, label, members in by_group(sources):
        entries = []
        for source in sorted(members, key=lambda s: (not is_holding(s), slug(s.name))):
            names = sorted({o["company"] for o in offers.values() if o["source"] == source.id and o.get("company")})
            subs = [(f"Solo {name}", companies[name]) for name in names if name != source.name] if len(names) > 1 else []
            entries.append((member_name(source), organism_paths[source.id], subs))
        organism_feeds.append((label, entries))
    mail_organisms = [(label, [(s.id, member_name(s)) for s in members]) for _, label, members in by_group(sources)]
    write(out / "avisos/index.html", alerts_page(region_feeds, organism_feeds, checked, TELEGRAM_BOT, area_feeds,
                                                 CORREO_SITEKEY, mail_organisms))

    stamp = now.isoformat(timespec="seconds")

    def api(name: str, **content) -> None:
        write(out / "api" / name, json.dumps({**API_HEAD, "documentacion": f"{base_url}datos/", "generado": stamp, **content}, ensure_ascii=False, indent=1))

    api("ofertas.json", ofertas=[public_offer(o, group_of.get(o["source"], ""), base_url) for o in offers.values()])
    api("novedades.json", dias=NEWS_DAYS, novedades=news(offers, events, announcements, sources, base_url, now))
    api("procesos.json", procesos=processes(announcements))
    api("listas.json", **lists(sources))
    pages = (
        [""] + [href for _, href, _ in NAV + FOOTER_NAV if href] + ["historico/procesos/"]
        + [f"organismos/{s.id}/" for s in ACTIVE]
        + [offer_path(o) for o in offers.values()]
    )
    write(out / "sitemap.xml",
          '<?xml version="1.0" encoding="UTF-8"?>\n'
          '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
          + "".join(f"<url><loc>{e(base_url + p)}</loc></url>" for p in pages)
          + "</urlset>\n")
    write(out / "robots.txt", f"User-agent: *\nAllow: /\nSitemap: {base_url}sitemap.xml\n")


def main() -> None:
    now = datetime.now(timezone.utc)
    base_url = os.environ.get("BASE_URL", DEFAULT_BASE_URL)
    checked = os.environ.get("CHECKED_AT")
    build(
        Path("data"), Path("_site"), base_url, now,
        datetime.fromisoformat(checked) if checked else None,
    )
    print("Web generada en _site/")


if __name__ == "__main__":
    main()
