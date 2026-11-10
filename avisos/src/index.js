// Worker de avisos: bot de Telegram, avisos por correo (desactivados mientras CORREO_ACTIVO no sea
// «si») y la ruta interna a la que llama actualizar.yml tras publicar. Los datos de las ofertas siguen en GitHub Pages:
// aquí solo se guardan las suscripciones y lo necesario para no avisar dos veces.

import { COMANDOS, atender } from "./bot.js";
import { alta, baja, confirmar, direccion, pagina, resumenCorreo } from "./correo.js";
import { correoConfigurado, enlaceBaja, enviarUno, telegram, vaciar } from "./envios.js";
import { recibir } from "./novedades.js";

export const CRON_ENVIOS = "* * * * *";
export const CRONS_CORREO = ["0 6 * * *", "0 13 * * *"]; // resumen de la mañana y de la tarde (UTC)

function igual(a, b) { // comparación en tiempo constante
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let distinto = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) distinto |= (x[i] || 0) ^ (y[i] || 0);
  return distinto === 0;
}

const autorizado = (request, clave) => Boolean(clave) && igual(request.headers.get("Authorization") || "", `Bearer ${clave}`);
const json = (datos, status = 200) => Response.json(datos, { status });

export async function configurar(env, fetcher = fetch) {
  const webhook = await telegram(env, "setWebhook", {
    url: `${env.URL_PUBLICA}/telegram`,
    secret_token: env.TELEGRAM_SECRETO,
    allowed_updates: ["message", "callback_query"],
    drop_pending_updates: false,
  }, fetcher);
  const comandos = await telegram(env, "setMyCommands", { commands: COMANDOS, language_code: "" }, fetcher);
  return { webhook: webhook.ok === true, comandos: comandos.ok === true };
}

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const ruta = `${request.method} ${url.pathname}`;
    try {
      if (ruta === "POST /telegram") {
        if (!env.TELEGRAM_TOKEN || !env.TELEGRAM_SECRETO
          || !igual(request.headers.get("X-Telegram-Bot-Api-Secret-Token") || "", env.TELEGRAM_SECRETO)) {
          return new Response("No autorizado", { status: 401 });
        }
        try {
          await atender(env, await request.json());
        } catch (error) {
          console.log(`Error al atender a Telegram: ${error.message}`); // sin datos personales
        }
        return new Response("ok"); // siempre 200: si no, Telegram repite el mismo mensaje
      }
      if (ruta === "POST /interno/publicado") {
        if (!autorizado(request, env.AVISOS_CLAVE)) return json({ error: "No autorizado" }, 401);
        const resultado = await recibir(env, await request.json());
        ctx.waitUntil(vaciar(env, { limite: 25 })); // deja margen: la recepción ya gastó parte de las 50 llamadas
        return json(resultado);
      }
      if (ruta === "POST /interno/configurar") {
        if (!autorizado(request, env.AVISOS_CLAVE)) return json({ error: "No autorizado" }, 401);
        if (!env.TELEGRAM_TOKEN || !env.TELEGRAM_SECRETO) return json({ error: "Faltan TELEGRAM_TOKEN o TELEGRAM_SECRETO" }, 409);
        return json(await configurar(env));
      }
      // Correo de prueba (aunque el correo no esté activo): comprueba el SMTP desde Cloudflare y
      // permite revisar SPF, DKIM y DMARC con herramientas como mail-tester.com.
      if (ruta === "POST /interno/correo-prueba") {
        if (!autorizado(request, env.AVISOS_CLAVE)) return json({ error: "No autorizado" }, 401);
        if (!correoConfigurado(env)) return json({ error: "Faltan SMTP_* o CORREO_REMITENTE" }, 409);
        const para = direccion((await request.json().catch(() => ({}))).para);
        if (!para) return json({ error: "Dirección no válida" }, 400);
        try {
          await enviarUno(env, {
            para,
            asunto: "Prueba del correo de avisos de empleo público",
            texto: "Este es un correo de prueba del servicio de avisos de Empleo en Empresas Públicas.\n\n"
              + "Si lo has recibido, el envío funciona. No hace falta que hagas nada.",
            baja: enlaceBaja(env, "prueba"),
          });
        } catch (error) {
          return json({ error: error.message }, 502);
        }
        return json({ enviado: true });
      }
      if (ruta === "POST /correo/alta") return await alta(env, request);
      if (ruta === "GET /correo/confirmar") return await confirmar(env, url);
      if (url.pathname === "/correo/baja" && ["GET", "POST"].includes(request.method)) return await baja(env, request, url);
      if (ruta === "GET /") {
        return pagina("Avisos de empleo público", '<p>Servicio de avisos del portal <a href="https://alertapublica.es/">Empleo en Empresas Públicas</a>.</p>');
      }
      return new Response("No encontrado", { status: 404 });
    } catch (error) {
      console.log(`Error en ${ruta}: ${error.message}`);
      return json({ error: "Error interno" }, 500);
    }
  },

  async scheduled(evento, env, _ctx) {
    if (CRONS_CORREO.includes(evento.cron)) await resumenCorreo(env);
    await vaciar(env);
  },
};
