# CIBER: procedencia de los fixtures

Lecturas reales del 2026-11-15, TLS verificado. URL, hora UTC, HTTP y SHA-256 de cada descarga
original en `sondeo/codex/sondeo-31/peticiones.jsonl` (local, fuera de git).

- `ciber-abiertas.jsonp`: `getPerfilesPaginado`, 09:22:35 UTC, HTTP 200.
- `ciber-reposicion-correcta.jsonp`: `getPerfilesReposicionPaginado`, 09:23:21 UTC, HTTP 200.
- `ciber-estabilizacion.jsonp`: `getPerfilesEstabilizacionPaginado`, 09:23:06 UTC, HTTP 200, vacío real.
- `ciber-perfil-<id>.jsonp`: `getPerfil?callback=empleo&PerfilId=<id>`, HTTP 200.
  Originales del mismo nombre en `sondeo/codex/sondeo-31/`, salvo 3913, que procede de `ciber-perfil-3913-2.jsonp`
  (09:28:50 UTC; la primera lectura agotó el tiempo).

Los listados se conservan completos. De las fichas se han retirado enlaces a listados de personas,
banderas de visibilidad y campos internos no utilizados. El texto de los perfiles se conserva;
solo cambia el formato del JSON. No se descargaron listas de candidaturas ni resoluciones personales.

La prueba de paginación de más de una página usa filas derivadas de estos datos: es una simulación,
no una captura de «Abiertas». La consulta real sin filtro de estado sí anunció 18 páginas y 268 perfiles.
