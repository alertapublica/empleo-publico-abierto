# Empleo en Empresas Públicas

[![Tests](https://github.com/alertapublica/empleo-publico-abierto/actions/workflows/ci.yml/badge.svg)](https://github.com/alertapublica/empleo-publico-abierto/actions/workflows/ci.yml)
[![Actualización](https://github.com/alertapublica/empleo-publico-abierto/actions/workflows/actualizar.yml/badge.svg)](https://github.com/alertapublica/empleo-publico-abierto/actions/workflows/actualizar.yml)
[![Código: EUPL 1.2](https://img.shields.io/badge/código-EUPL%201.2-blue)](LICENSE)
[![Datos: CC BY 4.0](https://img.shields.io/badge/datos-CC%20BY%204.0-lightgrey)](https://creativecommons.org/licenses/by/4.0/deed.es)

Portal independiente y **no oficial** que reúne en un solo sitio las ofertas de empleo de las empresas públicas españolas, con una web accesible, avisos por RSS y Telegram y una API JSON abierta.

**Web: <https://alertapublica.es/>**

Lee las páginas oficiales de 43 organismos: Grupo SEPI, otras empresas del Estado, empresas públicas autonómicas, fundaciones y centros de investigación. La lista completa está en [`empleo/sources/__init__.py`](empleo/sources/__init__.py) y en la página «Organismos» de la web.

## Qué ofrece

- **Ofertas** con ficha y plazo, y **procesos selectivos** con sus comunicados por fases, siempre con enlace a la fuente oficial.
- **Filtros** por texto, área, comunidad, organismo, tipo de contrato y teletrabajo.
- **Avisos** por RSS y por Telegram con criterios propios (palabras, áreas, comunidades, organismos).
- **Datos abiertos**: API JSON sin clave y con CORS abierto, con códigos INE de comunidad, provincia y municipio.
- **Sin cuentas ni cookies**: la web y el RSS no recogen datos de quien los usa.

## Cómo funciona

```text
Webs oficiales → ingesta cada hora → data/ (JSON) → web estática + RSS + API JSON
                                                   → worker de avisos → Telegram (y correo)
```

GitHub Actions lee las páginas públicas una vez por hora, de una en una y con pausas, y guarda los cambios como JSON en `data/` (el histórico queda en git). La web se genera desde esos datos y se publica en GitHub Pages; no hay servidor. Si una página oficial cambia de forma, la ingesta de esa fuente se detiene sin tocar sus datos y la ejecución falla para avisar.

La web del Grupo Tragsa ([`alertapublica/empleo-tragsa`](https://github.com/alertapublica/empleo-tragsa)) se genera con la API de este portal. Al publicar, `actualizar.yml` la manda regenerar si existe el secreto `TOKEN_WEB_TRAGSA`: un token de grano fino con «Actions: lectura y escritura» solo en ese repo. Sin él, se actualiza con su propio cron.

## Desarrollo

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest          # tests
.venv/bin/python -m empleo.ingest     # lee las webs oficiales y actualiza data/
.venv/bin/python -m empleo.site       # genera la web en _site/
```

Necesita Python 3.13. Auditoría de accesibilidad (axe + Chromium), con la web ya generada y Node 22:

```bash
cd tests/a11y && npm ci && npx playwright install chromium && npm test
```

Los workers de Cloudflare tienen sus propios tests: ver [`docs/worker.md`](docs/worker.md) y [`docs/avisos.md`](docs/avisos.md).

## Documentación

| | |
|---|---|
| [`docs/anadir-fuente.md`](docs/anadir-fuente.md) | Cómo añadir un organismo y qué cuenta como oferta o proceso |
| [`docs/api.md`](docs/api.md) | API JSON: ficheros, versionado y reglas para quien mantiene el código |
| [`docs/avisos.md`](docs/avisos.md) | Avisos por Telegram y correo: funcionamiento y puesta en marcha |
| [`docs/worker.md`](docs/worker.md) | Worker de Cloudflare que lanza la ingesta cada hora |
| [`docs/privacidad.md`](docs/privacidad.md) | Qué datos se guardan y cuáles nunca |
| [`hallazgos/`](hallazgos/) | Estado de cada fuente y cómo publica cada portal sus plazos |

Para quien reutiliza los datos, la documentación de cada campo está en [Datos abiertos](https://alertapublica.es/datos/), dentro del portal.

## Contribuir

Las ideas, los fallos y las fuentes nuevas son bienvenidos: mira [`CONTRIBUTING.md`](CONTRIBUTING.md). Para vulnerabilidades, [`SECURITY.md`](SECURITY.md).

## Licencia

- **Código:** [Licencia Pública de la Unión Europea (EUPL) 1.2](LICENSE).
- **Datos elaborados por el proyecto** (la API, los códigos INE asignados, las áreas y la detección del teletrabajo): [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.es). Se pueden reutilizar citando «Empleo en Empresas Públicas» y enlazando el portal.
- **Textos, documentos y enlaces de cada oferta y comunicado:** son de su organismo, que es la fuente oficial y la que prevalece.
