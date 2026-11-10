# API

JSON estático en GitHub Pages (`https://alertapublica.es/api/…`), regenerado en cada publicación, hasta cada 30 minutos entre semana por la mañana (ver [worker](worker.md)). Se puede leer desde cualquier web (CORS abierto) sin clave.

Hay cuatro ficheros:

| Fichero | Contenido |
|---|---|
| `ofertas.json` | Ofertas, con códigos INE de comunidad (`ccaa`), provincia y municipio |
| `procesos.json` | Comunicados de procesos selectivos |
| `novedades.json` | Novedades de los últimos 14 días (lo usa el worker de avisos) |
| `listas.json` | Nombre legible de cada clave |

La documentación para quien reutiliza los datos, con cada campo, ejemplos, uso responsable y licencia, está en la página [Datos abiertos](https://alertapublica.es/datos/) del portal. El campo `documentacion` de cada fichero enlaza a ella.

## Ubicación y códigos INE

La ubicación se guarda tal como la da cada portal. Al publicar, `api/ofertas.json` añade los códigos del INE de comunidad, provincia y municipio solo cuando el texto no deja dudas: «Sevilla» puede ser la provincia o la capital y se queda en provincia. Los municipios vienen de la [Relación de municipios del INE](https://www.ine.es/daco/daco42/codmun/codmunmapa.htm) a 1 de enero de 2026, a través de [territorios-es](https://github.com/alertapublica/territorios-es).

## Para quien mantiene el código

- Todos los ficheros empiezan con `version` (ahora `1`), `licencia`, `documentacion` y `generado`. Dentro de una versión solo se añaden claves: renombrar o quitar una obliga a subir `API_VERSION` (`empleo/site.py`). `test_api_v1_en_castellano` fija el orden de las claves de una oferta.
- La descripción de cada clave vive en `FILE_FIELDS`, `OFFER_FIELDS`, `PROCESS_FIELDS` y `NEWS_FIELDS` (`empleo/site.py`), que generan «Datos abiertos». `test_datos_abiertos_documenta_todas_las_claves` falla si una clave de la API no está descrita ahí.
- Un dato que la fuente no da vale `null`. Los textos van tal como los publica cada organismo; lo que elabora el proyecto son los códigos INE, las áreas y la detección del teletrabajo.
