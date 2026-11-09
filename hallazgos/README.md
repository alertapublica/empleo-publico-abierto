# Hallazgos

Lo aprendido al leer los portales oficiales. Revisado el 2026-11-08.

| Archivo | Contenido |
|---|---|
| [`plazos.md`](plazos.md) | Cómo publica cada portal el plazo, qué trampas tiene y las reglas que seguimos para no mostrar un plazo falso. Fallos pendientes. |
| [`fuentes.md`](fuentes.md) | Estado de cada portal: activo, centinela, siguiente tanda, más adelante o fuera, con el motivo. |

El detalle de cada fuente activa está en el docstring de su módulo (`empleo/sources/<fuente>.py`): qué página se lee, cómo se decide si es oferta y qué límites tiene. Aquí solo va lo que sirve para decidir y lo que no está en el código.

## Cómo se lee un portal nuevo

- Lecturas con `curl` o el cliente del proyecto (`empleo/http.py`), una a una, con 2 s de pausa o la que pida `robots.txt` (`Crawl-delay`). Cada fuente declara la suya en `Source.delay`.
- Unas 12 peticiones por portal como mucho. Sin formularios, sin cuentas y sin automatizar inscripciones.
- No se descargan listas de personas (admitidas, puntuaciones, adjudicaciones). Si se baja una por error, se borra y se anota.
- Si algo no se puede leer desde GitHub Actions, se comprueba con el workflow `sondeo` (`gh workflow run sondeo.yml -f ronda=N`) antes de escribir el analizador.
- TLS: nunca se desactiva la verificación. Si el servidor envía un intermedio equivocado, se añade el correcto en `empleo/certs/` (ver su README).
- Un analizador solo se activa si el título, las fechas y el enlace son fiables, y se prueba con HTML real recortado. Si hoy no hay ninguna oferta abierta, la rama de oferta queda sin ver con datos reales, y se dice.
- Los estudios externos de partida pueden contener errores (plazos de caché, discrepancias que no se reproducen, URL que no llevan a ningún portal): nada se da por bueno sin comprobarlo.
