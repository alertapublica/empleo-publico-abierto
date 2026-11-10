import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { atender } from "../src/bot.js";
import { alta, baja, confirmar, direccion, resumenCorreo } from "../src/correo.js";
import { coincide, describir, empiezaPalabra, limpiar, reconocerComunidades, reconocerOrganismos } from "../src/criterios.js";
import { vaciar } from "../src/envios.js";
import worker, { CRON_ENVIOS, CRONS_CORREO } from "../src/index.js";
import { MAX_MENSAJE, mensajeTelegram, recibir } from "../src/novedades.js";
import { abrirSesion, cabecera, componer, ErrorSmtp } from "../src/smtp.js";
import { LISTAS, d1, oferta, telegramFalso } from "./d1.mjs";
import { leerMensaje, smtpFalso } from "./smtp.mjs";

const AHORA = new Date("2026-11-09T07:00:00Z");

// --- Criterios ---------------------------------------------------------------------------------

test("palabras por comienzo de palabra, sin tildes ni mayúsculas", () => {
  assert.ok(empiezaPalabra("Ingeniero/a Agrónomo/a (Tenerife)", "ingenier"));
  assert.ok(empiezaPalabra("INGENIERA DE CAMINOS", "ingeniera"));
  assert.ok(empiezaPalabra("Técnico/a de administración", "tecnico"));
  assert.ok(empiezaPalabra("Auxiliar Administrativo/a - Lugo", "auxiliar administ"));
  assert.ok(!empiezaPalabra("Biotecnología", "tec"));
  assert.ok(!empiezaPalabra("Ingeniero/a", "ingeniera"));
});

test("criterios combinados: todos los apartados, uno dentro de cada uno", () => {
  const analistaGalicia = { palabras: ["analista"], ccaa: ["12"], sin_ccaa: false };
  assert.ok(coincide(analistaGalicia, oferta(1)));
  assert.ok(!coincide(analistaGalicia, oferta(2, { ccaa: "13" })));
  assert.ok(!coincide(analistaGalicia, oferta(3, { titulo: "Administrativo/a" })));
  assert.ok(coincide({ ...analistaGalicia, ccaa: ["03", "12"] }, oferta(4)));

  const analistaTragsa = { palabras: ["analista"], organismos: ["tragsa"] };
  assert.ok(coincide(analistaTragsa, oferta(5)));
  assert.ok(!coincide(analistaTragsa, oferta(6, { organismo: "isdefe" })));

  assert.ok(coincide({ areas: ["tic"], ccaa: ["12"] }, oferta(7)));
  assert.ok(!coincide({ areas: ["admin"] }, oferta(8)));
  assert.ok(coincide({}, oferta(9)), "un aviso vacío recibe todas las ofertas");
});

test("teletrabajo: solo las ofertas cuya ficha lo menciona", () => {
  const tele = { palabras: ["analista"], teletrabajo: true };
  assert.ok(coincide(tele, oferta(1, { teletrabajo: "Posibilidad de trabajo a distancia." })));
  assert.ok(!coincide(tele, oferta(2, { teletrabajo: false })));
  assert.ok(!coincide(tele, oferta(3, { teletrabajo: null })), "sin texto de la ficha no se puede comprobar");
  assert.ok(!coincide(tele, oferta(4)), "novedades.json antiguo, sin el campo");
  assert.ok(coincide({ palabras: ["analista"] }, oferta(5, { teletrabajo: null })), "sin el criterio no filtra");
  assert.match(mensajeTelegram([oferta(6, { teletrabajo: "Teletrabajo dos días." })])[0], /Menciona teletrabajo/);
});

test("ofertas sin comunidad concreta: incluidas salvo que se desactive", () => {
  const sin = oferta(1, { ccaa: null });
  assert.ok(coincide({ ccaa: ["12"] }, sin));
  assert.ok(coincide({ ccaa: ["12"], sin_ccaa: true }, sin));
  assert.ok(!coincide({ ccaa: ["12"], sin_ccaa: false }, sin));
});

test("comunicados solo con la casilla y del organismo elegido", () => {
  const com = { tipo: "comunicado", organismo: "tragsa", proceso: "Analista de sistemas (AB-1)", titulo: "Lista provisional", url: "u" };
  assert.ok(!coincide({ organismos: ["tragsa"] }, com));
  assert.ok(coincide({ organismos: ["tragsa"], comunicados: true }, com));
  assert.ok(!coincide({ organismos: ["isdefe"], comunicados: true }, com));
  assert.ok(coincide({ organismos: ["tragsa"], comunicados: true, palabras: ["analista"], ccaa: ["03"] }, com),
    "sin comunidad entra por defecto y las palabras miran el nombre del proceso");
});

