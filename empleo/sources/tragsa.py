"""Grupo Tragsa (Tragsa y Tragsatec).

Web pública: tablas HTML en SharePoint. Portal de candidatos: PeopleSoft con sesión
de invitado, que además da fecha de publicación, ubicación y familia de puesto.

La ficha repite el plazo con inicio y hora («desde hoy día 23/10/2026 hasta el próximo 09/11/2026
a las 23:59»). A veces no coincide con la columna del listado (58484: 08/11 en el listado, 09/11 en
la ficha): vale la fecha mayor, y la hora solo si es de ese día.

Los puestos fijos no tienen ficha: cada proceso (tasa de reposición) es una página con
comunicados, y la inscripción va en una plataforma externa. Un proceso con plazo de solicitudes
vigente es una oferta, aunque el plazo esté en el cuerpo de un comunicado.
"""
from __future__ import annotations

import re
import warnings
from datetime import date, datetime, timedelta
from urllib.parse import parse_qs, urljoin, urlparse

from bs4 import BeautifulSoup, XMLParsedAsHTMLWarning

from ..dates import clock, latest, spanish_date
from ..http import Client
from ..model import MADRID, Announcement, ListedOffer, OfferDetail, SourceLayoutError, selection_system
from ..sanitize import sanitize
from ..text import slug
from .base import Source

BASE = "https://www.tragsa.es"
UNETE = f"{BASE}/es/equipo-humano/unete-a-nuestro-equipo"
HUB = f"{UNETE}/Paginas/default.aspx"
PORTAL = (
    "https://rrhhcandidato.tragsa.es:8443/psc/portalrh/EMPLOYEE/HRMS/c/"
    "HRS_HRAM_FL.HRS_CG_SEARCH_FL.GBL"
)
PORTAL_MAX_PAGES = 15

LISTINGS = [
    ("temporal", f"{UNETE}/ofertas-empleo-temporal/Paginas/ofertas-especificas.aspx"),
    ("temporal", f"{UNETE}/ofertas-empleo-temporal/Paginas/ofertas-especificas-it.aspx"),
    ("temporal", f"{UNETE}/ofertas-empleo-temporal/Paginas/ofertas-personal-incendios.aspx"),
    ("bolsa", f"{UNETE}/ofertas-empleo-temporal/Paginas/bolsas-empleo.aspx"),
    ("indefinido", f"{UNETE}/ofertas-empleo-indefinido/Paginas/ofertas-especificas.aspx"),
    ("practicas", f"{UNETE}/ofertas-practicas/Paginas/default.aspx"),
]
EMPTY_TEXT = "No se han encontrado resultados"
HEADERS = ["Oferta", "Código oferta", "Empresa", "Nº de puestos", "Tipo", "Fecha límite envío de CV"]
CALL_HEADERS = ["Oferta de empleo", "ID", "Publicación", "Información sobre la fase"]
OPEN_PHASE = "Abierto plazo inscripción"
CALL_SINCE = re.compile(r"Desde:\s*(\d\d/\d\d/\d{4})")
CALL_UNTIL = re.compile(r"Hasta:\s*(\d\d/\d\d/\d{4})\s+(\d\d:\d\d)")
MAIN_SECTIONS = {
    "Proyecto/ Motivo contratación", "Lugar de Trabajo", "Funciones y Tareas",
    "Requisitos Específicos", "Méritos (Valorables)", "Observaciones",
}
SKIP_SECTIONS = {"Título Oferta", "Vacantes Previstas", "Empresa"}
MONTHS = "enero febrero marzo abril mayo junio julio agosto septiembre octubre noviembre diciembre".split()
SPACES = r"[\s​\xa0]+"
CANDIDATE_CODE = re.compile(r"\b[A-Z]{2,4}\d{6,8}\b")
DATE_LINE = re.compile(rf"(\d{{1,2}}) de ({'|'.join(MONTHS)}) de (20\d\d)", re.I)
APPLICATION = re.compile(
    r"plazo\s+de\s+(?:presentaci[óo]n\s+de\s+)?solicitudes[^.]*?hasta\s+las\s+(\d{1,2}[:.]\d{2})\s+(?:horas\s+)?"
    r"del\s+(?:d[íi]a\s+)?(\d{1,2})\s+de\s+([a-záéíóú]+)\s+de\s+(\d{4})", re.I)
