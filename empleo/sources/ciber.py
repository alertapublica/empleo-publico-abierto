"""CIBER (Consorcio Centro de Investigación Biomédica en Red).

`www.ciberisciii.es/empleo` carga un servicio público JSONP de Cientifis: tres listados
independientes (ordinario, reposición y estabilización), paginados de 15 en 15; `start` es el
número de página, desde 1. Se comprueban páginas, total y perfiles únicos antes de devolver datos.
El método de reposición es `getPerfilesReposicionPaginado`, sin «Tasa». Lecturas del 2026-11-15:
5 + 4 + 0 filas «Abiertas», pero una ya vencida: mandan inicio y fin, sin hora publicada.

Cada IdPerfil tiene ficha pública y `getPerfil`: perfil, funciones, requisitos, contrato literal,
categoría profesional, centro, provincia e inscripción. No hay título breve: el título junta la
categoría y la titulación académica literales de la tabla («Doctor · Doctorado en Medicina»), sin
el punto final, y el código público convocatoria/perfil va aparte (también aparece así en la
tabla). El perfil completo queda en la ficha. «Doctor» incluye coordinación de infraestructuras;
«Titulado Superior», predoctorales y gestión: no equivalen a una función investigadora. Se guarda
la categoría en `category`, el contrato en `contract` y el área CIBER (incluida UT) en `department`.
Sin cifra estructurada de plazas no se presupone una, ni se extraen números del texto del perfil.

Solo ofertas en plazo. El histórico por fases no se recorre ni se descargan las listas de personas
cuyos enlaces devuelve el servicio. Un centro anfitrión (Bellvitge, Clínic, etc.) no es el empleador:
no se excluye por centro. Para futuras republicaciones locales, clave = IdPerfil/enlace CIBER.
TLS con el cliente común; robots de la web permite empleo, el de Cientifis redirige al login.
Pausa de 4 s y ninguna inscripción automatizada. Diagnóstico y evidencias en sondeo/codex/sondeo-31/
(local, fuera de git).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from html import escape
from urllib.parse import parse_qs, urlencode, urlsplit

from ..dates import numeric_date
from ..http import Client
from ..model import ListedOffer, OfferDetail, SourceLayoutError, deadline_passed, today_madrid
from .base import Source

PAGE = "https://www.ciberisciii.es/empleo"
DETAIL = PAGE + "/detalle-oferta?id="
SERVICE = "https://intranet.cientifis.com/Ciber/WebServices/Web/Empleo/ws_Empleo.asmx/"
METHODS = ("getPerfilesPaginado", "getPerfilesReposicionPaginado", "getPerfilesEstabilizacionPaginado")
COMPANY = "CIBER"
PER_PAGE = 15
MAX_PAGES = 10  # por listado; si crece, fallar antes que truncarlo
KINDS = {
    "Interinidad": "temporal",
    "Predoctoral Ley de la ciencia": "temporal",
    "Postdoctoral Ley de la ciencia": "temporal",
    "Indefinido": "indefinido",
    "Indefinido actividades científico-técnicas": "indefinido",
    "Formativo para obtención de práctica profesional": "practicas",
}


def listing_url(method: str, page: int = 1) -> str:
    return SERVICE + method + "?" + urlencode({
        "callback": "empleo", "start": page, "limit": PER_PAGE, "Ciber": "SinEsp", "Estado": "Abiertas",
        "Provincia": "SinEsp", "CategoriaProfesional": "SinEsp", "Ano": "SinEsp",
    })


def detail_url(ref: str) -> str:
    return SERVICE + "getPerfil?" + urlencode({"callback": "empleo", "PerfilId": ref})


def parse_jsonp(text: str):
    wrapped = re.fullmatch(r"\s*empleo\((.*)\);?\s*", text, re.S)
    if wrapped is None:
        raise SourceLayoutError("CIBER: respuesta sin JSONP empleo(...)")
    try:
        return json.loads(wrapped.group(1))
    except json.JSONDecodeError as error:
        raise SourceLayoutError("CIBER: JSON ilegible") from error


def _text(row: dict, key: str, required: bool = False) -> str:
    value = row.get(key)
    if not isinstance(value, str) or (required and not value.strip()):
        raise SourceLayoutError(f"CIBER: campo {key} ausente o ilegible")
    return value.strip()


def _identity(row: dict) -> tuple[str, str]:
    ref, call = _text(row, "IdPerfil", True), _text(row, "IdConvocatoria", True)
    if not ref.isascii() or not ref.isdigit() or not call.isascii() or not call.isdigit():
        raise SourceLayoutError("CIBER: identificador de perfil o convocatoria ilegible")
    return ref, call


def _period(row: dict) -> tuple[str, str]:
    values = [_text(row, k, True) for k in ("FechaDesde", "FechaHasta")]
    try:
        if any(re.fullmatch(r"\d{2}/\d{2}/\d{4}", v) is None for v in values):
            raise ValueError("formato")
        first, last = map(numeric_date, values)
        if first > last:
            raise ValueError("inicio posterior al fin")
    except ValueError as error:
        raise SourceLayoutError(f"CIBER: plazo ilegible: {values!r}") from error
    return first, last


def parse_page(text: str) -> tuple[int, int, int, list[dict]]:
    data = parse_jsonp(text)
    if not isinstance(data, dict) or not isinstance(data.get("Lista"), list):
        raise SourceLayoutError("CIBER: listado sin Lista")
    numbers = [data.get(k) for k in ("ElementosEncontrados", "Paginas", "PaginaActual")]
    if any(type(n) is not int or n < 0 for n in numbers):
        raise SourceLayoutError("CIBER: paginación ilegible")
    total, pages, current = numbers
    rows = data["Lista"]
    if pages != (total + PER_PAGE - 1) // PER_PAGE or not 1 <= current <= max(1, pages):
        raise SourceLayoutError("CIBER: páginas y total incoherentes")
    if len(rows) != min(PER_PAGE, max(0, total - (current - 1) * PER_PAGE)):
        raise SourceLayoutError("CIBER: listado incompleto para el total anunciado")
    for row in rows:
        if not isinstance(row, dict):
            raise SourceLayoutError("CIBER: fila ilegible")
        _identity(row)
        _period(row)
        for key in ("CategoriaProfesional", "Intranet", "Estado", "ProvinciaPerfil"):
            _text(row, key, True)
        seats = row.get("Plazas")
        if seats is not None and (type(seats) is not int or seats < 1):
            raise SourceLayoutError("CIBER: número de plazas ilegible")
    return total, pages, current, rows


def title(row: dict) -> str:
    """Categoría y titulación literales, como las muestra la tabla: el servicio no da otro título."""
    degree = _text(row, "TitulacionAcademica").rstrip(" .")
    return " · ".join(v for v in (_text(row, "CategoriaProfesional", True), degree) if v)


def _paragraphs(value: str) -> str:
    # Algunos campos del servicio traen los saltos escapados dos veces. Son texto, no HTML.
    return "".join(f"<p>{escape(p.strip())}</p>" for p in value.replace("\\r\\n", "\n").splitlines() if p.strip())


def parse_detail(text: str, ref: str) -> dict:
    data = parse_jsonp(text)
    if not isinstance(data, dict) or _identity(data)[0] != ref:
        raise SourceLayoutError("CIBER: ficha de otro perfil o sin identificador")
    first, last = _period(data)
    for key in ("Perfil", "CategoriaProfesional", "TipoContrato", "Provincia", "Estado"):
        _text(data, key, True)
    if type(data.get("ContieneErrores")) is not bool or data["ContieneErrores"]:
        raise SourceLayoutError("CIBER: ficha con corrección de errores que requiere revisión")
    apply = _text(data, "URLPaginaSolicitud", True)
    try:
        address = urlsplit(apply)
    except ValueError as error:
        raise SourceLayoutError("CIBER: enlace de inscripción ilegible") from error
    if (address.scheme != "https" or address.netloc != "intranet.cientifis.com"
            or parse_qs(address.query).get("PRFId") != [ref]):
        raise SourceLayoutError("CIBER: enlace de inscripción inesperado")
    sections = []
    for title, key in (("Perfil del puesto", "Perfil"), ("Funciones a desarrollar", "FuncionesDesarrollar"),
                       ("Titulación requerida", "Titulacion"), ("Experiencia requerida", "ExperienciaRequerida"),
                       ("Otros conocimientos", "OtrosConocimientos")):
        value = _text(data, key)
        if value:
            sections.append({"title": title, "level": 2, "html": _paragraphs(value)})
    facts = "".join(f"<p><strong>{escape(label)}:</strong> {escape(_text(data, key))}</p>"
                    for label, key in (("Centro", "Centro"), ("Provincia", "Provincia"),
                                       ("Tipo de contrato", "TipoContrato"), ("Financiación", "Financiacion"),
                                       ("Jornada completa", "Jornada"), ("Horas semanales", "HorasSemanales"),
                                       ("Salario", "SalarioBrutoAnual")) if _text(data, key))
    sections.append({"title": "Condiciones", "level": 2, "html": facts})
    center, province = _text(data, "Centro"), _text(data, "Provincia", True)
    location = "; ".join(v for v in (center if center != "SIN ESPECIFICAR" else "", province) if v)
    return {"data": data, "opens_on": first, "deadline": last, "apply_url": apply,
            "location": location, "sections": sections}


class CiberSource(Source):
    id = "ciber"
    name = "CIBER (Centro de Investigación Biomédica en Red)"
    homepage = PAGE
    delay = 4.0
    required_sections = ("Perfil del puesto", "Funciones a desarrollar")

    def __init__(self, now: datetime | None = None) -> None:
        self._now = now  # solo para las pruebas
        self._details: dict[str, dict] = {}
        self._rows: dict[str, dict] = {}

    def _listing(self, http: Client, method: str) -> list[dict]:
        total, pages, current, rows = parse_page(http.get(listing_url(method)))
        if current != 1 or pages > MAX_PAGES:
            raise SourceLayoutError("CIBER: primera página inesperada o demasiadas páginas")
        for page in range(2, pages + 1):
            more_total, more_pages, current, more = parse_page(http.get(listing_url(method, page)))
            if (more_total, more_pages, current) != (total, pages, page):
                raise SourceLayoutError("CIBER: el listado cambió durante la paginación")
            rows.extend(more)
        if len({_identity(row)[0] for row in rows}) != total:
            raise SourceLayoutError("CIBER: perfiles repetidos o total incompleto")
        return rows

    def list_offers(self, http: Client) -> list[ListedOffer]:
        self._rows, self._details = {}, {}
        now = self._now or datetime.now(timezone.utc)
        rows = {}
        for method in METHODS:
            for row in self._listing(http, method):
                ref = row["IdPerfil"]
                if ref in rows and rows[ref] != row:
                    raise SourceLayoutError("CIBER: un perfil tiene datos distintos entre listados")
                rows[ref] = row
        offers = []
        for ref, row in rows.items():
            first, last = _period(row)
            if first > today_madrid(now) or deadline_passed(last, None, now):
                continue
            detail = parse_detail(http.get(detail_url(ref)), ref)
            data = detail["data"]
            if (data["IdConvocatoria"], data["CategoriaProfesional"]) != (row["IdConvocatoria"], row["CategoriaProfesional"]):
                raise SourceLayoutError("CIBER: ficha y listado discrepan en convocatoria o categoría")
            if detail["opens_on"] > today_madrid(now) or deadline_passed(detail["deadline"], None, now):
                continue
            self._rows[ref], self._details[ref] = row, detail
            offers.append(ListedOffer(
                ref=ref, title=title(row), company=COMPANY, url=DETAIL + ref,
                apply_url=detail["apply_url"], code=f"{data['IdConvocatoria']}/{ref}",
                category=data["CategoriaProfesional"], contract=data["TipoContrato"],
                kind=KINDS.get(data["TipoContrato"]), positions=row.get("Plazas"),
                opens_on=detail["opens_on"], deadline=detail["deadline"],
            ))
        return offers

    def enrich(self, http: Client) -> dict[str, dict]:
        return {ref: {"department": row["Intranet"]} for ref, row in self._rows.items()}

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        detail = self._details.get(offer.ref) or parse_detail(http.get(detail_url(offer.ref)), offer.ref)
        data = detail["data"]
        return OfferDetail(sections=detail["sections"], location=detail["location"],
                           opens_on=detail["opens_on"], deadline=detail["deadline"],
                           contract=data["TipoContrato"], kind=KINDS.get(data["TipoContrato"]))
