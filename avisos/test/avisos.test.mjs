import assert from "node:assert/strict";
import { test } from "node:test";
import { atender } from "../src/bot.js";
import { confirmar, baja, resumenDiario } from "../src/correo.js";
import { coincide, describir, empiezaPalabra, limpiar, reconocerComunidades, reconocerOrganismos } from "../src/criterios.js";
import { vaciar } from "../src/envios.js";
import worker from "../src/index.js";
import { MAX_MENSAJE, mensajeTelegram, recibir } from "../src/novedades.js";
import { LISTAS, d1, oferta, telegramFalso } from "./d1.mjs";

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
    "la comunidad no se aplica a los comunicados y las palabras miran el nombre del proceso");
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

// --- Correo (preparado, desactivado) -------------------------------------------------------------

test("correo desactivado: el alta responde 503 y el resumen no hace nada", async () => {
  const peticion = new Request("https://x/correo/alta", { method: "POST", body: new URLSearchParams({ correo: "a@b.es" }) });
  const r = await worker.fetch(peticion, { DB: d1(), CORREO_ACTIVO: "no" }, { waitUntil() {} });
  assert.equal(r.status, 503);
  assert.equal(await resumenDiario({ DB: d1(), CORREO_ACTIVO: "no" }, AHORA), 0);
});

test("correo activo: alta con doble confirmación, resumen diario y baja con un clic", async () => {
  const db = d1();
  const enviados = [];
  const env = {
    DB: db, CORREO_ACTIVO: "si", CORREO_REMITENTE: "avisos@ejemplo.es", URL_PUBLICA: "https://avisos.ejemplo.es",
    TURNSTILE_SECRETO: "s", CORREO: { send: async (m) => enviados.push(m) },
  };
  await db.prepare("INSERT INTO estado (clave, valor) VALUES ('listas', ?)").bind(JSON.stringify(LISTAS)).run();
  const { alta } = await import("../src/correo.js");
  const turnstileOk = async () => Response.json({ success: true });
  const form = new URLSearchParams({ correo: "Ana@Ejemplo.es", criterios: JSON.stringify({ palabras: ["analista"] }), "cf-turnstile-response": "x" });
  const r = await alta(env, new Request("https://x/correo/alta", { method: "POST", body: form }), { fetcher: turnstileOk, ahora: AHORA });
  assert.equal(r.status, 200);
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM avisos").first("n"), 0, "sin confirmar no hay aviso");
  const enlace = enviados[0].text.match(/https:\S+confirmar\?t=\S+/)[0];
  assert.equal((await confirmar(env, new URL(enlace), { ahora: AHORA })).status, 200);
  assert.equal((await confirmar(env, new URL(enlace), { ahora: AHORA })).status, 404, "el enlace sirve una vez");
  assert.equal(await db.prepare("SELECT estado FROM suscriptores").first("estado"), "activo");

  await resumenDiario(env, AHORA); // fija el cursor
  await recibir(env, { novedades: [oferta(0)], listas: LISTAS }, AHORA); // primera carga, sin avisos
  await recibir(env, { novedades: [oferta(1), oferta(2, { titulo: "Conductor/a" })], listas: LISTAS }, AHORA);
  assert.equal(await resumenDiario(env, AHORA), 1);
  await vaciar(env, { ahora: AHORA });
  const resumen = enviados.at(-1);
  assert.equal(resumen.to, "ana@ejemplo.es");
  assert.match(resumen.text, /Analista 1/);
  assert.doesNotMatch(resumen.text, /Conductor/);
  const bajaUrl = resumen.headers["List-Unsubscribe"].slice(1, -1);
  assert.equal(resumen.headers["List-Unsubscribe-Post"], "List-Unsubscribe=One-Click");

  const get = await baja(env, new Request(bajaUrl), new URL(bajaUrl));
  assert.match(await get.text(), /<form method="post"/);
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM suscriptores").first("n"), 1, "abrir el enlace no da de baja");
  await baja(env, new Request(bajaUrl, { method: "POST" }), new URL(bajaUrl));
  assert.equal(await db.prepare("SELECT COUNT(*) AS n FROM suscriptores").first("n"), 0);
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
  assert.equal((await worker.fetch(new Request("https://x/nada"), env, ctx)).status, 404);
});