APPLICATION_DAYS = re.compile(r"plazo\s+de\s+presentaci[óo]n\s+de\s+solicitudes\s+de\s+(\d{1,3})\s+d[íi]as\s+naturales", re.I)
FICHA_TERM = re.compile(r"desde\s+hoy\s+d[íi]a\s+(\d\d/\d\d/\d{4})\s+hasta\s+el\s+pr[óo]ximo\s+(\d\d/\d\d/\d{4})"
                        r"(?:\s+a\s+las\s+(\d{1,2}[:.]\d{2}))?", re.I)
# Al ampliar el plazo, la ficha cita la publicación original y el portal pone la fecha de la ampliación.
PUBLISHED_BEFORE = re.compile(r"proceso\s+publicado\s+el\s+pasado\s+(\d\d/\d\d/\d{4})", re.I)
PLATFORM = re.compile(r"https?://[\w.-]+\.(?:iformalia\.es|talent-ecosystem\.com)[^\s\"'<>]*", re.I)
ONLY_BLOCKS = re.compile(r"exclusivamente\s+para\s+(?:estos|esos)\s+bloques", re.I)


def _clean(text: str) -> str:
    return re.sub(SPACES, " ", text).strip()


def _date(value: str, layout: str = "%d/%m/%Y") -> str | None:
    try:
        return datetime.strptime(value.strip(), layout).date().isoformat()
    except ValueError:
        return None


def _parse_calls(table, kind: str) -> list[ListedOffer]:
    """Tabla por fases (incendios, bolsas): solo es oferta la fila con la inscripción abierta.

    «Hasta: 20/11/2026 00:00 h» es el final del día 19; la ficha lo dice así: «se cerrará el día
    19/11/2026 (23:59 hora peninsular)».
    """
    headers = [_clean(th.get_text(" ")) for th in table.select("thead th")]
    if headers != CALL_HEADERS:
        raise SourceLayoutError(f"Columnas inesperadas: {headers}")
    offers = []
    for row in table.select("tbody tr"):
        link = row.select_one("a[href*='ficha-oferta-empleo.aspx']")
        if link is None:
            continue
        phase = row.select_one("td.fases")
        lines = [_clean(line) for line in phase.get_text("\n").splitlines() if _clean(line)] if phase else []
        if not lines or lines[0] != OPEN_PHASE:
            continue  # las demás fases solo dan el nombre, sin documentos
        query = parse_qs(urlparse(link["href"]).query)
        text = " ".join(lines)
        since, until = CALL_SINCE.search(text), CALL_UNTIL.search(text)
        if "jobid" not in query or until is None:
            raise SourceLayoutError(f"Fila incompleta: {text}")
        day, hour = datetime.strptime(until.group(1), "%d/%m/%Y").date(), until.group(2)
        if hour == "00:00":
            day, hour = day - timedelta(days=1), "23:59"
        published = row.select_one("td.fecha-publica")
        ref = query["jobid"][0]
        offers.append(
            ListedOffer(
                ref=ref,
                title=_clean(link.get_text(" ")),
                company=None,  # la da la ficha («Empresa»); si no, el grupo
                deadline=day.isoformat(),
                deadline_time=hour,
                opens_on=_date(since.group(1)) if since else None,
                published_on=_date(_clean(published.get_text(" "))[:10]) if published else None,
                kind=kind,
                url=urljoin(BASE, link["href"]),
                apply_url=f"{BASE}/_layouts/15/GrupoTragsa/portal-empleo-acceso.aspx?jobid={ref}",
            )
        )
    return offers


