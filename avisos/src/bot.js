// Bot de Telegram: crear, ver y borrar avisos con una conversación guiada.
// Pasos de /nuevo: palabras clave → áreas (→ ¿solo con teletrabajo?) → comunidades (→ ¿sin comunidad concreta?) → organismos
// (→ ¿comunicados?) → resumen y guardar. Cada paso se puede saltar. «/start <organismo>» (enlace t.me/<bot>?start=tragsa)
// hace lo mismo con el organismo ya elegido, sin su paso.

import {
  MAX_AVISOS, MAX_PALABRAS, describir, limpiar, normalizar, reconocerComunidades, reconocerOrganismos,
} from "./criterios.js";
import { telegram } from "./envios.js";
import { escapar, iso, leerListas } from "./novedades.js";

export const COMANDOS = [
  { command: "nuevo", description: "Crear un aviso" },
  { command: "avisos", description: "Ver y borrar tus avisos" },
  { command: "baja", description: "Borrar todos tus avisos y tus datos" },
  { command: "ayuda", description: "Cómo funciona" },
  { command: "privacidad", description: "Qué datos se guardan" },
];

const AYUDA = `Este bot te avisa de las ofertas nuevas de empleo en empresas públicas que publica el portal no oficial «Empleo en Empresas Públicas».

/nuevo crea un aviso. Puedes combinar:
• palabras clave del título (por ejemplo «analista»): basta con el comienzo de la palabra, así «ingenier» encuentra Ingeniero/a e Ingeniera;
• áreas profesionales, y si quieres solo las ofertas que mencionan el teletrabajo;
• comunidades autónomas;
• organismos (por ejemplo Grupo Tragsa), y si quieres también los comunicados de sus procesos selectivos.

La oferta tiene que cumplir todo lo que elijas: «analista» + Galicia avisa solo de las ofertas de analista en Galicia. Dentro de cada apartado basta con una coincidencia (Galicia o Asturias).

Las palabras se buscan en el título tal como lo publica cada empresa: las ofertas en inglés o en catalán solo coinciden con palabras en ese idioma.

/avisos muestra tus avisos y te deja borrarlos. /baja lo borra todo.
Puedes tener hasta ${MAX_AVISOS} avisos.`;

const PRIVACIDAD = `Qué se guarda: el identificador de este chat y los criterios de tus avisos. Nada más: ni tu nombre, ni tu usuario, ni tus mensajes.

Para qué: solo para enviarte los avisos que pides. No se cede a nadie.

Base jurídica: tu consentimiento, que das al guardar un aviso (art. 6.1.a del RGPD). Puedes retirarlo cuando quieras.

Cuánto tiempo: hasta que lo borres. /baja borra tus avisos y el identificador del chat al momento. Si bloqueas el bot, se borran en el siguiente envío.

Dónde: en Cloudflare, Inc., que presta el servicio y puede tratar los datos fuera del Espacio Económico Europeo, con las garantías del Marco de Privacidad de Datos UE-EE. UU. Los mensajes pasan además por Telegram, según su propia política de privacidad.

Responsable: Voceiro - JJAA (legal@alertapublica.es). Escribe a ese correo para ejercer tus derechos (acceso, rectificación, supresión, oposición, limitación o portabilidad). Si no quedan atendidos, puedes reclamar ante la Agencia Española de Protección de Datos (aepd.es).

Más información: https://alertapublica.es/acerca/#bot-telegram`;

const boton = (text, callback_data) => ({ text, callback_data });
const teclado = (filas) => ({ inline_keyboard: filas });
const CANCELAR = [boton("Cancelar", "cancelar")];

async function suscriptor(db, chat) {
  return db.prepare("SELECT * FROM suscriptores WHERE canal = 'telegram' AND destino = ?").bind(String(chat)).first();
}

async function crearSuscriptor(db, chat, ahora) {
  await db.prepare(
    "INSERT OR IGNORE INTO suscriptores (canal, destino, estado, token, creado) VALUES ('telegram', ?, 'activo', ?, ?)",
  ).bind(String(chat), crypto.randomUUID(), iso(ahora)).run();
  return suscriptor(db, chat);
}

