"""Sondeo puntual de las páginas de empleo de las empresas públicas.

Una petición por página y con pausa, para no cargar los servidores.
Guarda el HTML tal cual llega y un resumen JSON. No inicia sesión ni envía formularios.
Se lanza desde GitHub Actions (workflow «Sondeo»); en local solo se prueba con datos falsos.
"""
from __future__ import annotations

import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from .http import HEADERS, relay

DELAY = 3.0
MAX_BYTES = 3_000_000
TIMEOUT = 40

# (organismo, URL). Solo páginas públicas de lectura; ninguna es de inicio de sesión ni de inscripción.
TARGETS = [
    ("sepi", "https://www.sepi.es/es/empleo-publico"),
    ("sepi", "https://www.sepi.es/es/empleo-publico/convocatoria-de-proceso-de-seleccion-para-la-cobertura-de-15-puestos-de-personal"),
    ("sepi", "https://www.sepi.es/es/empleo-publico/convocatoria-de-proceso-de-seleccion-para-la-cobertura-de-dos-puestos-de-personal"),
    ("mercasa", "https://www.mercasa.es/que-es-mercasa/unete-a-mercasa/"),
    ("cofivacasa", "https://cofivacasa.com/empleo-publico/"),
    ("zarzuela", "https://www.hipodromodelazarzuela.es/informacion-corporativa"),
    ("cetarsa", "https://www.cetarsa.es/empleo"),
    ("cetarsa", "https://www.cetarsa.es/empleo-2026/"),
    ("sepides", "https://www.sepides.es/empleo"),
    ("hunosa", "https://www.hunosa.es/empleo-publico/"),
    ("saeca", "https://www.saeca.es/ofertas-de-empleo-saeca"),
    ("mayasa", "https://mayasa.es/trabaja-con-nosotros/"),
    ("enusa", "https://www.enusa.es/trabaja-con-nosotros/"),
    ("enusa", "https://engljobsite.pn.cegid.cloud/jobsite_g/espanol/generico_login.jsp?zjslanguser=es"),
    ("ensa", "https://ensa.epreselec.com/Ofertas/Ofertas.aspx"),
    ("correos", "https://empleo.correos.com/"),
    ("navantia", "https://www.navantia.es/es/trabaja-con-nosotros/"),
    ("navantia", "https://empleo.navantia.es/"),
    ("rtve", "https://www.convocatorias.rtve.es/"),
    ("efe", "https://www.efe.com/"),
]

# Segunda ronda, a partir de lo que dejó ver la primera.
TARGETS_2 = [
    ("sepi", "https://www.sepi.es/es/empleo-publico"),
    ("correos", "https://empleo.correos.com/go/Ofertas-publicadas/4331401/"),
    ("correos", "https://empleo.correos.com/go/Perfiles-Corporativos/9700001/"),
    ("navantia", "https://empleo.navantia.es/go/Ofertas-de-empleo/9308355/"),
    ("rtve", "https://convocatorias.rtve.es/main.43ebed5dd4280d67.js"),
]
TARGETS_3 = [
    ("rtve", "https://convocatorias.rtve.es/assets/conf/deployment-properties.json"),
]
TARGETS_4 = [
    ("rtve", "https://convocatorias.rtve.es/PLACOPUBLIC/api/convocatoria/getConvocatorias"),
]
# Empresas públicas fuera del Grupo SEPI: ¿responden desde Actions y qué HTML dan?
TARGETS_5 = [
    ("enaire", "https://empleo.enaire.es/empleo/PFSrv?accion=inicio&SEDE=0"),
    ("aena", "https://empleo.aena.es/empleo/PFSrv?accion=inicio&SEDE=0"),
    ("puertos", "https://www.puertos.es/institucional/recursos-humanos/ofertas-de-empleo?offer_type=108"),
    ("puertos", "https://www.puertos.es/institucional/recursos-humanos/ofertas-de-empleo?offer_type=107"),
    ("adif", "https://www.adif.es/empleo/oferta-empleo-publico/plazo-solicitud-abierto"),
    ("adif", "https://www.adif.es/empleo/oferta-empleo-publico/proceso-resolucion"),
    ("adif", "https://www.adif.es/w/pni26-03-tecnico"),
    ("renfe", "https://empleo.renfe.com/search/"),
    ("renfe", "https://empleo.renfe.com/CONV_EXT_PROCESO/content/INDEX_CONV_EXT_PROCESO/?locale=es_ES"),
    ("cesce", "https://www.cesce.es/es/corporativo/trabaja-en-cesce"),
    ("sasemar", "https://www.salvamentomaritimo.es/conocenos/nuestra-empresa/trabaja-con-nosotros"),
    ("paradores", "https://paradoresempleo.epreselec.com/Ofertas/Ofertas.aspx"),
]
ROUNDS = {"1": TARGETS, "2": TARGETS_2, "3": TARGETS_3, "4": TARGETS_4, "5": TARGETS_5}