def parse_listing(html: str, kind: str) -> list[ListedOffer]:
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.ofertas-empleo")
    if table is None:
        calls = soup.select_one("table.convocatorias")
        if calls is not None:
            return _parse_calls(calls, kind)
        if EMPTY_TEXT in html:
            return []
        raise SourceLayoutError("No aparece la tabla de ofertas ni el aviso de lista vacía")
    headers = [_clean(th.get_text(" ")) for th in table.select("thead th")]
    if headers != HEADERS:
        raise SourceLayoutError(f"Columnas inesperadas: {headers}")

    offers = []
    for row in table.select("tbody tr"):
        link = row.select_one("a[href*='ficha-oferta-empleo.aspx']")
        if link is None:
            continue  # fila informativa: «Actualmente no hay publicadas ofertas»
        query = parse_qs(urlparse(link["href"]).query)
        cells = [_clean(td.get_text(" ")) for td in row.select("td")]
        if len(cells) < 6 or "jobid" not in query:
            raise SourceLayoutError(f"Fila incompleta: {cells}")
        ref = query["jobid"][0]
        offers.append(
            ListedOffer(
                ref=ref,
                title=cells[0],
                company=cells[2],
                positions=int(cells[3]) if cells[3].isdigit() else None,
                category=cells[4] or None,
                deadline=_date(cells[5]),
                kind=kind,
                url=urljoin(BASE, link["href"]),
                apply_url=f"{BASE}/_layouts/15/GrupoTragsa/portal-empleo-acceso.aspx?jobid={ref}",
            )
        )
    return offers


def parse_detail(html: str) -> OfferDetail | None:
    soup = BeautifulSoup(html, "html.parser")
    groups = soup.select("section.detalles .ps_box-group")
    if not groups:
        return None  # la web vacía la ficha en cuanto termina el plazo
    detail = OfferDetail()
    for group in groups:
        heading = group.select_one(".ps_header-group")
        content = group.select_one(".ps_content-group")
        if heading is None or content is None:
            continue
        title = _clean(heading.get_text(" "))
        if title == "Empresa":
            detail.company = _clean(content.get_text(" ")) or None
        elif title == "Vacantes Previstas":
            count = _clean(content.get_text(" "))
            detail.positions = int(count) if count.isdigit() else None
        if title in SKIP_SECTIONS:
            continue
        body = sanitize(content.decode_contents())
        if not BeautifulSoup(body, "html.parser").get_text(strip=True):
            continue
        detail.sections.append(
            {"title": title, "level": 2 if title in MAIN_SECTIONS else 3, "html": body}
        )
        if title == "Lugar de Trabajo":
            lines = [line.strip() for line in content.get_text("\n").splitlines() if line.strip()]
            detail.location = lines[0] if lines else None
    text = _clean(soup.select_one("section.detalles").get_text(" "))
    parent = re.search(r"proviene de la publicaci[oó]n con ID (\d+)", text)
    detail.parent_ref = parent.group(1) if parent else None
    detail.published_before = min(filter(None, map(_date, PUBLISHED_BEFORE.findall(text))), default=None)
    term = FICHA_TERM.search(text)
    if term:
        detail.opens_on, detail.deadline = _date(term.group(1)), _date(term.group(2))
        detail.deadline_time = clock(term.group(3))
    return detail


def parse_portal_rows(html: str) -> dict[str, dict]:
    with warnings.catch_warnings():  # la paginación llega como XML con HTML dentro: se lee igual
        warnings.simplefilter("ignore", XMLParsedAsHTMLWarning)
        soup = BeautifulSoup(re.sub(r"<!\[CDATA\[|\]\]>", "", html), "html.parser")
    rows = {}
    pattern = re.compile(
        r"ID Puesto (\d+) Ubicación (.*?) Departamento (.*?) Familia Puestos (.*?) "
        r"Fecha Pub\w* (\S+) Fecha Cierre (\S+)"
    )
    for row in soup.find_all(id=re.compile(r"^HRS_AGNT_RSLT_I\$0_row_\d+$")):
        match = pattern.search(_clean(row.get_text(" ", strip=True)))
        if match:
            ref, location, department, family, opened, _closes = match.groups()
            rows[ref] = {
                "location": location or None,
                "department": department or None,
                "family": family or None,
                # Ojo: el portal da las fechas como MM/DD/AAAA y la web como DD/MM/AAAA.
                "published_on": _date(opened, "%m/%d/%Y"),
            }
    return rows


def _hidden_fields(html: str) -> dict[str, str]:
    soup = BeautifulSoup(html, "html.parser")
    return {
        field["name"]: field.get("value", "")
        for field in soup.find_all("input", {"type": "hidden"})
        if field.get("name")
    }


