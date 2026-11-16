# API

JSON estático en GitHub Pages (`https://alertapublica.es/api/…`), regenerado en cada publicación, es decir, tras cada lectura: cada 30 minutos entre semana de 6:00 a 19:00 y menos el resto (horario en [worker](worker.md); la web lo publica desde `SCHEDULE`, `empleo/site.py`). Se puede leer desde cualquier web (CORS abierto) sin clave.

Hay cuatro ficheros:

| Fichero | Contenido |
|---|---|
| `ofertas.json` | Ofertas, con códigos INE de comunidad (`ccaa`), provincia y municipio, y país (ISO 3166-1). Las becas (`tipo_contrato` `beca`) van en todos los ficheros; en la web, solo en Becas (`site.is_grant`). Un puesto fuera de España lleva `comunidad` «Extranjero» (`regions.ABROAD`), `ccaa` `null` y su `pais` |
| `procesos.json` | Comunicados de procesos selectivos |
| `novedades.json` | Novedades de los últimos 14 días (lo usa el worker de avisos). Cada oferta lleva `tipo_contrato` y `extranjero` (bool): los avisos solo mandan becas y puestos en el extranjero a quien los pide |
| `listas.json` | Nombre legible de cada clave |

La documentación para quien reutiliza los datos, con cada campo, ejemplos, horario, uso responsable y licencia, está en la página [Datos abiertos](https://alertapublica.es/datos/) del portal. El campo `documentacion` de cada fichero enlaza a ella. Los registros y el tamaño de cada fichero no se apuntan aquí: la página los mide en cada publicación.

## Ubicación y códigos INE

La ubicación se guarda tal como la da cada portal. Al publicar, `api/ofertas.json` añade los códigos del INE de comunidad, provincia y municipio solo cuando el texto no deja dudas: «Sevilla» puede ser la provincia o la capital y se queda en provincia. Los municipios vienen de la [Relación de municipios del INE](https://www.ine.es/dyngs/INEbase/es/operacion.htm?c=Estadistica_C&cid=1254736177031&menu=ultiDatos&idp=1254734710990) a 1 de enero de 2026, a través de [territorios-es](https://github.com/alertapublica/territorios-es) (`INE_FECHA`, `empleo/site.py`; un test la compara con la de territorios-es). `listas.json` trae en `municipios` el nombre de los que usa alguna oferta, no los más de 8000 de la relación.

Los procesos llevan la ubicación que dé su fuente (`Announcement.location`: el centro en ENRESA, la autoridad portuaria en Puertos) y, al publicar, `api/procesos.json` añade comunidad y provincia con el mismo criterio (`process_codes`). Sin municipio: un centro o una autoridad portuaria no fijan una localidad (el puerto de Bilbao está casi todo en Santurtzi).

## Para quien mantiene el código

- Todos los ficheros empiezan con `version` (ahora `1`), `licencia`, `documentacion` y `generado`. Dentro de una versión solo se añaden claves: renombrar o quitar una obliga a subir `API_VERSION` (`empleo/site.py`). `test_api_v1_en_castellano` fija el orden de las claves de una oferta.
- La descripción de cada clave vive en `FILE_FIELDS`, `OFFER_FIELDS`, `PROCESS_FIELDS`, `NEWS_FIELDS` y `LIST_FIELDS` (`empleo/site.py`), que generan «Datos abiertos». `test_datos_abiertos_documenta_todas_las_claves` falla si una clave de la API (también las de cada comunicado y las de cada elemento de las listas) no está descrita ahí, y `test_api_usa_las_claves_de_listas` si un valor codificado (organismo, área, tipo de contrato, códigos INE…) no está en `listas.json`.
- `teletrabajo`, `teletrabajo_estado` y `teletrabajo_detalle` salen de leer el texto de la ficha con reglas fijas (`empleo/teletrabajo.py`): son orientativos. `no_menciona` no significa que no haya teletrabajo; `sin` solo se da cuando la ficha lo dice. Desde el 2026-11-14 los apartados que solo enlazan documentos no cuentan para decidir si la ficha tiene texto, así que algunas ofertas pasaron de `false` a `null`.
- Un dato que la fuente no da vale `null`. Los textos van tal como los publica cada organismo, salvo en `novedades.json` y en el RSS, que pasan a minúsculas los títulos en mayúsculas (`humane_caps`) porque los usan los avisos; lo que elabora el proyecto son los códigos INE, las áreas, los perfiles de las ofertas de investigación, la detección del teletrabajo y las fechas de cierre calculadas: si una oferta trae `plazo_regla`, `plazo_fin` lo ha calculado este portal con esa regla y el calendario oficial del organismo (hoy, solo la Universidade da Coruña).
- `ofertas.json` guarda también todas las cerradas, así que solo crece. No compensa partirlo todavía; si pasa de 2 MB (`API_SPLIT_BYTES`), `python -m empleo.site` deja un aviso en el resumen de la ejecución de Actions y toca añadir un fichero solo con las abiertas (un fichero nuevo no obliga a cambiar de versión).
- En el RSS, la fecha de cada entrada de oferta (`pubDate`) es la de detección o la del cambio, como `fecha` en `novedades.json`; la de publicación en la fuente, si consta, va en el texto de la entrada («Publicada el…»). La ficha muestra las dos.
- El `id` de un proceso sale de su organismo y su nombre (`process_id`); los comunicados de `novedades.json` lo llevan en `proceso_id`, y es también el de su RSS (`feeds/proceso-{id}.xml`, solo para procesos en marcha).
- Un comunicado sin fecha guarda `date: ""`, nunca la de detección: la API da `fecha: null` y `detectado`. La ingesta le añade `position` (su lugar en la última lectura) para ordenarlo. Todo comunicado que ya estaba en la primera lectura del organismo, con fecha o sin ella, lleva `baseline` (no es novedad: queda fuera de `novedades.json`, del RSS y de los avisos). El orden está en `notice_order` (`empleo/site.py`). El `id` de las novedades y el `guid` del RSS (`announcement_id`, `empleo/feeds.py`) llevan organismo, proceso, `date` y el título entero: no cambiar la fecha ni el título guardados de un comunicado ya avisado.