# Pistas de la tecnología con la que se publica: sirven para decidir qué parser hace falta.
HINTS = {
    "successfactors": r"successfactors|hana\.ondemand\.com|rmkcdn|/go/",
    "cegid": r"cegid",
    "epreselec": r"epreselec|e-preselec",
    "taleo": r"taleo",
    "workday": r"myworkdayjobs|workday",
    "oracle": r"oraclecloud|peoplesoft",
    "wordpress": r"wp-content|wp-includes",
    "drupal": r"drupal",
    "sharepoint": r"sharepoint|_layouts/15",
    "aspnet": r"__viewstate",
}
LOADING = re.compile(r"cargando|loading", re.I)
OFFER_WORDS = re.compile(
    r"oferta|convocatoria|proceso selectivo|tasa de reposici|oposici|bolsa de empleo|plazo", re.I
)


def analyse(html: str) -> dict:
    """Resume lo que importa de una página sin guardar su texto."""
    title = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
    lowered = html.lower()
    links = re.findall(r"<a\s[^>]*href=[\"']([^\"'#][^\"']*)", html, re.I)
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", html, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    return {
        "titulo": re.sub(r"\s+", " ", title.group(1)).strip()[:150] if title else None,
        "texto_visible": len(re.sub(r"\s+", " ", text).strip()),
        "enlaces": len(links),
        "enlaces_pdf": sum(1 for link in links if link.lower().split("?")[0].endswith(".pdf")),
        "scripts": len(re.findall(r"<script\b", lowered)),
        "tablas": lowered.count("<table"),
        "listas": lowered.count("<li"),
        "marca_de_carga": bool(LOADING.search(text)),
        "palabras_de_oferta": len(OFFER_WORDS.findall(text)),
        "pistas": [name for name, pattern in HINTS.items() if re.search(pattern, lowered)],
    }


def fetch(url: str) -> dict:
    """Una sola petición. Devuelve estado, cabeceras útiles y cuerpo (o el error)."""
    target, signed = relay(url)
    request = urllib.request.Request(target, headers={**HEADERS, **signed})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            # Por el relay, geturl() sería la del relay, no la de destino tras las redirecciones.
            status, headers, final = response.status, response.headers, url if signed else response.geturl()
            body = response.read(MAX_BYTES)
    except urllib.error.HTTPError as error:
        status, headers, final, body = error.code, error.headers, url, error.read(MAX_BYTES)
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as error:
        return {"estado": None, "error": f"{type(error).__name__}: {error}", "cuerpo": ""}
    if headers.get("Content-Encoding") == "gzip":
        try:
            body = gzip.decompress(body)
        except OSError:
            pass
    return {
        "estado": status,
        "via": "relay" if signed else "directa",
        "url_final": final,
        "tipo": headers.get("Content-Type"),
        "servidor": headers.get("Server"),
        "cuerpo": body.decode("utf-8", "replace"),
    }


def run(targets, out: Path, getter=fetch, sleep=time.sleep) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    (out / "html").mkdir(exist_ok=True)
    report = {"agente": HEADERS["User-Agent"], "paginas": []}
    for number, (organism, url) in enumerate(targets, 1):
        if number > 1:
            sleep(DELAY)
        entry = {"organismo": organism, "url": url}
        result = getter(url)
        body = result.pop("cuerpo")
        entry.update(result)
        if result.get("estado"):
            name = f"{number:02d}-{organism}.html"
            (out / "html" / name).write_text(body, encoding="utf-8")
            entry["fichero"] = name
            entry["bytes"] = len(body.encode("utf-8"))
            entry["analisis"] = analyse(body)
        report["paginas"].append(entry)
    (out / "sondeo.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return report


def summary(report: dict) -> str:
    rows = ["| Organismo | Estado | Texto | PDF | Scripts | Carga | Pistas | Página |", "|---|---|---:|---:|---:|---|---|---|"]
    for page in report["paginas"]:
        analysis = page.get("analisis") or {}
        rows.append(
            f"| {page['organismo']} | {page.get('estado') or page.get('error', '?')} "
            f"| {analysis.get('texto_visible', '')} | {analysis.get('enlaces_pdf', '')} "
            f"| {analysis.get('scripts', '')} | {'sí' if analysis.get('marca_de_carga') else ''} "
            f"| {', '.join(analysis.get('pistas', []))} | {page['url']} |"
        )
    return "\n".join(rows)


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "sondeo")
    report = run(ROUNDS[sys.argv[2] if len(sys.argv) > 2 else "1"], out)
    print(summary(report))


if __name__ == "__main__":
    main()
