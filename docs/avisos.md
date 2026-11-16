# Avisos por Telegram y correo

El worker `empleo-avisos` (`avisos/`, cuenta `empleo-publico` de Cloudflare) guarda las suscripciones en D1 (`empleo-avisos`). Los datos de las ofertas no se copian: al terminar de publicar, `actualizar.yml` le envía las novedades de los últimos 3 días a `/interno/publicado`. El worker guarda las que no conocía marcadas como pendientes, las cruza con los avisos y deja los mensajes en una bandeja de salida; la marca se quita con los últimos mensajes, así un reparto que falla se reintenta en la recepción siguiente. Un cron vacía la bandeja cada minuto, por tandas, porque el plan gratuito permite 50 llamadas por ejecución. Cada tanda reserva sus envíos (los aplaza 10 minutos) antes de mandarlos: dos tandas que coinciden no mandan el mismo mensaje. Otros tres crons preparan los resúmenes por correo (ver abajo).

## Criterios de un aviso

Un aviso combina palabras del título (por comienzo de palabra, sin tildes), áreas, «menciona teletrabajo», comunidades y organismos. Tiene que cumplir todos los apartados elegidos, y dentro de cada uno basta con una coincidencia. Las ofertas sin comunidad concreta se incluyen salvo que se desactive. Los comunicados de procesos van en una casilla aparte, junto a los organismos; se filtran por las palabras (nombre del proceso y título) y por la comunidad del proceso (`ccaa` de `novedades.json`), con la misma casilla para los que no la tienen, que hoy son la mayoría: solo Puertos y ENRESA dan la ubicación de sus procesos.

## Puesta en marcha

1. Secreto del repo `AVISOS_CLAVE`: una cadena aleatoria larga. Es la misma que el secreto del worker con ese nombre.
2. Secretos del worker (`cd avisos && wrangler secret put …`): `AVISOS_CLAVE`, `TELEGRAM_TOKEN` (de @BotFather) y `TELEGRAM_SECRETO` (otra cadena aleatoria, para el webhook).
3. Variable del repo `TELEGRAM_BOT` con el usuario del bot: la web empieza a mencionarlo.
4. Lanzar el workflow «Workers»: migra D1, despliega y registra el webhook y los comandos del bot.

El worker se publica en `https://avisos.alertapublica.es` (dominio propio declarado en `avisos/wrangler.jsonc`), así que el token del secreto `CLOUDFLARE_API_TOKEN` necesita también «Zone › Workers Routes › Edit» en la zona `alertapublica.es`. Si cambia esa dirección, hay que cambiarla también en `URL_PUBLICA`, en `AVISOS_URL` (`empleo/site.py`) y en los workflows `actualizar.yml` y `worker.yml`.

## Enlaces con el organismo ya elegido

Para enlazar los avisos desde otra web (por ejemplo, la del Grupo Tragsa, `alertapublica/empleo-tragsa`), con el id de `organismos` de `api/listas.json`:

- `https://alertapublica.es/avisos/?organismo=tragsa` deja marcada su casilla, y abierto su grupo, en el formulario de correo (`listas.js`).
- `https://t.me/<bot>?start=tragsa` empieza un aviso con ese organismo ya elegido y se salta ese paso. Un `/start` sin organismo o con uno que no existe muestra la ayuda.

## Correo

Sale por el SMTP del buzón `avisos@alertapublica.es` de Piensa (`smtp.buzondecorreo.com`, TLS en el 465), con un cliente propio sobre `cloudflare:sockets` (`avisos/src/smtp.js`). No hace falta el plan Workers Paid. Cada tanda abre una sola sesión y envía como mucho `CORREO_POR_TANDA` correos; el resto espera al minuto siguiente. Un destinatario rechazado no se reintenta; un fallo temporal o de conexión, sí.

Los avisos por correo son resúmenes, no alertas: de lunes a viernes, dos al día, a las 6:00 y a las 18:30 UTC (7:00 y 19:30 en invierno; 8:00 y 20:30 en verano, hora de Madrid), y sábados y domingos, uno, a las 19:30 UTC (20:30 en invierno; 21:30 en verano). El de la tarde sale después de la última lectura cada 30 minutos (18:37) y el del fin de semana, después de la de las 20:07 (ver [worker](worker.md)); casi todas las novedades llegan de 9:00 a 19:00 entre semana. Cada uno reúne lo guardado desde el anterior: el de la tarde lleva lo del día; el de la mañana, lo leído desde entonces (las lecturas de la noche y de las 6:00), y el del sábado, lo del viernes por la noche y el sábado. Las horas van en UTC y se corren una hora en verano; no importa, porque siguen quedando después de esas lecturas. Una novedad espera, como mucho, hasta el siguiente resumen. Telegram avisa en cada ingesta. Si cambias las horas, cámbialas a la vez en `crons` de `avisos/wrangler.jsonc` y en `CRONS_CORREO` de `avisos/src/index.js`.

Está desactivado mientras `CORREO_ACTIVO` no sea `si`. Hace falta:

- las variables `SMTP_*`, `CORREO_REMITENTE` y `CORREO_NOMBRE` (en `wrangler.jsonc`) y el secreto `SMTP_CLAVE` (`wrangler secret put SMTP_CLAVE`);
- el formulario de la web con Turnstile: el secreto `TURNSTILE_SECRETO` en el worker y la variable del repo `CORREO_SITEKEY` con la clave pública (sin ella, la web no ofrece el correo). El formulario envía casillas con las claves de `api/listas.json` a `/correo/alta`; la CSP se abre solo en `/avisos/`, para Turnstile y para el worker;
- en el DNS: SPF (`include:_spf.buzondecorreo.com`), DKIM (selector `1794215374238`, el que firma Piensa) y DMARC.

### Correo de prueba

Funciona aunque el correo esté desactivado: sirve para comprobar el SMTP desde Cloudflare y revisar SPF, DKIM y DMARC (por ejemplo, con mail-tester.com).

```bash
curl -X POST -H "Authorization: Bearer $AVISOS_CLAVE" -d '{"para": "direccion@ejemplo.es"}' \
  https://avisos.alertapublica.es/interno/correo-prueba
```

Responde `{"enviado": true}` o el fallo, sin el texto del servidor (p. ej. `SMTP 535 en AUTH`).

### Rebotes

Los rebotes y las respuestas llegan al buzón `avisos@`. Se revisan a mano; para borrar una dirección que ya no existe:

```bash
cd avisos && npx wrangler d1 execute empleo-avisos --remote \
  --command "DELETE FROM suscriptores WHERE canal = 'correo' AND destino = 'direccion@ejemplo.es'"
```

## Tests

```bash
cd avisos && node --test test/avisos.test.mjs
```

Necesitan Node 22.13 o posterior, por `node:sqlite`.