def discover_processes(html: str) -> list[str]:
    """Procesos indefinidos en curso: los cerrados pasan a `tasas-cerradas`."""
    soup = BeautifulSoup(html, "html.parser")
    urls = []
    for link in soup.find_all("a", href=True):
        path = urlparse(link["href"]).path
        if (
            "/ofertas-empleo-indefinido/" in path
            and "tasas-cerradas" not in path
            and not path.endswith(("ofertas-especificas.aspx", "puestos-ofertados.aspx"))
        ):
            url = urljoin(BASE, path)
            if url not in urls:
                urls.append(url)
    return urls


def _canonical(soup: BeautifulSoup, url: str) -> str:
    """La dirección propia del proceso: algunas páginas generales muestran su contenido."""
    link = soup.find("link", rel="canonical")
    path = urlparse(link["href"]).path if link and link.get("href") else ""
    return urljoin(BASE, path) if path else url


def _application_deadline(text: str, published: str) -> tuple[date | None, str | None]:
    """Fin del plazo de solicitudes de un comunicado y su hora: la fecha escrita o, si no la da, los días."""
    days = [(d, clock(hour)) for hour, *day in APPLICATION.findall(text) if (d := spanish_date(*day))]
    if days:
        return latest(days)
    relative = APPLICATION_DAYS.search(text)
    if relative:
        return date.fromordinal(date.fromisoformat(published).toordinal() + int(relative.group(1))), None
    return None, None


def parse_process(html: str, url: str, today: date) -> dict:
    """Comunicados de un proceso y, si sigue abierto, su plazo y dónde inscribirse."""
    soup = BeautifulSoup(html, "html.parser")
    title = soup.find("title")
    process = _clean(title.get_text()).split(" | ")[0] if title else url
    url = _canonical(soup, url)
    paragraphs = soup.find_all("p")
    marks = [p for p in paragraphs if DATE_LINE.fullmatch(_clean(p.get_text(" ")))]
    rows, seen, deadline, hour, opening = [], set(), None, None, None
    for mark in marks:
        index = paragraphs.index(mark)
        text = next(
            (
                _clean(candidate.get_text(" "))
                for candidate in paragraphs[index + 1 : index + 5]
                if _clean(candidate.get_text(" "))
            ),
            "",
        )
        if not text or DATE_LINE.fullmatch(text):
            continue
        day, month, year = DATE_LINE.fullmatch(_clean(mark.get_text(" "))).groups()
        published = f"{year}-{MONTHS.index(month.lower()) + 1:02d}-{int(day):02d}"
        text = CANDIDATE_CODE.sub("[código omitido]", text)
        if (published, text) in seen:
            continue
        seen.add((published, text))
        rows.append((published, text))
        body = []
        for node in mark.find_next_siblings():
            if node in marks:
                break
            body.append(node)
        plain = _clean(" ".join(node.get_text(" ") for node in body).replace("\u200b", ""))
        found, at = _application_deadline(plain, published)
        if found and (deadline is None or found > deadline):
            deadline, hour, opening = found, at, body

    is_open = deadline is not None and deadline >= today
    page = soup.select_one(".texto-superior") or soup
    page_text = page.get_text(" ")
    platform = PLATFORM.search(str(page).replace("\u200b", ""))
    system = selection_system(page_text)
    apply_url = platform.group(0).rstrip(".,;)") if platform else url
    items = [
        Announcement(
            date=published, process=process, title=text, url=url, via="tasa", access="libre",
            contract="indefinido", system=system, state="abierto" if is_open else "curso",
            process_url=url, deadline=deadline.isoformat() if is_open else None,
            deadline_time=hour if is_open else None,
            apply_url=apply_url if is_open else None,
        )
        for published, text in rows
    ]
    parts = [part for part in urlparse(url).path.split("/") if part]
    return {
        "ref": slug(parts[-3] if len(parts) >= 3 else process),
        "process": process,
        "url": url,
        "items": items,
        "open": is_open,
        "deadline": deadline.isoformat() if is_open else None,
        "deadline_time": hour if is_open else None,
        "apply_url": apply_url,
        "partial": is_open and bool(ONLY_BLOCKS.search(" ".join(n.get_text(" ") for n in opening or []))),
        "notice_html": sanitize(CANDIDATE_CODE.sub("[código omitido]", "".join(str(n) for n in opening or []))),
        "published_on": rows[0][0] if rows else None,
    }