test("comunicados: la comunidad del proceso, como en las ofertas", () => {
  const avisos = { organismos: ["puertos"], comunicados: true, ccaa: ["12"] };
  const de = (ccaa) => ({ tipo: "comunicado", organismo: "puertos", ccaa, proceso: "Policía Portuario", titulo: "Aparece", url: "u" });
  assert.ok(coincide(avisos, de("12")));
  assert.ok(!coincide(avisos, de("09")), "un proceso de Barcelona no llega a quien eligió Galicia");
  assert.ok(coincide(avisos, de(null)), "sin comunidad concreta, incluido por defecto");
  assert.ok(!coincide({ ...avisos, sin_ccaa: false }, de(null)));
  assert.ok(coincide({ organismos: ["puertos"], comunicados: true }, de("09")), "sin comunidades elegidas no filtra");
});

test("limpiar descarta claves desconocidas y valores raros", () => {
  const c = limpiar({ palabras: [" Analista ", "analista"], ccaa: ["12", "99"], organismos: ["nadie"], comunicados: true, areas: ["tic"] }, LISTAS);
  assert.deepEqual(c, { palabras: ["analista"], areas: ["tic"], ccaa: ["12"], organismos: [], sin_ccaa: true, teletrabajo: false, comunicados: false });
  assert.equal(limpiar({ palabras: Array.from({ length: 11 }, (_, i) => `p${i}`) }, LISTAS), null);
  assert.equal(describir(c, LISTAS), "«analista» · Informática y telecomunicaciones · Galicia (y sin comunidad concreta)");
});

test("reconoce comunidades y organismos escritos a mano", () => {
  assert.deepEqual(reconocerComunidades("galicia, Madrid, cataluña, valencia", LISTAS).ok, ["12", "13", "09", "10"]);
  const castilla = reconocerComunidades("castilla", LISTAS);
  assert.equal(castilla.dudas.length, 1);
  assert.deepEqual(reconocerComunidades("Narnia", LISTAS).fallos, ["Narnia"]);
  assert.deepEqual(reconocerOrganismos("tragsa, grupo correos", LISTAS).ok, ["tragsa", "correos"]);
  assert.equal(reconocerOrganismos("usc", LISTAS).dudas[0].opciones.length, 2);
  assert.equal(reconocerOrganismos("grupo", LISTAS).dudas.length, 1);
});

// --- Novedades y envíos ------------------------------------------------------------------------

async function conSuscriptor(db, criterios, canal = "telegram", destino = "100") {
  await db.prepare("INSERT INTO suscriptores (canal, destino, estado, token, creado) VALUES (?, ?, 'activo', ?, '2026-11-01')")
    .bind(canal, destino, `token-${destino}`).run();
  const id = await db.prepare("SELECT id FROM suscriptores WHERE destino = ?").bind(destino).first("id");
  await db.prepare("INSERT INTO avisos (suscriptor, criterios, creado) VALUES (?, ?, '2026-11-01')").bind(id, JSON.stringify(criterios)).run();
  return id;
}

test("la primera carga se guarda sin avisar y después solo se avisa lo nuevo, una vez", async () => {
  const db = d1();
  await conSuscriptor(db, { palabras: ["analista"], ccaa: ["12"] });
  const env = { DB: db };
  const primera = await recibir(env, { novedades: [oferta(1)], listas: LISTAS }, AHORA);
  assert.equal(primera.primera, true);
  assert.equal(primera.mensajes, 0);

  const carga = { novedades: [oferta(1), oferta(2), oferta(3, { ccaa: "13" })], listas: LISTAS };
  const segunda = await recibir(env, carga, AHORA);
  assert.deepEqual([segunda.nuevas, segunda.mensajes], [2, 1]);
  const { results } = await db.prepare("SELECT texto FROM envios").all();
  assert.match(results[0].texto, /Analista 2/);
  assert.doesNotMatch(results[0].texto, /Analista 3|Analista 1/);

  const tercera = await recibir(env, carga, AHORA);
  assert.deepEqual([tercera.nuevas, tercera.mensajes], [0, 0]);
});

test("no avisa de novedades antiguas aunque lleguen por primera vez", async () => {
  const db = d1();
  await conSuscriptor(db, {});
  await recibir({ DB: db }, { novedades: [oferta(1)], listas: LISTAS }, AHORA);
  const vieja = oferta(2, { id: "x/old", fecha: "2026-11-01T06:00:00+00:00" });
  const r = await recibir({ DB: db }, { novedades: [vieja], listas: LISTAS }, AHORA);
  assert.deepEqual([r.nuevas, r.mensajes], [1, 0]);
});

test("si el reparto falla, la recepción siguiente lo reintenta en vez de darlo por avisado", async () => {
  const db = d1();
  await conSuscriptor(db, {});
  await recibir({ DB: db }, { novedades: [oferta(1)], listas: LISTAS }, AHORA);
  const real = db.prepare;
  db.prepare = (sql) => {
    if (sql.includes("FROM avisos a")) throw new Error("D1 caído");
    return real(sql);
  };
  const carga = { novedades: [oferta(1), oferta(2)], listas: LISTAS };
  await assert.rejects(recibir({ DB: db }, carga, AHORA), /D1 caído/);
  db.prepare = real;
  const r = await recibir({ DB: db }, carga, AHORA);
  assert.deepEqual([r.nuevas, r.avisadas, r.mensajes], [0, 1, 1]);
  assert.match((await db.prepare("SELECT texto FROM envios").first("texto")), /Analista 2/);
  const otra = await recibir({ DB: db }, carga, AHORA);
  assert.deepEqual([otra.avisadas, otra.mensajes], [0, 0]);
});

