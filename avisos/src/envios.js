// Vacía la bandeja de salida por tandas: el plan gratuito permite 50 llamadas por ejecución,
// contando las de D1, así que cada tanda hace 1 lectura, hasta `limite` envíos y 1 escritura.

import { iso } from "./novedades.js";

const MAX_INTENTOS = 5;

export async function telegram(env, metodo, datos, fetcher = fetch) {
  const respuesta = await fetcher(`https://api.telegram.org/bot${env.TELEGRAM_TOKEN}/${metodo}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(datos),
  });
  const cuerpo = await respuesta.json().catch(() => ({}));
  return { status: respuesta.status, ...cuerpo };
}

export const correoActivo = (env) => env.CORREO_ACTIVO === "si" && Boolean(env.CORREO) && Boolean(env.CORREO_REMITENTE);

export async function enviarCorreo(env, { para, asunto, texto, baja }) {
  const pie = baja ? `\n\n--\nDarte de baja de estos avisos: ${baja}\n` : "";
  await env.CORREO.send({
    from: env.CORREO_REMITENTE,
    to: para,
    subject: asunto,
    text: texto + pie,
    headers: baja ? { "List-Unsubscribe": `<${baja}>`, "List-Unsubscribe-Post": "List-Unsubscribe=One-Click" } : {},
  });
}

export const enlaceBaja = (env, token) => `${env.URL_PUBLICA}/correo/baja?t=${encodeURIComponent(token)}`;

export async function vaciar(env, { ahora = new Date(), fetcher = fetch, limite = 40 } = {}) {
  const db = env.DB;
  const canales = correoActivo(env) ? ["telegram", "correo"] : ["telegram"];
  if (!env.TELEGRAM_TOKEN) canales.splice(canales.indexOf("telegram"), 1);
  if (!canales.length) return { enviados: 0, fallidos: 0 };
  const { results } = await db.prepare(
    `SELECT e.id, e.asunto, e.texto, e.intentos, s.id AS suscriptor, s.canal, s.destino, s.token
     FROM envios e JOIN suscriptores s ON s.id = e.suscriptor
     WHERE e.despues <= ? AND s.canal IN (${canales.map(() => "?").join(", ")})
     ORDER BY e.id LIMIT ?`,
  ).bind(iso(ahora), ...canales, limite).all();

  const sentencias = [];
  const fuera = new Set(); // personas que bloquearon el bot
  let enviados = 0;
  for (const e of results) {
    if (fuera.has(e.suscriptor)) continue;
    let reintentar = null;
    try {
      if (e.canal === "telegram") {
        const r = await telegram(env, "sendMessage", {
          chat_id: e.destino, text: e.texto, parse_mode: "HTML", link_preview_options: { is_disabled: true },
        }, fetcher);
        if (r.ok) enviados++;
        else if (r.status === 403) { // bloqueó el bot o borró la cuenta: se borran sus datos
          fuera.add(e.suscriptor);
          sentencias.push(db.prepare("DELETE FROM suscriptores WHERE id = ?").bind(e.suscriptor));
          continue;
        } else if (r.status === 429) {
          reintentar = (r.parameters?.retry_after || 30) * 1000;
        } else if (r.status >= 400 && r.status < 500) {
          console.log(`Telegram rechazó el envío ${e.id}: ${r.status} ${r.description || ""}`);
        } else reintentar = 60000 * 2 ** e.intentos;
      } else {
        await enviarCorreo(env, { para: e.destino, asunto: e.asunto, texto: e.texto, baja: enlaceBaja(env, e.token) });
        enviados++;
      }
    } catch (error) {
      console.log(`Fallo al enviar ${e.id}: ${error.message}`);
      reintentar = 60000 * 2 ** e.intentos;
    }
    if (reintentar !== null && e.intentos + 1 < MAX_INTENTOS) {
      sentencias.push(db.prepare("UPDATE envios SET intentos = intentos + 1, despues = ? WHERE id = ?")
        .bind(iso(new Date(ahora.getTime() + reintentar)), e.id));
    } else {
      sentencias.push(db.prepare("DELETE FROM envios WHERE id = ?").bind(e.id));
    }
  }
  if (sentencias.length) await db.batch(sentencias);
  return { enviados, fallidos: results.length - enviados };
}
