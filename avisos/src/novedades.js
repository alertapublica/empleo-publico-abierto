// Recibe api/novedades.json y api/listas.json al terminar cada publicación, guarda las novedades
// nuevas y deja en la bandeja de salida un mensaje por persona con lo que encaja en sus avisos.

import { coincide } from "./criterios.js";

const RECIENTES_DIAS = 3; // una novedad más antigua que esto ya no se avisa (p. ej. tras vaciar D1)
const GUARDAR_DIAS = 30;
const LOTE = 50; // sentencias por db.batch
export const MAX_MENSAJE = 3800; // Telegram admite 4096 caracteres

export const iso = (fecha) => fecha.toISOString().slice(0, 19) + "+00:00";
const hace = (ahora, dias) => iso(new Date(ahora.getTime() - dias * 86400000));

export async function lotes(db, sentencias) {
  for (let i = 0; i < sentencias.length; i += LOTE) await db.batch(sentencias.slice(i, i + LOTE));
}

export async function leerListas(db) {
  const fila = await db.prepare("SELECT valor FROM estado WHERE clave = 'listas'").first();
  return fila ? JSON.parse(fila.valor) : null;
}

export async function recibir(env, carga, ahora = new Date()) {
  const db = env.DB;
  if (!Array.isArray(carga?.novedades) || !carga?.listas?.organismos) throw new Error("Carga no válida");
  const novedades = carga.novedades.filter((n) => n && typeof n.id === "string" && typeof n.fecha === "string");

  const vacia = !(await db.prepare("SELECT 1 FROM novedades LIMIT 1").first());
  const desde = novedades.reduce((min, n) => (n.fecha < min ? n.fecha : min), "9999");
  const { results } = await db.prepare("SELECT id FROM novedades WHERE fecha >= ?").bind(desde).all();
  const vistas = new Set(results.map((r) => r.id));
  const nuevas = novedades.filter((n) => !vistas.has(n.id));

  await lotes(db, [
    db.prepare("INSERT OR REPLACE INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(carga.listas)),
    db.prepare("DELETE FROM novedades WHERE fecha < ?").bind(hace(ahora, GUARDAR_DIAS)),
    ...nuevas.map((n) =>
      db.prepare("INSERT OR IGNORE INTO novedades (id, fecha, datos) VALUES (?, ?, ?)").bind(n.id, n.fecha, JSON.stringify(n))),
  ]);

  // La primera vez todo es «nuevo»: se guarda sin avisar para no inundar a nadie.
  const recientes = vacia ? [] : nuevas.filter((n) => n.fecha >= hace(ahora, RECIENTES_DIAS));
  const mensajes = recientes.length ? await repartir(db, "telegram", recientes, ahora) : 0;
  return { recibidas: novedades.length, nuevas: nuevas.length, avisadas: recientes.length, mensajes, primera: vacia };
}

// Cruza las novedades con los avisos activos del canal y encola un mensaje (o varios trozos) por persona.
export async function repartir(db, canal, novedades, ahora = new Date()) {
  const { results } = await db.prepare(
    `SELECT a.suscriptor, a.criterios FROM avisos a JOIN suscriptores s ON s.id = a.suscriptor
     WHERE s.canal = ? AND s.estado = 'activo' ORDER BY a.suscriptor, a.id`,
  ).bind(canal).all();
  const porPersona = new Map();
  for (const { suscriptor, criterios } of results) {
    const c = JSON.parse(criterios);
    const elegidas = porPersona.get(suscriptor) || new Map();
    for (const n of novedades) if (coincide(c, n)) elegidas.set(n.id, n);
    porPersona.set(suscriptor, elegidas);
  }
  const sentencias = [];
  for (const [suscriptor, elegidas] of porPersona) {
    if (!elegidas.size) continue;
    const trozos = canal === "telegram" ? mensajeTelegram([...elegidas.values()]) : [textoCorreo([...elegidas.values()])];
    const asunto = canal === "correo" ? asuntoCorreo(elegidas.size) : null;
    for (const texto of trozos) {
      sentencias.push(db.prepare("INSERT INTO envios (suscriptor, asunto, texto, despues) VALUES (?, ?, ?, ?)")
        .bind(suscriptor, asunto, texto, iso(ahora)));
    }
  }
  await lotes(db, sentencias);
  return sentencias.length;
}

export const escapar = (t) => String(t ?? "").replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");

const ordenar = (novedades) => [...novedades].sort((a, b) => (a.fecha < b.fecha ? 1 : -1));

// Mensajes en HTML de Telegram, partidos para no pasar del límite.
export function mensajeTelegram(novedades) {
  const ofertas = ordenar(novedades.filter((n) => n.tipo === "oferta"));
  const comunicados = ordenar(novedades.filter((n) => n.tipo === "comunicado"));
  const bloques = [];
  if (ofertas.length) {
    bloques.push(`<b>${ofertas.length === 1 ? "Nueva oferta" : `${ofertas.length} ofertas nuevas`} para tus avisos</b>`);
    for (const o of ofertas) {
      const prefijo = o.evento === "republished" ? "Republicada: " : "";
      const tele = typeof o.teletrabajo === "string" ? "\nMenciona teletrabajo" : "";
      bloques.push(`• ${prefijo}<a href="${escapar(o.url)}">${escapar(o.titulo)}</a>${o.detalle ? `\n${escapar(o.detalle)}` : ""}${tele}`);
    }
  }
  if (comunicados.length) {
    bloques.push(`<b>Comunicados de procesos selectivos</b>`);
    for (const c of comunicados) bloques.push(`• ${escapar(c.proceso)}: <a href="${escapar(c.url)}">${escapar(c.titulo)}</a>`);
  }
  bloques.push("Gestiona tus avisos con /avisos.");
  const trozos = [];
  let actual = "";
  for (const bloque of bloques) {
    const b = bloque.length > MAX_MENSAJE ? bloque.slice(0, MAX_MENSAJE) : bloque;
    if (actual && actual.length + b.length + 2 > MAX_MENSAJE) {
      trozos.push(actual);
      actual = "";
    }
    actual = actual ? `${actual}\n\n${b}` : b;
  }
  if (actual) trozos.push(actual);
  return trozos;
}

export const asuntoCorreo = (n) => (n === 1 ? "1 novedad para tus avisos de empleo público" : `${n} novedades para tus avisos de empleo público`);

// Texto plano del resumen por correo (el enlace de baja lo añade el envío).
export function textoCorreo(novedades) {
  const ofertas = ordenar(novedades.filter((n) => n.tipo === "oferta"));
  const comunicados = ordenar(novedades.filter((n) => n.tipo === "comunicado"));
  const lineas = [];
  if (ofertas.length) {
    lineas.push("OFERTAS NUEVAS", "");
    for (const o of ofertas) {
      lineas.push(`- ${o.evento === "republished" ? "Republicada: " : ""}${o.titulo}`);
      if (o.detalle) lineas.push(`  ${o.detalle}`);
      if (typeof o.teletrabajo === "string") lineas.push("  Menciona teletrabajo");
      lineas.push(`  ${o.url}`, "");
    }
  }
  if (comunicados.length) {
    lineas.push("COMUNICADOS DE PROCESOS SELECTIVOS", "");
    for (const c of comunicados) lineas.push(`- ${c.proceso}: ${c.titulo}`, `  ${c.url}`, "");
  }
  return lineas.join("\n");
}
