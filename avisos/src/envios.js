// Vacía la bandeja de salida por tandas: el plan gratuito permite 50 llamadas por ejecución,
// contando las de D1, así que cada tanda hace 1 lectura, hasta `limite` envíos y 1 escritura.

import { iso } from "./novedades.js";
import { abrirSesion, componer } from "./smtp.js";

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

// Correo por el SMTP del buzón de Piensa. «Configurado» basta para la ruta de prueba; «activo» abre
// las altas y el resumen diario.
export const correoConfigurado = (env) =>
  Boolean(env.SMTP_SERVIDOR && env.SMTP_USUARIO && env.SMTP_CLAVE && env.CORREO_REMITENTE);
export const correoActivo = (env) => env.CORREO_ACTIVO === "si" && correoConfigurado(env);

// CONECTAR_SMTP solo existe en los tests (un servidor SMTP de mentira).
export async function sesionCorreo(env) {
  const connect = env.CONECTAR_SMTP || (await import("cloudflare:sockets")).connect;
  return abrirSesion({
    servidor: env.SMTP_SERVIDOR, puerto: env.SMTP_PUERTO || 465, usuario: env.SMTP_USUARIO, clave: env.SMTP_CLAVE,
    nombre: env.CORREO_REMITENTE.split("@").pop(),
  }, connect);
}

export async function enviarCorreo(env, sesion, { para, asunto, texto, baja }) {
  const pie = baja ? `\n\n--\nDarte de baja de estos avisos: ${baja}\n` : "";
  await sesion.enviar(env.CORREO_REMITENTE, para, componer({
    de: env.CORREO_REMITENTE, nombre: env.CORREO_NOMBRE, para, asunto, texto: texto + pie, baja,
  }));
}

// Un correo suelto (confirmación de alta, prueba): abre la sesión, lo envía y la cierra.
export async function enviarUno(env, mensaje) {
  const sesion = await sesionCorreo(env);
  try {
    await enviarCorreo(env, sesion, mensaje);
  } finally {
    await sesion.cerrar();
  }
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
  // Correo: una sola sesión SMTP por tanda y un tope de correos (el límite de envío del buzón).
  const maxCorreos = Number(env.CORREO_POR_TANDA) || 20;
  let sesion = null;
  let correoParado = false; // conexión caída o tope alcanzado: el resto, en la tanda siguiente
  let correos = 0;
  let enviados = 0;
  let aplazados = 0;
  try {
    for (const e of results) {
      if (fuera.has(e.suscriptor)) continue;
      if (e.canal === "correo" && (correoParado || correos >= maxCorreos)) { // sin gastar intento
        aplazados++;
        continue;
      }
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
          correos++;
          sesion ||= await sesionCorreo(env);
          await enviarCorreo(env, sesion, { para: e.destino, asunto: e.asunto, texto: e.texto, baja: enlaceBaja(env, e.token) });
          enviados++;
        }
      } catch (error) {
        console.log(`Fallo al enviar ${e.id}: ${error.message}`); // ErrorSmtp no lleva la dirección
        // Destinatario rechazado: no se reintenta (los rebotes posteriores llegan al buzón).
        reintentar = error.definitivo ? null : 60000 * 2 ** e.intentos;
        if (e.canal === "correo" && (!sesion || sesion.rota)) correoParado = true;
      }
      if (reintentar !== null && e.intentos + 1 < MAX_INTENTOS) {
        sentencias.push(db.prepare("UPDATE envios SET intentos = intentos + 1, despues = ? WHERE id = ?")
          .bind(iso(new Date(ahora.getTime() + reintentar)), e.id));
      } else {
        sentencias.push(db.prepare("DELETE FROM envios WHERE id = ?").bind(e.id));
      }
    }
  } finally {
    if (sesion) await sesion.cerrar();
  }
  if (sentencias.length) await db.batch(sentencias);
  return { enviados, fallidos: results.length - enviados - aplazados, aplazados };
}
