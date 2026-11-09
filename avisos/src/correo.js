// Avisos por correo: alta con doble confirmación, baja con un clic y resumen diario.
// Desactivado mientras CORREO_ACTIVO no sea «si». Para activarlo hacen falta un dominio en la cuenta
// de Cloudflare (Email Sending), el plan Workers Paid para enviar a cualquier dirección, el binding
// CORREO, CORREO_REMITENTE y el secreto TURNSTILE_SECRETO del formulario.

import { MAX_AVISOS, describir, limpiar } from "./criterios.js";
import { correoActivo, enlaceBaja, enviarCorreo } from "./envios.js";
import { escapar, iso, leerListas, repartir } from "./novedades.js";

const CORREO = /^[^\s@<>"]{1,64}@[^\s@<>"]+\.[^\s@<>"]{2,}$/;
const CADUCA_HORAS = 48;

export function pagina(titulo, cuerpo, status = 200) {
  return new Response(
    `<!doctype html><html lang="es"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">`
    + `<title>${escapar(titulo)}</title><body style="font:1.2rem/1.5 system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem">`
    + `<h1>${escapar(titulo)}</h1>${cuerpo}</body></html>`,
    { status, headers: { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store", "X-Robots-Tag": "noindex" } },
  );
}

async function turnstile(env, token, ip, fetcher) {
  const datos = new FormData();
  datos.append("secret", env.TURNSTILE_SECRETO);
  datos.append("response", token || "");
  if (ip) datos.append("remoteip", ip);
  const r = await fetcher("https://challenges.cloudflare.com/turnstile/v0/siteverify", { method: "POST", body: datos });
  return (await r.json()).success === true;
}

// Formulario de la web (POST, sin JavaScript propio): correo, criterios (JSON) y token de Turnstile.
// El aviso queda pendiente hasta que se confirma desde el correo; nada se activa sin confirmar.
export async function alta(env, request, { fetcher = fetch, ahora = new Date() } = {}) {
  if (!correoActivo(env)) return pagina("Aún no disponible", "<p>Los avisos por correo todavía no están activos. Mientras tanto puedes usar el bot de Telegram o los avisos por RSS.</p>", 503);
  const form = await request.formData();
  const correo = String(form.get("correo") || "").trim().toLowerCase();
  if (!CORREO.test(correo)) return pagina("Revisa el correo", "<p>La dirección no parece válida. Vuelve atrás y corrígela.</p>", 400);
  if (!(await turnstile(env, form.get("cf-turnstile-response"), request.headers.get("CF-Connecting-IP"), fetcher))) {
    return pagina("No se pudo comprobar", "<p>No hemos podido comprobar que no eres un programa automático. Vuelve atrás e inténtalo de nuevo.</p>", 400);
  }
  const listas = await leerListas(env.DB);
  let criterios;
  try { criterios = limpiar(JSON.parse(String(form.get("criterios") || "{}")), listas); } catch { criterios = null; }
  if (!listas || !criterios) return pagina("Revisa el aviso", "<p>El aviso no es válido. Vuelve atrás y revísalo.</p>", 400);

  const db = env.DB;
  await db.prepare(
    "INSERT OR IGNORE INTO suscriptores (canal, destino, estado, token, creado) VALUES ('correo', ?, 'pendiente', ?, ?)",
  ).bind(correo, crypto.randomUUID(), iso(ahora)).run();
  const s = await db.prepare("SELECT id, token FROM suscriptores WHERE canal = 'correo' AND destino = ?").bind(correo).first();
  const confirmar = crypto.randomUUID();
  // Solo se guarda el último aviso pendiente: quien no controla el buzón no puede activar nada.
  await db.prepare("UPDATE suscriptores SET borrador = ? WHERE id = ?")
    .bind(JSON.stringify({ confirmar, criterios, hasta: iso(new Date(ahora.getTime() + CADUCA_HORAS * 3600000)) }), s.id).run();
  await enviarCorreo(env, {
    para: correo,
    asunto: "Confirma tu aviso de empleo público",
    texto: `Alguien (seguramente tú) ha pedido avisos por correo con estos criterios:\n\n${describir(criterios, listas)}\n\n`
      + `Para activarlo, abre este enlace en las próximas ${CADUCA_HORAS} horas:\n${env.URL_PUBLICA}/correo/confirmar?t=${confirmar}\n\n`
      + "Si no lo has pedido tú, no hagas nada: sin confirmar no se envía ningún aviso.",
  });
  return pagina("Revisa tu correo", `<p>Te hemos enviado un enlace a <strong>${escapar(correo)}</strong> para confirmar el aviso. Caduca en ${CADUCA_HORAS} horas.</p>`);
}

export async function confirmar(env, url, { ahora = new Date() } = {}) {
  const token = url.searchParams.get("t") || "";
  const db = env.DB;
  const s = token && await db.prepare(
    "SELECT id, borrador FROM suscriptores WHERE canal = 'correo' AND json_extract(borrador, '$.confirmar') = ?",
  ).bind(token).first();
  const pendiente = s ? JSON.parse(s.borrador) : null;
  if (!pendiente || pendiente.hasta < iso(ahora)) {
    return pagina("Enlace no válido", "<p>El enlace ha caducado o ya se usó. Puedes pedir el aviso de nuevo desde el portal.</p>", 404);
  }
  const n = await db.prepare("SELECT COUNT(*) AS n FROM avisos WHERE suscriptor = ?").bind(s.id).first("n");
  if (n >= MAX_AVISOS) return pagina("Demasiados avisos", `<p>Ya tienes ${MAX_AVISOS} avisos, el máximo.</p>`, 409);
  await db.batch([
    db.prepare("INSERT INTO avisos (suscriptor, criterios, creado) VALUES (?, ?, ?)").bind(s.id, JSON.stringify(pendiente.criterios), iso(ahora)),
    db.prepare("UPDATE suscriptores SET estado = 'activo', borrador = NULL WHERE id = ?").bind(s.id),
  ]);
  return pagina("Aviso activado", "<p>Recibirás un correo al día como mucho, solo cuando haya novedades. Cada correo trae un enlace para darte de baja.</p>");
}

// GET muestra un botón (los antivirus abren los enlaces y no deben dar de baja a nadie);
// POST borra, y es también la baja con un clic de List-Unsubscribe-Post.
export async function baja(env, request, url) {
  const token = url.searchParams.get("t") || "";
  if (request.method === "GET") {
    return pagina("Darte de baja", `<form method="post" action="?t=${encodeURIComponent(token)}"><p>Se borrarán tu correo y todos tus avisos.</p><button type="submit" style="font:inherit;padding:.5rem 1rem">Darme de baja</button></form>`);
  }
  if (token) await env.DB.prepare("DELETE FROM suscriptores WHERE canal = 'correo' AND token = ?").bind(token).run();
  return pagina("Baja hecha", "<p>Hemos borrado tu correo y tus avisos.</p>");
}

// Cron diario: un resumen por persona con las novedades guardadas desde el último resumen. El cursor
// es el rowid (orden de llegada), no la fecha de la novedad, para no perder las que llegan tarde.
export async function resumenDiario(env, ahora = new Date()) {
  if (!correoActivo(env)) return 0;
  const db = env.DB;
  const desde = await db.prepare("SELECT valor FROM estado WHERE clave = 'correo_desde'").first("valor");
  const ultimo = (await db.prepare("SELECT MAX(rowid) AS n FROM novedades").first("n")) || 0;
  let encolados = 0;
  if (desde !== null) {
    const { results } = await db.prepare("SELECT datos FROM novedades WHERE rowid > ? AND rowid <= ?")
      .bind(Number(desde), ultimo).all();
    if (results.length) encolados = await repartir(db, "correo", results.map((r) => JSON.parse(r.datos)), ahora);
  }
  await db.batch([
    db.prepare("INSERT OR REPLACE INTO estado (clave, valor) VALUES ('correo_desde', ?)").bind(String(ultimo)),
    // Altas sin confirmar caducadas: se borran.
    db.prepare("DELETE FROM suscriptores WHERE canal = 'correo' AND estado = 'pendiente' AND json_extract(borrador, '$.hasta') < ?").bind(iso(ahora)),
  ]);
  return encolados;
}

export { enlaceBaja };
