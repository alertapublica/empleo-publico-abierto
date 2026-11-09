# Avisos por Telegram y correo

El worker `empleo-avisos` (`avisos/`, cuenta `empleo-publico` de Cloudflare) guarda las suscripciones en D1 (`empleo-avisos`). Los datos de las ofertas no se copian: al terminar de publicar, `actualizar.yml` le envía las novedades de los últimos 3 días a `/interno/publicado`. El worker guarda las que no conocía, las cruza con los avisos y deja los mensajes en una bandeja de salida. Un cron la vacía cada minuto, por tandas, porque el plan gratuito permite 50 llamadas por ejecución.

## Criterios de un aviso

Un aviso combina palabras del título (por comienzo de palabra, sin tildes), áreas, «menciona teletrabajo», comunidades y organismos. Tiene que cumplir todos los apartados elegidos, y dentro de cada uno basta con una coincidencia. Las ofertas sin comunidad concreta se incluyen salvo que se desactive. Los comunicados de procesos van en una casilla aparte, junto a los organismos.

## Puesta en marcha

1. Secreto del repo `AVISOS_CLAVE`: una cadena aleatoria larga. Es la misma que el secreto del worker con ese nombre.
2. Secretos del worker (`cd avisos && wrangler secret put …`): `AVISOS_CLAVE`, `TELEGRAM_TOKEN` (de @BotFather) y `TELEGRAM_SECRETO` (otra cadena aleatoria, para el webhook).
3. Variable del repo `TELEGRAM_BOT` con el usuario del bot: la web empieza a mencionarlo.
4. Lanzar el workflow «Workers»: migra D1, despliega y registra el webhook y los comandos del bot.

## Correo

Está hecho pero desactivado (`CORREO_ACTIVO`). Para activarlo hace falta:

- un dominio en la cuenta, con Email Sending;
- el plan Workers Paid, para enviar a cualquier dirección;
- el binding `send_email` llamado `CORREO` y `CORREO_REMITENTE`;
- el formulario de la web con Turnstile (`TURNSTILE_SECRETO`).

## Tests

```bash
cd avisos && node --test test/avisos.test.mjs
```

Necesitan Node 22.13 o posterior, por `node:sqlite`.
