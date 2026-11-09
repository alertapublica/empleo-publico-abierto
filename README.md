# Empleo en Empresas Públicas

Portal independiente y **no oficial** que reúne en un sitio las ofertas de empleo de las empresas públicas, con una web accesible y avisos por RSS y Telegram (y por correo, más adelante).

**Web:** https://alertapublica.es/

Empezó con el Grupo SEPI y ahora incluye otras empresas públicas. La lista completa está en `empleo/sources/__init__.py` y en la página «Organismos» de la web.

## Cómo funciona

```text
Webs oficiales → ingesta cada hora → data/ (JSON) → web estática + RSS + API JSON
                                                   → worker de avisos → Telegram (y correo)
```

- GitHub Actions lee las páginas públicas una vez por hora, de una en una y con pausas para no cargar los servidores.
- Los cambios se guardan como JSON en `data/`, así que el histórico queda en el repositorio.
- La ubicación se guarda tal como la da cada portal. Al publicar, `api/ofertas.json` añade los códigos del INE de comunidad (`ccaa`), provincia y municipio solo cuando el texto no deja dudas: «Sevilla» puede ser la provincia o la capital y se queda en provincia. Los municipios vienen de la [Relación de municipios del INE](https://www.ine.es/daco/daco42/codmun/codmunmapa.htm) a 1 de enero de 2026 (`empleo/municipios.csv`).
- La web se genera desde esos datos y se publica en GitHub Pages. No hay servidor, cuentas ni cookies.
- Si una página oficial cambia de forma, la ingesta de esa fuente se detiene sin tocar sus datos y la ejecución falla.
- ADIF y Renfe son centinelas: hoy no tienen convocatorias abiertas, así que solo se vigila su texto de «no hay ofertas». Cuando desaparece, la ejecución falla a propósito para avisar de que hay que escribir su analizador.

## Datos personales

- La web y el RSS no recogen datos de quien los usa.
- Los avisos por Telegram guardan solo el identificador del chat y los criterios del aviso (en D1, Cloudflare). `/baja` lo borra todo, y también se borra si la persona bloquea el bot. Los avisos por correo, cuando se activen, guardarán la dirección con doble confirmación y baja con un clic.
- De los procesos indefinidos solo se guardan título, fecha y enlace oficial.
- No se copian listas de personas candidatas y se omiten los códigos de candidatura.
- Nunca se automatiza una inscripción.

## Desarrollo

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m unittest          # tests
.venv/bin/python -m empleo.ingest     # lee las webs oficiales y actualiza data/
.venv/bin/python -m empleo.site       # genera la web en _site/
```

Auditoría de accesibilidad, con la web ya generada:

```bash
cd tests/a11y && npm ci && npx playwright install chromium && npm test
```

## Worker de Cloudflare

El cron de GitHub se salta muchas ejecuciones, así que un worker (`worker/`, cuenta `empleo-publico`) lanza cada hora `actualizar.yml` con `workflow_dispatch`. Se despliega solo al fusionar en `main` (`.github/workflows/worker.yml`).

- Secretos del repo: `CLOUDFLARE_API_TOKEN` (token acotado de despliegue), `CLOUDFLARE_ACCOUNT_ID` y `AVISOS_CLAVE` (ver «Avisos»).
- Secreto del worker: `GITHUB_TOKEN`, un token de grano fino solo para este repo con «Actions: read and write» (`cd worker && wrangler secret put GITHUB_TOKEN`).
- Tests: `cd worker && node --test test/index.test.mjs`.

## API

JSON estático en GitHub Pages (`https://alertapublica.es/api/…`), regenerado en cada publicación, más o menos cada hora. Se puede leer desde cualquier web (CORS abierto) sin clave. Hay cuatro ficheros: `ofertas.json`, `procesos.json`, `novedades.json` (últimos 14 días; lo usa el worker de avisos) y `listas.json` (nombre legible de cada clave).

La documentación para quien reutiliza los datos, con cada campo, ejemplos, uso responsable y licencia, está en la página [Datos abiertos](https://alertapublica.es/datos/) del portal. El campo `documentacion` de cada fichero enlaza a ella.

Para quien mantiene el código:

- Todos los ficheros empiezan con `version` (ahora `1`), `licencia`, `documentacion` y `generado`. Dentro de una versión solo se añaden claves: renombrar o quitar una obliga a subir `API_VERSION` (`empleo/site.py`). `test_api_v1_en_castellano` fija el orden de las claves de una oferta.
- La descripción de cada clave vive en `FILE_FIELDS`, `OFFER_FIELDS`, `PROCESS_FIELDS` y `NEWS_FIELDS` (`empleo/site.py`), que generan «Datos abiertos». `test_datos_abiertos_documenta_todas_las_claves` falla si una clave de la API no está descrita ahí.
- Un dato que la fuente no da vale `null`. Los textos van tal como los publica cada organismo; lo que elabora el proyecto son los códigos INE, las áreas y la detección del teletrabajo.

## Avisos por Telegram y correo

El worker `empleo-avisos` (`avisos/`, cuenta `empleo-publico`) guarda las suscripciones en D1 (`empleo-avisos`). Los datos de las ofertas no se copian: al terminar de publicar, `actualizar.yml` le envía las novedades de los últimos 3 días a `/interno/publicado`. El worker guarda las que no conocía, las cruza con los avisos y deja los mensajes en una bandeja de salida. Un cron la vacía cada minuto, por tandas, porque el plan gratuito permite 50 llamadas por ejecución.

Un aviso combina palabras del título (por comienzo de palabra, sin tildes), áreas, «menciona teletrabajo», comunidades y organismos. Tiene que cumplir todos los apartados elegidos, y dentro de cada uno basta con una coincidencia. Las ofertas sin comunidad concreta se incluyen salvo que se desactive. Los comunicados de procesos van en una casilla aparte, junto a los organismos.

Puesta en marcha:

1. Secreto del repo `AVISOS_CLAVE`: una cadena aleatoria larga. Es la misma que el secreto del worker con ese nombre.
2. Secretos del worker (`cd avisos && wrangler secret put …`): `AVISOS_CLAVE`, `TELEGRAM_TOKEN` (de @BotFather) y `TELEGRAM_SECRETO` (otra cadena aleatoria, para el webhook).
3. Variable del repo `TELEGRAM_BOT` con el usuario del bot: la web empieza a mencionarlo.
4. Lanzar el workflow «Workers»: migra D1, despliega y registra el webhook y los comandos del bot.

El correo está hecho pero desactivado (`CORREO_ACTIVO`). Para activarlo hace falta:
- un dominio en la cuenta, con Email Sending;
- el plan Workers Paid, para enviar a cualquier dirección;
- el binding `send_email` llamado `CORREO` y `CORREO_REMITENTE`;
- el formulario de la web con Turnstile (`TURNSTILE_SECRETO`).

Tests: `cd avisos && node --test test/avisos.test.mjs`. Necesitan Node 22.13 o posterior, por `node:sqlite`.

## Añadir un organismo

1. Crea `empleo/sources/<organismo>.py` con una clase que herede de `Source`, o reutiliza una plataforma ya hecha (SuccessFactors, por ejemplo). Si es autonómico, declara su `scope` con el nombre de la comunidad.
2. Implementa `list_offers`, que debe lanzar `SourceLayoutError` si la página cambia.
3. Implementa si procede `fetch_detail`, `enrich` y `list_announcements`.
4. Añádelo a su grupo en `CATALOG` (`empleo/sources/__init__.py`): Grupo SEPI, otras empresas del Estado, empresas públicas autonómicas o fundaciones y centros de investigación. Quítalo de `PLANNED`.

El motor, la web y los feeds no necesitan cambios. La clase `FakeSource` de `tests/test_ingest.py` es un ejemplo mínimo.

### Cómo se reparte lo que publica cada portal

Lo decide la forma en que publica el propio portal, no una clasificación nuestra:

- **Oferta** (`ListedOffer`, portada): algo a lo que una persona de fuera puede presentarse ahora, con ficha y plazo. Incluye bolsas, prácticas y becas.
- **Proceso** (`Announcement`, «Procesos selectivos»): comunicados de un proceso publicado por fases. Solo título, fecha y enlace.
- **No se lee:** ayudas a proyectos, resoluciones con nombres, exámenes, listas de personas y la promoción interna como oferta.

Reglas al escribir una fuente:

- El contrato va con el texto literal de la fuente en `contract`. `kind` solo se rellena si la fuente lo dice sin ambigüedad. No se deduce nada del título.
- Si el portal pega un código interno al título («OE 25/26 - Analista»), la fuente declara `title_code`: el título queda limpio, el código va a `code` y el literal a `source_title`. `ref_code` dice qué `ref` son el código que publica el portal; los ids de URL, hashes y slugs no se enseñan.
- Abierta o cerrada se decide por las fechas (`opens_on`, `deadline`, `deadline_time`), no por la etiqueta de la web.
- Si el portal pide una pausa mayor entre peticiones, se respeta.

## Licencia

- El código, con la [Licencia Pública de la Unión Europea (EUPL) 1.2](LICENSE).
- Los datos que elabora este proyecto (la API, los códigos INE asignados, las áreas y la detección del teletrabajo), con [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/deed.es): se pueden reutilizar citando «Empleo en Empresas Públicas» y enlazando el portal.
- Los textos, documentos y enlaces de cada oferta y comunicado son de su organismo, que es la fuente oficial y la que prevalece.

## Documentación

La carpeta [`hallazgos/`](hallazgos/) recoge el estado de cada fuente y cómo publica sus plazos.
