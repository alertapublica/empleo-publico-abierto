# Plan: lectura de fuentes en paralelo

Borrador local (2026-11-15). Base: informes de Codex `sondeo/codex/respuesta33.md` (concurrencia),
`respuesta34.md` (clasificación de fuentes) y `respuesta37.md` (revisión tras pasar el relay al Worker, #76),
revisados.

## Por qué

- La ingesta lee las 71 fuentes en serie con un solo `Client`. Las lecturas completas del 14 y 15/11 tardan
  15–25 min, y las de las 11:07 y 12:07 del 15/11 agotaron `timeout-minutes: 30` sin una línea en el log (salida
  con búfer). Es lentitud acumulada, no un cuelgue. Casi todo es espera (pausas de 2–10 s y red), así que
  basta con hilos.
- El repo es público: no se trata de ahorrar minutos sino de frescura, margen frente al límite del job y
  crecimiento (universidades).
- Estimación de Codex (pausas, no medición): estado normal ≈11 min en serie → ≈2–3 min con 4–6 hilos.
  En una relectura masiva manda el grupo más pesado (Tragsa, ≈7 min con 193 fichas), que no se divide.

## Regla innegociable

Dentro de cada portal (servidor real) se mantiene el ritmo actual (`delay`, Crawl-delay) y nunca hay dos
peticiones a la vez. Las fuentes que comparten servidor van en el mismo grupo, en serie.

## PR 1 — Registro por fuente (en serie, sin cambiar nada más)

- `INICIO`/`FIN` por fuente con id, duración (`time.monotonic()`) y resultado; `FIN` también si falla
  (`finally`). `flush=True` y `PYTHONUNBUFFERED=1` en el paso de `actualizar.yml`.
- Opcional: tiempos por fase (listado, fichas, enriquecimiento, anuncios) y nº de peticiones/reintentos.
- Objetivo: saber dónde se acumula la lentitud (qué fuente y qué fase) antes de fijar topes.
- De paso: `http.py:118` no espera tras el último intento fallido (hoy duerme 45 s antes de rendirse; una URL
  caída cuesta 180 s de timeouts + 65 s de esperas). No cambia ningún resultado.
- `timeout-minutes: 30` se queda como está (decisión del 15/11): lo resuelve el paralelismo.

## PR 2 — Preparar sin cambiar el comportamiento (sigue con 1 hilo)

- Campo nuevo en `Source` (`empleo/sources/base.py`): `concurrency_group: str | None = None`; clave
  efectiva `source.concurrency_group or source.id`. (`group` ya es la categoría editorial: no se toca.)
- Grupos iniciales (de `respuesta34.md`, actualizados con `respuesta37.md`): 59 grupos para 71 fuentes.
  - seguro: `junta-andalucia` (andalucia, ifapa);
  - preventivos, misma plataforma sin confirmar servidor (coste bajo, se mantienen hasta comprobarlo):
    SuccessFactors (correos, navantia, fgc, bsm, renfe), Fundanet (idibell, fisabio, idival, imas12),
    `isdefe`+`canal`, `enaire`+`aena`, `idis`+`galiciasur`, USC (ciqus, cimus).
  - El Worker de Cloudflare (`relay/`) no agrupa: cada petición tiene su propio estado (tarro, redirecciones)
    y admite simultáneas. Se agrupa por el servidor de destino, así que SEPI, EFE, Tragsa y `furioja` van
    cada una en su grupo.
- Un `Client` por fuente: cookies, sesión y `_relay_cookies` (ya separadas por origen desde #76) propios; el
  `Client` sigue sin ser compartible entre hilos. Dentro de un grupo se conserva la pausa al pasar de una
  fuente a la siguiente (máximo de sus `delay`).
- `tragsa.py:219`: sustituir `warnings.catch_warnings()` (estado global, no seguro con hilos) por un
  filtro fijo a nivel de módulo.
- Precalentar las cachés de `regions` (`_municipalities()` etc.) antes de arrancar.
- Adaptar `tests/test_http.py:33` (hoy exige orden secuencial): comprobar pausa por fuente y orden dentro
  del grupo, no entre grupos.

## PR 3 — Pool de hilos por grupo

- `ThreadPoolExecutor` con N tareas de grupo (variable de entorno, por defecto 4; con 1, como hoy).
  Cada tarea recorre su grupo en orden de catálogo; una fuente, un único hilo (no se paralelizan fichas).
- Errores: capturados por fuente dentro del grupo, sigue con la siguiente; código de salida 1 si alguna
  falla (como hoy).
- Salida: líneas `INICIO`/`FIN` inmediatas; resumen final en orden de catálogo. Sin `redirect_stdout`.
- Plazo cooperativo (no procesos). Contrato:
  - el `Client` recibe una hora límite, `min(inicio de la fuente + tope por fuente, límite global)`;
  - la comprueba antes de cada petición y de cada espera o reintento; recorta las esperas y el `timeout`
    HTTP al tiempo que quede;
  - al pasarla lanza una excepción propia, distinta de los errores reintentables (`http.py:114`), que no se
    traga en los `except Exception` de fichas y enriquecimiento (`ingest.py:176`, `:248`);
  - el procesado local (PDF, análisis) que ya ha empezado termina: es rápido y no se corta.
  Límite: una respuesta que llega a goteo puede pasar algo del plazo (el `timeout` es por operación de socket);
  lo acota el límite del job. Topes iniciales: 10 min por fuente y presupuesto global de ~25 min (las
  pendientes cuentan como fallo), a revisar con lo medido en PR 1 (Tragsa ya gasta ≈7 min solo en pausas).
- Guardado: si el plazo salta en anuncios, ofertas y eventos ya están guardados y anuncios no, igual que hoy
  con cualquier error en esa fase (ver «Descartado o aplazado»).
- `now` común, el de `main`, para `run_source`. Los adaptadores que calculan su propia hora (`fundanet.py:130`,
  `tragsa.py:375`) se dejan como están: no cambia respecto a hoy.
- Tests en CI: exclusión dentro del grupo, pausas, una fuente que agota su plazo no frena a las demás,
  código de salida.

## Descartado o aplazado

- Procesos supervisados para un tope duro (propuesta de Codex): demasiado para el caso. Casi todo el
  tiempo es pausa o espera de red, que el plazo cooperativo acota; lo que se escape lo para el límite del job
  y, con PR 1, el log dice dónde fue.
- Guardado transaccional de offers/events/announcements: hoy ya no es atómico entre los tres. Solo hace
  falta si el plazo corta fuentes a medias con frecuencia.
- Pausa entre saltos de redirección (urllib y el Worker los siguen solos; el Worker, hasta 5 saltos de 25 s
  cada uno): detalle menor.

## Pendiente de comprobar con red (más adelante)

Servidor real de los grupos preventivos (DNS, redirecciones, cabeceras); destino de UACloud; alias de
EMACSA. Al dar de alta una fuente nueva, declarar su grupo si comparte servidor.