def parse_announcements(html: str, url: str) -> list[Announcement]:
    return parse_process(html, url, date.max)["items"]


class TragsaSource(Source):
    id = "tragsa"
    name = "Grupo Tragsa"
    homepage = HUB
    ref_code = re.compile(r"\d+")  # «Código oferta»; los procesos llevan un slug
    # 2: la ficha corrige el plazo del listado (#17). 3: publicación original al ampliar el plazo, y
    # empresa y vacantes de la ficha para las filas del listado por fases.
    detail_version = 3
    enrich_fields = ("published_on", "family")

    def __init__(self, today: date | None = None) -> None:
        self._today = today  # solo para las pruebas
        self._processes: list[dict] = []

    def _read_processes(self, http: Client) -> list[dict]:
        today = self._today or datetime.now(MADRID).date()
        processes: dict[str, dict] = {}
        for url in discover_processes(http.get(HUB)):
            process = parse_process(http.get(url), url, today)
            # Varias direcciones redirigen al mismo proceso.
            if process["items"]:
                processes.setdefault(process["process"], process)
        return list(processes.values())

    def list_offers(self, http: Client) -> list[ListedOffer]:
        offers: dict[str, ListedOffer] = {}
        for kind, url in LISTINGS:
            for offer in parse_listing(http.get(url), kind):
                offers.setdefault(offer.ref, offer)
        self._processes = self._read_processes(http)
        for process in self._processes:
            if process["open"]:
                suffix = ": solo los bloques corregidos" if process["partial"] else ""
                offers[process["ref"]] = ListedOffer(
                    ref=process["ref"], title=process["process"] + suffix, company=self.name,
                    url=process["url"], apply_url=process["apply_url"], kind="indefinido",
                    category="Tasa de reposición", deadline=process["deadline"],
                    deadline_time=process["deadline_time"],
                    published_on=process["published_on"],
                )
        return list(offers.values())

    def fetch_detail(self, http: Client, offer: ListedOffer) -> OfferDetail | None:
        process = next((p for p in self._processes if p["ref"] == offer.ref), None)
        if process is None:
            detail = parse_detail(http.get(offer.url))
            # Si el listado da una fecha posterior a la de la ficha, manda la del listado.
            if detail and detail.deadline and offer.deadline and detail.deadline < offer.deadline:
                detail.deadline = detail.deadline_time = None
            # Empresa y vacantes: las del listado, salvo en la tabla por fases, que no las trae.
            if detail and offer.company:
                detail.company = None
            elif detail:
                detail.company = detail.company or self.name
            if detail and offer.positions is not None:
                detail.positions = None
            return detail
        return OfferDetail(
            sections=[{"title": "Comunicado oficial del plazo", "level": 2, "html": process["notice_html"]}],
            location="Varias comunidades",
        )

    def enrich(self, http: Client) -> dict[str, dict]:
        html = http.get(f"{PORTAL}?FOCUS=Applicant&SiteId=1&Page=HRS_APP_SCHJOB_FL&Action=U")
        rows = parse_portal_rows(html)
        if not rows:  # mantenimiento o cambio de página: que no gaste los intentos de las ofertas
            raise SourceLayoutError("Portal de candidatos: la primera página no trae ofertas")
        fields = _hidden_fields(html)
        total = re.search(r"(\d+)\s+filas", html)
        for _ in range(PORTAL_MAX_PAGES):
            if not fields.get("ICSID") or (total and len(rows) >= int(total.group(1))):
                break
            # Es lo que hace el navegador al bajar por la lista.
            response = http.post(
                PORTAL,
                {**fields, "ICAction": "HRS_AGNT_RSLT_I$hdown$0", "ICAJAX": "1"},
            )
            page = parse_portal_rows(response)
            if not set(page) - set(rows):
                break
            rows.update(page)
            state = re.search(r"ICStateNum[^0-9]{1,30}(\d+)", response)
            if state:
                fields["ICStateNum"] = state.group(1)
        return rows

    def list_announcements(self, http: Client) -> list[Announcement]:
        items = {item.key: item for process in self._processes for item in process["items"]}
        return list(items.values())