test("rechaza cargas sin novedades o sin listas", async () => {
  await assert.rejects(recibir({ DB: d1() }, { novedades: [] }, AHORA), /Carga no válida/);
});

test("los mensajes largos se parten y el texto ajeno se escapa", () => {
  const muchas = Array.from({ length: 80 }, (_, i) => oferta(i, { titulo: `Analista <b>${"x".repeat(60)}</b> ${i}` }));
  const trozos = mensajeTelegram(muchas);
  assert.ok(trozos.length > 1);
  assert.ok(trozos.every((t) => t.length <= MAX_MENSAJE));
  assert.ok(trozos.every((t) => !t.includes("<b>x")));
  assert.match(trozos.at(-1), /\/avisos/);
});

test("un título desmesurado se recorta antes de escaparlo: el enlace sigue cerrado", () => {
  const [texto] = mensajeTelegram([oferta(1, { titulo: "x".repeat(4000) })]);
  assert.ok(texto.length <= MAX_MENSAJE);
  assert.match(texto, /x…<\/a>/);
});

test("vaciar envía, reintenta los 429 y borra a quien bloqueó el bot", async () => {
  const db = d1();
  const a = await conSuscriptor(db, {}, "telegram", "1");
  const b = await conSuscriptor(db, {}, "telegram", "2");
  const c = await conSuscriptor(db, {}, "telegram", "3");
  for (const id of [a, b, c]) {
    await db.prepare("INSERT INTO envios (suscriptor, texto, despues) VALUES (?, 'hola', '2026-11-09T06:00:00+00:00')").bind(id).run();
  }
  const tg = telegramFalso((_, d) => (d.chat_id === "2" ? { ok: false, status: 403 }
    : d.chat_id === "3" ? { ok: false, status: 429, parameters: { retry_after: 5 } } : { ok: true }));
  const r = await vaciar({ DB: db, TELEGRAM_TOKEN: "t" }, { ahora: AHORA, fetcher: tg.fetcher });
  assert.equal(r.enviados, 1);
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM suscriptores WHERE destino = '2'").first("n"), 0);
  const pendiente = await db.prepare("SELECT intentos, despues FROM envios").all();
  assert.deepEqual(pendiente.results, [{ intentos: 1, despues: "2026-11-09T07:00:05+00:00" }]);
});

test("dos tandas a la vez no mandan el mismo mensaje", async () => {
  const db = d1();
  const a = await conSuscriptor(db, {}, "telegram", "1");
  await db.prepare("INSERT INTO envios (suscriptor, texto, despues) VALUES (?, 'hola', '2026-11-09T06:00:00+00:00')").bind(a).run();
  const tg = telegramFalso();
  const env = { DB: db, TELEGRAM_TOKEN: "t" };
  const [x, y] = await Promise.all([vaciar(env, { ahora: AHORA, fetcher: tg.fetcher }), vaciar(env, { ahora: AHORA, fetcher: tg.fetcher })]);
  assert.equal(x.enviados + y.enviados, 1);
  assert.equal(tg.mensajes().length, 1);
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM envios").first("n"), 0);
});

test("sin token de Telegram no se intenta enviar", async () => {
  const r = await vaciar({ DB: d1() }, { fetcher: () => assert.fail("no debe llamar") });
  assert.equal(r.enviados, 0);
});

// --- Bot ---------------------------------------------------------------------------------------

function bot() {
  const db = d1();
  const tg = telegramFalso();
  const env = { DB: db, TELEGRAM_TOKEN: "t" };
  let n = 0;
  const escribir = (text) => atender(env, { message: { chat: { id: 42, type: "private" }, text } }, { fetcher: tg.fetcher, ahora: AHORA });
  const pulsar = (data) => atender(env, { callback_query: { id: `c${++n}`, data, message: { message_id: 7, chat: { id: 42, type: "private" } } } }, { fetcher: tg.fetcher, ahora: AHORA });
  const ultimo = () => tg.mensajes().at(-1)?.text || "";
  return { db, env, tg, escribir, pulsar, ultimo };
}