async function guardarBorrador(db, id, borrador) {
  await db.prepare("UPDATE suscriptores SET borrador = ? WHERE id = ?")
    .bind(borrador ? JSON.stringify(borrador) : null, id).run();
}

// Quita el borrador; si la persona no tiene avisos, no se guarda nada de ella.
async function olvidarSiVacio(db, s) {
  const avisos = await db.prepare("SELECT COUNT(*) AS n FROM avisos WHERE suscriptor = ?").bind(s.id).first("n");
  if (avisos) await guardarBorrador(db, s.id, null);
  else await db.prepare("DELETE FROM suscriptores WHERE id = ?").bind(s.id).run();
}

function pregunta(paso, criterios, listas) {
  const total = criterios.organismos ? 3 : 4; // con /start <organismo> no se pregunta por los organismos
  switch (paso) {
    case "palabras":
      return {
        text: `Paso 1 de ${total}. Escribe palabras clave del título separadas por comas (por ejemplo: analista, ingenier), o sáltalo.`,
        reply_markup: teclado([[boton("Sin palabras clave", "saltar")], CANCELAR]),
      };
    case "areas": {
      const elegidas = new Set(criterios.areas || []);
      const botones = listas.areas.map((a) => boton(`${elegidas.has(a.id) ? "✓ " : ""}${a.nombre}`, `area:${a.id}`));
      const filas = [];
      for (let i = 0; i < botones.length; i += 2) filas.push(botones.slice(i, i + 2));
      filas.push([boton(elegidas.size ? "Listo" : "Todas las áreas", "saltar")], CANCELAR);
      return {
        text: `Paso 2 de ${total}. Elige una o varias áreas profesionales y pulsa «Listo», o «Todas las áreas». El área es una clasificación orientativa del portal, no de la empresa.`,
        reply_markup: teclado(filas),
      };
    }
    case "teletrabajo":
      return {
        text: "¿Quieres solo las ofertas que mencionan el teletrabajo o el trabajo a distancia? Lo busco en el texto de la oferta: si solo enlaza a las bases en PDF no puedo saberlo, y esa oferta no te llegará.",
        reply_markup: teclado([[boton("Sí, solo esas", "si"), boton("No, todas", "no")], CANCELAR]),
      };
    case "comunidades":
      return {
        text: `Paso 3 de ${total}. Escribe comunidades autónomas separadas por comas (por ejemplo: Galicia, Asturias), o elige toda España.`,
        reply_markup: teclado([[boton("Toda España", "saltar")], CANCELAR]),
      };
    case "sin_ccaa":
      return {
        text: "Algunas ofertas y procesos no dicen la comunidad (sin ubicación, varias comunidades o ámbito nacional). ¿Quieres recibirlos también?",
        reply_markup: teclado([[boton("Sí, también", "si"), boton("No", "no")], CANCELAR]),
      };
    case "organismos":
      return {
        text: "Paso 4 de 4. Escribe organismos o empresas separados por comas (por ejemplo: Tragsa, Correos), o elige todos. La lista completa está en la página «Organismos» del portal.",
        reply_markup: teclado([[boton("Todos los organismos", "saltar")], CANCELAR]),
      };
    case "comunicados":
      return {
        text: "¿Quieres también los comunicados de sus procesos selectivos (bases, listas, notas, fases)?",
        reply_markup: teclado([[boton("Sí", "si"), boton("No, solo ofertas", "no")], CANCELAR]),
      };
    default: // resumen
      return {
        text: `Tu aviso: ${escapar(describir(criterios, listas))}\n\n¿Lo guardo?`,
        reply_markup: teclado([[boton("Guardar", "guardar"), boton("Cancelar", "cancelar")]]),
      };
  }
}

function siguiente(paso, c) {
  switch (paso) {
    case "palabras": return "areas";
    case "areas": return "teletrabajo";
    case "teletrabajo": return "comunidades";
    case "comunidades": return c.ccaa?.length ? "sin_ccaa" : siguiente("sin_ccaa", c);
    case "sin_ccaa": return c.organismos ? "comunicados" : "organismos"; // ya elegidos con /start <organismo>
    case "organismos": return c.organismos?.length ? "comunicados" : "resumen";
    default: return "resumen";
  }
}