test("el bot crea un aviso analista + Galicia + Tragsa con comunicados", async () => {
  const b = bot();
  await b.db.prepare("INSERT INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(LISTAS)).run();
  await b.escribir("/nuevo");
  assert.match(b.ultimo(), /Paso 1 de 4/);
  await b.escribir("Analista, ingenier");
  assert.match(b.ultimo(), /Paso 2 de 4/);
  await b.pulsar("area:tic");
  assert.equal(b.tg.llamadas.at(-1).metodo, "editMessageReplyMarkup");
  await b.pulsar("saltar");
  assert.match(b.ultimo(), /teletrabajo/);
  await b.pulsar("si");
  assert.match(b.ultimo(), /Paso 3 de 4/);
  await b.escribir("castilla");
  assert.match(b.ultimo(), /puede ser/);
  await b.escribir("galicia");
  assert.match(b.ultimo(), /no dicen la comunidad/);
  await b.pulsar("no");
  await b.escribir("tragsa");
  assert.match(b.ultimo(), /comunicados/);
  await b.pulsar("si");
  assert.match(b.ultimo(), /¿Lo guardo\?/);
  await b.pulsar("guardar");
  assert.match(b.ultimo(), /Guardado/);
  const aviso = JSON.parse(await b.db.prepare("SELECT criterios FROM avisos").first("criterios"));
  assert.deepEqual(aviso, {
    palabras: ["analista", "ingenier"], areas: ["tic"], ccaa: ["12"], organismos: ["tragsa"], sin_ccaa: false, teletrabajo: true,
    comunicados: true,
  });
  assert.equal(await b.db.prepare("SELECT borrador FROM suscriptores").first("borrador"), null);

  await b.escribir("/avisos");
  assert.match(b.ultimo(), /1\. «analista», «ingenier» · Informática y telecomunicaciones · que mencionen teletrabajo · Galicia/);
  const id = await b.db.prepare("SELECT id FROM avisos").first("id");
  await b.pulsar(`borrar:${id}`);
  assert.match(b.ultimo(), /No tienes avisos/);
  assert.equal(await b.db.prepare("SELECT COUNT(*) AS n FROM suscriptores").first("n"), 0, "sin avisos no se guarda el chat");
});

test("el enlace t.me/<bot>?start=tragsa crea un aviso con el organismo ya elegido", async () => {
  const b = bot();
  await b.db.prepare("INSERT INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(LISTAS)).run();
  await b.escribir("/start noexiste");
  assert.match(b.ultimo(), /\/nuevo crea un aviso/, "un organismo desconocido da la ayuda");
  await b.escribir("/start tragsa");
  assert.match(b.ultimo(), /aviso de las ofertas de Grupo Tragsa/);
  assert.match(b.ultimo(), /Paso 1 de 3/);
  await b.pulsar("saltar");
  assert.match(b.ultimo(), /Paso 2 de 3/);
  await b.pulsar("saltar");
  await b.pulsar("no");
  assert.match(b.ultimo(), /Paso 3 de 3/);
  await b.pulsar("saltar");
  assert.match(b.ultimo(), /comunicados/, "sin preguntar por los organismos");
  await b.pulsar("si");
  await b.pulsar("guardar");
  assert.match(b.ultimo(), /Guardado/);
  const aviso = JSON.parse(await b.db.prepare("SELECT criterios FROM avisos").first("criterios"));
  assert.deepEqual(aviso.organismos, ["tragsa"]);
  assert.equal(aviso.comunicados, true);
});

test("cancelar a medias no deja datos y /baja lo borra todo", async () => {
  const b = bot();
  await b.db.prepare("INSERT INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(LISTAS)).run();
  await b.escribir("/nuevo");
  await b.pulsar("cancelar");
  assert.equal(await b.db.prepare("SELECT COUNT(*) AS n FROM suscriptores").first("n"), 0);

  await b.escribir("/nuevo");
  for (const paso of ["saltar", "saltar", "no", "saltar", "saltar", "guardar"]) await b.pulsar(paso);
  assert.match(b.ultimo(), /Todas las ofertas nuevas/);
  await b.escribir("/baja");
  await b.pulsar("baja:si");
  assert.equal(await b.db.prepare("SELECT COUNT(*) AS n FROM suscriptores").first("n"), 0);
  assert.equal(await b.db.prepare("SELECT COUNT(*) AS n FROM avisos").first("n"), 0);
});

test("el bot ignora los grupos y respeta el máximo de avisos", async () => {
  const b = bot();
  await b.db.prepare("INSERT INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(LISTAS)).run();
  await atender(b.env, { message: { chat: { id: -5, type: "group" }, text: "/nuevo" } }, { fetcher: b.tg.fetcher });
  assert.equal(b.tg.llamadas.length, 0);
  const id = await conSuscriptor(b.db, {}, "telegram", "42");
  for (let i = 1; i < 10; i++) await b.db.prepare("INSERT INTO avisos (suscriptor, criterios, creado) VALUES (?, '{}', 'x')").bind(id).run();
  await b.escribir("/nuevo");
  assert.match(b.ultimo(), /el máximo/);
});

// --- Correo ------------------------------------------------------------------------------------

const correoEnv = (db, smtp, extra = {}) => ({
  DB: db, CORREO_ACTIVO: "si", CORREO_REMITENTE: "avisos@ejemplo.es", CORREO_NOMBRE: "Empleo en Empresas Públicas",
  SMTP_SERVIDOR: "smtp.ejemplo.es", SMTP_PUERTO: "465", SMTP_USUARIO: "avisos@ejemplo.es", SMTP_CLAVE: "c,là`ve@",
  URL_PUBLICA: "https://avisos.ejemplo.es", TURNSTILE_SECRETO: "s", CONECTAR_SMTP: smtp.conectar, ...extra,
});
const turnstileOk = async () => Response.json({ success: true });
// Como lo envía el formulario de /avisos/: casillas repetidas con las claves de listas.json.
const formAlta = (correo, campos = [["palabras", "analista"]]) => new Request("https://x/correo/alta", {
  method: "POST", body: new URLSearchParams([["correo", correo], ...campos, ["cf-turnstile-response", "x"]]),
});

test("mensaje: cabeceras con tildes codificadas y cuerpo quoted-printable", () => {
  const largo = `Analista de sistemas con experiencia en ${"administración ".repeat(8)}= fin `;
  const crudo = componer({
    de: "avisos@ejemplo.es", nombre: "Empleo en Empresas Públicas", para: "ana@ejemplo.es",
    asunto: `3 novedades para tus avisos de empleo público ${"ñ".repeat(40)}\r\nBcc: otro@ejemplo.es`,
    texto: `Hola\n${largo}\n.línea que empieza por punto`, baja: "https://avisos.ejemplo.es/correo/baja?t=abc",
    fecha: new Date("2026-11-09T06:00:00Z"), id: "id-1",
  });
  for (const linea of crudo.split("\r\n")) assert.ok(linea.length <= 78, `línea demasiado larga: ${linea}`);
  assert.doesNotMatch(crudo, /[^\x00-\x7f]/, "todo ASCII");
  assert.doesNotMatch(crudo, /\r\nBcc:/, "el asunto no puede inyectar cabeceras");
  const { cabeceras, texto } = leerMensaje(crudo);
  assert.equal(cabeceras.Subject, `3 novedades para tus avisos de empleo público ${"ñ".repeat(40)} Bcc: otro@ejemplo.es`);
  assert.equal(cabeceras.From, "Empleo en Empresas Públicas <avisos@ejemplo.es>");
  assert.equal(cabeceras.To, "<ana@ejemplo.es>");
  assert.equal(cabeceras.Date, "Mon, 09 Nov 2026 06:00:00 +0000");
  assert.equal(cabeceras["Message-ID"], "<id-1@ejemplo.es>");
  assert.equal(cabeceras["Auto-Submitted"], "auto-generated");
  assert.equal(cabeceras["List-Unsubscribe"], "<https://avisos.ejemplo.es/correo/baja?t=abc>");
  assert.equal(cabeceras["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click");
  assert.equal(texto, `Hola\n${largo}\n.línea que empieza por punto\n`, "el espacio final y el «=» sobreviven");
  assert.equal(cabecera("Asunto sin tildes"), "Asunto sin tildes");
});

test("direcciones: minúsculas, dominio con tildes a punycode, nada que inyecte", () => {
  assert.equal(direccion(" Ana.Pérez@Ejemplo.es "), null, "tilde antes de la @");
  assert.equal(direccion("Ana@Ejemplo.ES"), "ana@ejemplo.es");
  assert.equal(direccion("ana@españa.es"), "ana@xn--espaa-rta.es");
  assert.equal(direccion("ana+avisos@ejemplo.es"), "ana+avisos@ejemplo.es");
  for (const mala of ["ana", "@ejemplo.es", "ana@ejemplo", "ana@ejemplo.es>\r\nRCPT TO:<b@c.es", "a b@ejemplo.es", "ana@ejem plo.es", "ana@[1.2.3.4]"]) {
    assert.equal(direccion(mala), null, mala);
  }
});

test("sesión SMTP: TLS, EHLO, AUTH PLAIN en UTF-8, puntos doblados y QUIT", async () => {
  const smtp = smtpFalso();
  const sesion = await abrirSesion({ servidor: "smtp.ejemplo.es", usuario: "avisos@ejemplo.es", clave: "c,là`ve@", nombre: "ejemplo.es" }, smtp.conectar);
  await sesion.enviar("avisos@ejemplo.es", "ana@ejemplo.es", "Subject: x\r\n\r\nuno\r\n.dos\r\n");
  await sesion.enviar("avisos@ejemplo.es", "luis@ejemplo.es", "Subject: y\r\n\r\ntres\r\n");
  await sesion.cerrar();
  const [s] = smtp.sesiones;
  assert.deepEqual(s.direccion, { hostname: "smtp.ejemplo.es", port: 465 });
  assert.equal(s.opciones.secureTransport, "on");
  assert.equal(s.ordenes[0], "EHLO ejemplo.es");
  const plano = new TextDecoder().decode(Uint8Array.from(atob(s.ordenes[1].split(" ")[2]), (c) => c.charCodeAt(0)));
  assert.equal(plano, "\0avisos@ejemplo.es\0c,là`ve@");
  assert.deepEqual(s.ordenes.filter((o) => /^(MAIL|RCPT)/.test(o)), [
    "MAIL FROM:<avisos@ejemplo.es>", "RCPT TO:<ana@ejemplo.es>", "MAIL FROM:<avisos@ejemplo.es>", "RCPT TO:<luis@ejemplo.es>",
  ]);
  assert.equal(s.mensajes[0], "Subject: x\r\n\r\nuno\r\n.dos\r\n");
  assert.equal(s.ordenes.at(-1), "QUIT");
  assert.ok(s.cerrada);
});

test("sesión SMTP: destinatario rechazado, contraseña mala y servidor mudo", async () => {
  const smtp = smtpFalso({ RCPT: (l) => (l.includes("mala@") ? "550 5.1.1 <mala@ejemplo.es>: no existe" : "250 OK") });
  const sesion = await abrirSesion({ servidor: "s", usuario: "u", clave: "c" }, smtp.conectar);
  const error = await sesion.enviar("a@ejemplo.es", "mala@ejemplo.es", "x\r\n").catch((e) => e);
  assert.ok(error instanceof ErrorSmtp && error.definitivo);
  assert.equal(error.message, "SMTP 550 en RCPT", "sin el texto del servidor, que trae la dirección");
  assert.ok(!sesion.rota, "tras RSET la sesión sigue sirviendo");
  await sesion.enviar("a@ejemplo.es", "buena@ejemplo.es", "x\r\n");
  await sesion.cerrar();
  assert.ok(smtp.sesiones[0].ordenes.includes("RSET"));

  const mala = await abrirSesion({ servidor: "s", usuario: "u", clave: "c" }, smtpFalso({ AUTH: "535 5.7.8 No" }).conectar).catch((e) => e);
  assert.equal(mala.message, "SMTP 535 en AUTH");
  assert.ok(!mala.definitivo);

  const mudo = smtpFalso({ DATA: null });
  const s2 = await abrirSesion({ servidor: "s", usuario: "u", clave: "c", espera: 50 }, mudo.conectar);
  const e2 = await s2.enviar("a@ejemplo.es", "b@ejemplo.es", "x\r\n").catch((e) => e);
  assert.equal(e2.message, "SMTP sin respuesta en DATA");
  assert.ok(s2.rota);
  await s2.cerrar();
  assert.ok(mudo.sesiones[0].cerrada);
});

test("correo desactivado: el alta responde 503 y el resumen no hace nada", async () => {
  const peticion = new Request("https://x/correo/alta", { method: "POST", body: new URLSearchParams({ correo: "a@b.es" }) });
  const r = await worker.fetch(peticion, { DB: d1(), CORREO_ACTIVO: "no" }, { waitUntil() {} });
  assert.equal(r.status, 503);
  assert.equal(await resumenCorreo({ DB: d1(), CORREO_ACTIVO: "no" }, AHORA), 0);
  const sinClave = correoEnv(d1(), smtpFalso(), { SMTP_CLAVE: "" });
  assert.equal((await worker.fetch(formAlta("a@b.es"), sinClave, { waitUntil() {} })).status, 503, "sin contraseña no está activo");
});

test("correo activo: alta con doble confirmación, resúmenes y baja con un clic", async () => {
  const db = d1();
  const smtp = smtpFalso();
  const env = correoEnv(db, smtp);
  const enviados = () => smtp.sesiones.flatMap((s) => s.mensajes).map(leerMensaje);
  await db.prepare("INSERT INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(LISTAS)).run();
  const r = await alta(env, formAlta("Ana@Ejemplo.es"), { fetcher: turnstileOk, ahora: AHORA });
  assert.equal(r.status, 200);
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM avisos").first("n"), 0, "sin confirmar no hay aviso");
  const confirmacion = enviados()[0];
  assert.equal(confirmacion.cabeceras.Subject, "Confirma tu aviso de empleo público");
  assert.equal(confirmacion.cabeceras["List-Unsubscribe"], undefined);
  const enlace = confirmacion.texto.match(/https:\S+confirmar\?t=\S+/)[0];
  assert.equal((await confirmar(env, new URL(enlace), { ahora: AHORA })).status, 200);
  assert.equal((await confirmar(env, new URL(enlace), { ahora: AHORA })).status, 404, "el enlace sirve una vez");
  assert.equal(await db.prepare("SELECT estado FROM suscriptores").first("estado"), "activo");

  await resumenCorreo(env, AHORA); // fija el cursor
  await recibir(env, { novedades: [oferta(0)], listas: LISTAS }, AHORA); // primera carga, sin avisos
  await recibir(env, { novedades: [oferta(1), oferta(2, { titulo: "Conductor/a" })], listas: LISTAS }, AHORA);
  assert.equal(await resumenCorreo(env, AHORA), 1);
  await vaciar(env, { ahora: AHORA });
  const resumen = enviados().at(-1);
  assert.equal(resumen.cabeceras.To, "<ana@ejemplo.es>");
  assert.match(resumen.texto, /Analista 1/);
  assert.doesNotMatch(resumen.texto, /Conductor/);
  const bajaUrl = resumen.cabeceras["List-Unsubscribe"].slice(1, -1);
  assert.equal(resumen.cabeceras["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click");
  assert.ok(resumen.texto.includes(`Darte de baja de estos avisos: ${bajaUrl}`));

  const get = await baja(env, new Request(bajaUrl), new URL(bajaUrl));
  assert.match(await get.text(), /<form method="post"/);
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM suscriptores").first("n"), 1, "abrir el enlace no da de baja");
  await baja(env, new Request(bajaUrl, { method: "POST" }), new URL(bajaUrl));
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM suscriptores").first("n"), 0);
});

test("los crons de wrangler.jsonc coinciden con los del código y el correo sale por la mañana y por la tarde", async () => {
  const jsonc = readFileSync(new URL("../wrangler.jsonc", import.meta.url), "utf8").replace(/^\s*\/\/.*$/gm, "");
  const { triggers } = JSON.parse(jsonc);
  assert.deepEqual([...triggers.crons].sort(), [CRON_ENVIOS, ...CRONS_CORREO].sort());
  assert.equal(CRONS_CORREO.length, 2);
  for (const cron of CRONS_CORREO) {
    const db = d1();
    const env = correoEnv(db, smtpFalso());
    await worker.scheduled({ cron }, env, { waitUntil() {} });
    assert.equal(await db.prepare("SELECT valor FROM estado WHERE clave = 'correo_desde'").first("valor"), "0", `${cron} fija el cursor`);
  }
  const db = d1();
  await worker.scheduled({ cron: CRON_ENVIOS }, correoEnv(db, smtpFalso()), { waitUntil() {} });
  assert.equal(await db.prepare("SELECT valor FROM estado WHERE clave = 'correo_desde'").first("valor"), null, "el cron de envíos no prepara resumen");
});

test("alta: los criterios llegan como casillas del formulario y se limpian", async () => {
  const db = d1();
  await db.prepare("INSERT INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(LISTAS)).run();
  const env = correoEnv(db, smtpFalso());
  const campos = [["palabras", " Analista, ingenier ,"], ["areas", "tic"], ["areas", "inventada"], ["ccaa", "12"], ["ccaa", "03"],
    ["organismos", "tragsa"], ["comunicados", "1"], ["teletrabajo", "1"]];
  assert.equal((await alta(env, formAlta("ana@ejemplo.es", campos), { fetcher: turnstileOk, ahora: AHORA })).status, 200);
  const { criterios } = JSON.parse(await db.prepare("SELECT borrador FROM suscriptores").first("borrador"));
  assert.deepEqual(criterios, {
    palabras: ["analista", "ingenier"], areas: ["tic"], ccaa: ["12", "03"], organismos: ["tragsa"],
    sin_ccaa: false, teletrabajo: true, comunicados: true,
  }, "sin la casilla «sin comunidad» marcada, se excluyen");
  const muchas = [["palabras", Array.from({ length: 11 }, (_, i) => `p${i}`).join(",")]];
  assert.equal((await alta(env, formAlta("luis@ejemplo.es", muchas), { fetcher: turnstileOk, ahora: AHORA })).status, 400);
  const sinListas = correoEnv(d1(), smtpFalso());
  assert.equal((await alta(sinListas, formAlta("eva@ejemplo.es"), { fetcher: turnstileOk, ahora: AHORA })).status, 503);
});

test("alta: espera entre confirmaciones y se deshace si no sale el correo", async () => {
  const db = d1();
  await db.prepare("INSERT INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(LISTAS)).run();
  const smtp = smtpFalso();
  const env = correoEnv(db, smtp);
  assert.equal((await alta(env, formAlta("ana@ejemplo.es"), { fetcher: turnstileOk, ahora: AHORA })).status, 200);
  const pronto = new Date(AHORA.getTime() + 5 * 60000);
  assert.equal((await alta(env, formAlta("ana@ejemplo.es"), { fetcher: turnstileOk, ahora: pronto })).status, 429);
  assert.equal(smtp.sesiones.length, 1, "no se reenvía antes de 15 minutos");
  const luego = new Date(AHORA.getTime() + 16 * 60000);
  assert.equal((await alta(env, formAlta("ana@ejemplo.es"), { fetcher: turnstileOk, ahora: luego })).status, 200);
  assert.equal(smtp.sesiones.length, 2);
  assert.equal((await alta(env, formAlta("josé@ejemplo.es"), { fetcher: turnstileOk, ahora: AHORA })).status, 400);

  const caido = correoEnv(db, smtpFalso({ AUTH: "535 No" }));
  const r = await alta(caido, formAlta("luis@ejemplo.es"), { fetcher: turnstileOk, ahora: AHORA });
  assert.equal(r.status, 503);
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM suscriptores WHERE destino = 'luis@ejemplo.es'").first("n"), 0);
  const repetida = await alta(correoEnv(db, smtpFalso()), formAlta("luis@ejemplo.es"), { fetcher: turnstileOk, ahora: AHORA });
  assert.equal(repetida.status, 200, "puede repetirse enseguida");
});

test("bandeja de correo: una sesión por tanda, tope, rechazos y conexión caída", async () => {
  const db = d1();
  const suscriptor = async (correo) => (await db.prepare(
    "INSERT INTO suscriptores (canal, destino, estado, token, creado) VALUES ('correo', ?, 'activo', ?, 'x')",
  ).bind(correo, `t-${correo}`).run()).meta.last_row_id;
  for (const correo of ["a@ejemplo.es", "mala@ejemplo.es", "c@ejemplo.es", "d@ejemplo.es"]) {
    await db.prepare("INSERT INTO envios (suscriptor, asunto, texto, despues) VALUES (?, 'Asunto', 'Texto', '2026-11-09T06:00:00+00:00')")
      .bind(await suscriptor(correo)).run();
  }
  const smtp = smtpFalso({ RCPT: (l) => (l.includes("mala@") ? "550 No existe" : "250 OK") });
  const r = await vaciar(correoEnv(db, smtp, { CORREO_POR_TANDA: "3" }), { ahora: AHORA });
  assert.deepEqual(r, { enviados: 2, fallidos: 1, aplazados: 1 });
  assert.equal(smtp.sesiones.length, 1, "un solo inicio de sesión");
  const quedan = await db.prepare("SELECT s.destino, e.intentos FROM envios e JOIN suscriptores s ON s.id = e.suscriptor").all();
  assert.deepEqual(quedan.results, [{ destino: "d@ejemplo.es", intentos: 0 }], "rechazo descartado; el del tope, intacto");

  await db.prepare("INSERT INTO envios (suscriptor, asunto, texto, despues) VALUES (1, 'Asunto', 'Texto', '2026-11-09T06:00:00+00:00')").run();
  const caido = await vaciar(correoEnv(db, smtpFalso({ AUTH: "454 Inténtalo luego" })), { ahora: AHORA });
  assert.deepEqual(caido, { enviados: 0, fallidos: 1, aplazados: 1 });
  const tras = await db.prepare("SELECT intentos FROM envios ORDER BY id").all();
  assert.deepEqual(tras.results.map((f) => f.intentos), [1, 0], "solo el primero gasta intento");
});

test("correo de prueba: exige la clave y avisa si el SMTP falla", async () => {
  const smtp = smtpFalso();
  const env = { ...correoEnv(d1(), smtp, { CORREO_ACTIVO: "no" }), AVISOS_CLAVE: "clave" };
  const ctx = { waitUntil() {} };
  const prueba = (auth, para = "ana@ejemplo.es") => new Request("https://x/interno/correo-prueba", {
    method: "POST", headers: auth ? { Authorization: auth } : {}, body: JSON.stringify({ para }),
  });
  assert.equal((await worker.fetch(prueba(), env, ctx)).status, 401);
  assert.equal((await worker.fetch(prueba("Bearer clave", "nada"), env, ctx)).status, 400);
  const ok = await worker.fetch(prueba("Bearer clave"), env, ctx);
  assert.deepEqual(await ok.json(), { enviado: true });
  const { cabeceras } = leerMensaje(smtp.sesiones[0].mensajes[0]);
  assert.equal(cabeceras.Subject, "Prueba del correo de avisos de empleo público");
  const malo = { ...env, CONECTAR_SMTP: smtpFalso({ AUTH: "535 No" }).conectar };
  const r = await worker.fetch(prueba("Bearer clave"), malo, ctx);
  assert.equal(r.status, 502);
  assert.deepEqual(await r.json(), { error: "SMTP 535 en AUTH" });
  assert.equal((await worker.fetch(prueba("Bearer clave"), { ...env, SMTP_CLAVE: "" }, ctx)).status, 409);
});

// --- Rutas -------------------------------------------------------------------------------------

test("las rutas internas y el webhook exigen su secreto", async () => {
  const env = { DB: d1(), AVISOS_CLAVE: "clave", TELEGRAM_TOKEN: "t", TELEGRAM_SECRETO: "s" };
  const ctx = { waitUntil() {} };
  const publicado = (auth) => new Request("https://x/interno/publicado", { method: "POST", headers: auth ? { Authorization: auth } : {}, body: "{}" });
  assert.equal((await worker.fetch(publicado(), env, ctx)).status, 401);
  assert.equal((await worker.fetch(publicado("Bearer otra"), env, ctx)).status, 401);
  assert.equal((await worker.fetch(publicado("Bearer clave"), env, ctx)).status, 500, "carga vacía");
  const tg = new Request("https://x/telegram", { method: "POST", headers: { "X-Telegram-Bot-Api-Secret-Token": "mal" }, body: "{}" });
  assert.equal((await worker.fetch(tg, env, ctx)).status, 401);
  // Sin secreto configurado, una petición sin cabecera tampoco pasa.
  const sinSecreto = { ...env, TELEGRAM_SECRETO: undefined };
  assert.equal((await worker.fetch(new Request("https://x/telegram", { method: "POST", body: "{}" }), sinSecreto, ctx)).status, 401);
  assert.equal((await worker.fetch(new Request("https://x/nada"), env, ctx)).status, 404);
});