function explicar(r, que) {
  const partes = [];
  for (const d of r.dudas) partes.push(`«${escapar(d.termino)}» puede ser: ${escapar(d.opciones.join("; "))}.`);
  for (const f of r.fallos) partes.push(`No encuentro ${que} «${escapar(f)}».`);
  return `${partes.join("\n")}\nEscríbelo de nuevo con más detalle.`;
}

export async function atender(env, update, { fetcher = fetch, ahora = new Date() } = {}) {
  const db = env.DB;
  const enviar = (chat, text, extra = {}) =>
    telegram(env, "sendMessage", { chat_id: chat, text, parse_mode: "HTML", ...extra }, fetcher);

  const consulta = update.callback_query;
  const mensaje = update.message;
  const chat = consulta?.message?.chat || mensaje?.chat;
  if (!chat || chat.type !== "private") return; // solo chats privados
  if (consulta) await telegram(env, "answerCallbackQuery", { callback_query_id: consulta.id }, fetcher);

  const listas = await leerListas(db);
  if (!listas) return enviar(chat.id, "El bot aún se está preparando. Prueba dentro de una hora.");

  let s = await suscriptor(db, chat.id);
  const texto = (mensaje?.text || "").trim();
  const comando = texto.startsWith("/") ? texto.slice(1).split(/[\s@]/)[0].toLowerCase() : null;
  const dato = consulta?.data || "";

  // t.me/<bot>?start=tragsa (desde la web de Tragsa) llega como «/start tragsa»: empieza un aviso de ese organismo.
  const inicio = comando === "start" ? listas.organismos.find((o) => o.id === texto.split(/\s+/)[1]) : null;
  if ((comando === "start" && !inicio) || comando === "ayuda") return enviar(chat.id, escapar(AYUDA));
  if (comando === "privacidad") return enviar(chat.id, escapar(PRIVACIDAD));

  if (comando === "avisos" || dato.startsWith("borrar:")) {
    if (dato.startsWith("borrar:") && s) {
      await db.prepare("DELETE FROM avisos WHERE id = ? AND suscriptor = ?").bind(Number(dato.slice(7)), s.id).run();
    }
    const avisos = s
      ? (await db.prepare("SELECT id, criterios FROM avisos WHERE suscriptor = ? ORDER BY id").bind(s.id).all()).results
      : [];
    if (!avisos.length) {
      if (s && !s.borrador) await db.prepare("DELETE FROM suscriptores WHERE id = ?").bind(s.id).run();
      return enviar(chat.id, "No tienes avisos. Crea uno con /nuevo.");
    }
    const lineas = avisos.map((a, i) => `${i + 1}. ${escapar(describir(JSON.parse(a.criterios), listas))}`);
    return enviar(chat.id, `Tus avisos:\n\n${lineas.join("\n")}`, {
      reply_markup: teclado(avisos.map((a, i) => [boton(`Borrar el ${i + 1}`, `borrar:${a.id}`)])),
    });
  }

  if (comando === "baja") {
    if (!s) return enviar(chat.id, "No hay nada guardado de este chat.");
    return enviar(chat.id, "¿Borro todos tus avisos y el identificador de este chat?", {
      reply_markup: teclado([[boton("Sí, borrar todo", "baja:si"), boton("No", "baja:no")]]),
    });
  }
  if (dato === "baja:si") {
    if (s) await db.prepare("DELETE FROM suscriptores WHERE id = ?").bind(s.id).run();
    return enviar(chat.id, "Hecho: no queda ningún dato tuyo. Si quieres volver, usa /nuevo.");
  }
  if (dato === "baja:no") return enviar(chat.id, "De acuerdo, no he borrado nada.");

  if (comando === "nuevo" || inicio) {
    const n = s ? await db.prepare("SELECT COUNT(*) AS n FROM avisos WHERE suscriptor = ?").bind(s.id).first("n") : 0;
    if (n >= MAX_AVISOS) return enviar(chat.id, `Ya tienes ${MAX_AVISOS} avisos, el máximo. Borra alguno con /avisos.`);
    s = s || (await crearSuscriptor(db, chat.id, ahora));
    const c = inicio ? { organismos: [inicio.id] } : {};
    await guardarBorrador(db, s.id, { paso: "palabras", c });
    const p = pregunta("palabras", c, listas);
    const presentacion = inicio
      ? `Vamos a crear un aviso de las ofertas de ${escapar(inicio.nombre)}. Con /ayuda verás cómo funciona el bot.\n\n`
      : "";
    return enviar(chat.id, presentacion + p.text, { reply_markup: p.reply_markup });
  }

  if (comando === "cancelar" || dato === "cancelar") {
    if (s?.borrador) await olvidarSiVacio(db, s);
    return enviar(chat.id, "Cancelado. No he guardado nada nuevo.");
  }

  const borrador = s?.borrador ? JSON.parse(s.borrador) : null;
  if (!borrador) {
    return enviar(chat.id, comando ? "No conozco ese comando. Mira /ayuda." : "Para crear un aviso usa /nuevo. Para ver los tuyos, /avisos.");
  }
  const { paso, c } = borrador;
  let avanzar = false;

  if (dato.startsWith("area:") && paso === "areas") {
    const id = dato.slice(5);
    const elegidas = new Set(c.areas || []);
    if (elegidas.has(id)) elegidas.delete(id);
    else if (listas.areas.some((a) => a.id === id)) elegidas.add(id);
    c.areas = [...elegidas];
    await guardarBorrador(db, s.id, { paso, c });
    return telegram(env, "editMessageReplyMarkup", {
      chat_id: chat.id, message_id: consulta.message.message_id, reply_markup: pregunta("areas", c, listas).reply_markup,
    }, fetcher);
  } else if (dato === "saltar") {
    if (paso === "palabras") c.palabras = [];
    if (paso === "comunidades") c.ccaa = [];
    if (paso === "organismos") c.organismos = [];
    avanzar = ["palabras", "areas", "comunidades", "organismos"].includes(paso);
  } else if ((dato === "si" || dato === "no") && ["sin_ccaa", "teletrabajo", "comunicados"].includes(paso)) {
    c[paso] = dato === "si";
    avanzar = true;
  } else if (dato === "guardar" && paso === "resumen") {
    const limpio = limpiar(c, listas);
    const n = await db.prepare("SELECT COUNT(*) AS n FROM avisos WHERE suscriptor = ?").bind(s.id).first("n");
    if (!limpio || n >= MAX_AVISOS) return enviar(chat.id, "No he podido guardar el aviso. Empieza de nuevo con /nuevo.");
    await db.batch([
      db.prepare("INSERT INTO avisos (suscriptor, criterios, creado) VALUES (?, ?, ?)").bind(s.id, JSON.stringify(limpio), iso(ahora)),
      db.prepare("UPDATE suscriptores SET borrador = NULL WHERE id = ?").bind(s.id),
    ]);
    return enviar(chat.id, `Guardado. Te avisaré de las novedades que encajen con: ${escapar(describir(limpio, listas))}.\n\nPuedes crear otro con /nuevo o verlos con /avisos.`);
  } else if (texto && !comando && paso === "palabras") {
    const palabras = [...new Set(texto.split(/[,;\n]+/).map(normalizar).filter(Boolean))];
    if (!palabras.length || palabras.length > MAX_PALABRAS || palabras.some((p) => p.length > 60)) {
      return enviar(chat.id, `Escribe entre 1 y ${MAX_PALABRAS} palabras clave separadas por comas.`);
    }
    c.palabras = palabras;
    avanzar = true;
  } else if (texto && !comando && (paso === "comunidades" || paso === "organismos")) {
    const r = paso === "comunidades" ? reconocerComunidades(texto, listas) : reconocerOrganismos(texto, listas);
    if (r.dudas.length || r.fallos.length || !r.ok.length) {
      return enviar(chat.id, explicar(r, paso === "comunidades" ? "la comunidad" : "el organismo"));
    }
    c[paso === "comunidades" ? "ccaa" : "organismos"] = r.ok;
    avanzar = true;
  } else {
    return enviar(chat.id, "Responde a la pregunta de arriba, o usa /cancelar.");
  }

  if (avanzar) {
    const nuevo = siguiente(paso, c);
    await guardarBorrador(db, s.id, { paso: nuevo, c });
    const p = pregunta(nuevo, c, listas);
    return enviar(chat.id, p.text, { reply_markup: p.reply_markup });
  }
}
