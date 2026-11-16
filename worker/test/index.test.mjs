import assert from "node:assert/strict";
import { test } from "node:test";
import worker, { lanzar, toca, tocaPag } from "../src/index.js";

const env = { GITHUB_TOKEN: "t", REPO: "dueño/repo", WORKFLOW: "actualizar.yml", REF: "main" };

test("lanza el workflow en la rama indicada", async () => {
  let llamada;
  await lanzar(env, async (url, opciones) => {
    llamada = { url, opciones };
    return new Response(null, { status: 204 });
  });
  assert.equal(llamada.url, "https://api.github.com/repos/dueño/repo/actions/workflows/actualizar.yml/dispatches");
  assert.equal(llamada.opciones.method, "POST");
  assert.equal(llamada.opciones.headers.Authorization, "Bearer t");
  assert.deepEqual(JSON.parse(llamada.opciones.body), { ref: "main" });
});

test("falla si GitHub no responde 204", async () => {
  await assert.rejects(
    lanzar(env, async () => new Response("Bad credentials", { status: 401 })),
    /GitHub respondió 401 \(actualizar.yml\): Bad credentials/,
  );
});

test("falla sin token", async () => {
  await assert.rejects(lanzar({ ...env, GITHUB_TOKEN: "" }, async () => assert.fail("no debe llamar")), /GITHUB_TOKEN/);
});

// Cada fecha es UTC; entre paréntesis, la hora de Madrid (invierno +1, verano +2).
const lanza = (iso) => toca(new Date(iso));

// Las lecturas de un día, en hora de Madrid, a partir de los disparos del cron (:07 y :37 UTC).
const lecturas = (dia) => {
  const horas = [];
  for (let t = Date.parse(`${dia}T00:00:00Z`) - 3 * 3600e3; t < Date.parse(`${dia}T00:00:00Z`) + 24 * 3600e3; t += 30 * 60e3) {
    const fecha = new Date(t + 7 * 60e3);
    const madrid = new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Madrid", day: "2-digit", hour: "numeric", minute: "2-digit", hourCycle: "h23" }).formatToParts(fecha);
    const parte = (tipo) => madrid.find((p) => p.type === tipo).value;
    if (parte("day") === dia.slice(8) && toca(fecha)) horas.push(`${Number(parte("hour"))}:${parte("minute")}`);
  }
  return horas;
};
const cada30 = (desde, hasta) => Array.from({ length: (hasta - desde) * 2 }, (_, i) => `${desde + Math.floor(i / 2)}:${i % 2 ? "37" : "07"}`);

test("entre semana: cada 30 min de 6:00 a 19:00, a las 20 y las 22 h, y nada de madrugada", () => {
  assert.deepEqual(lecturas("2026-11-10"), [...cada30(6, 19), "20:07", "22:07"]); // martes
  assert.equal(lecturas("2026-11-10").length, 28);
  assert.equal(lanza("2026-11-10T17:37:00Z"), true); // martes 18:37
  assert.equal(lanza("2026-11-10T18:07:00Z"), false); // martes 19:07
  assert.equal(lanza("2026-11-10T04:37:00Z"), false); // martes 5:37
});

test("fin de semana: cada 3 horas de las 8 a las 20 h", () => {
  assert.deepEqual(lecturas("2026-11-14"), ["8:07", "11:07", "14:07", "17:07", "20:07"]); // sábado
  assert.deepEqual(lecturas("2026-11-15"), ["8:07", "11:07", "14:07", "17:07", "20:07"]); // domingo
});

test("sigue la hora de Madrid en verano y en los cambios de hora", () => {
  assert.deepEqual(lecturas("2026-07-07"), [...cada30(6, 19), "20:07", "22:07"]); // martes (+2)
  assert.equal(lanza("2026-07-07T04:07:00Z"), true); // martes 6:07
  assert.equal(lanza("2026-07-07T03:37:00Z"), false); // martes 5:37
  // Los domingos en que cambia la hora (29 de marzo y 25 de octubre de 2026), las mismas horas de Madrid.
  assert.deepEqual(lecturas("2026-03-29"), ["8:07", "11:07", "14:07", "17:07", "20:07"]);
  assert.deepEqual(lecturas("2026-10-25"), ["8:07", "11:07", "14:07", "17:07", "20:07"]);
});

test("scheduled lanza el workflow solo cuando toca", async () => {
  const original = globalThis.fetch;
  let llamadas = 0;
  globalThis.fetch = async () => { llamadas++; return new Response(null, { status: 204 }); };
  try {
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-10T18:37:00Z") }, env, {}); // martes 19:37
    assert.equal(llamadas, 0);
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-10T05:37:00Z") }, env, {});
    assert.equal(llamadas, 1);
  } finally {
    globalThis.fetch = original;
  }
});

test("lectura del PAG: a las 2:07, 3:07 y 5:07 UTC, todo el año", () => {
  const pag = (iso) => tocaPag(new Date(iso));
  assert.equal(pag("2026-11-16T02:07:00Z"), true);
  assert.equal(pag("2026-11-16T03:07:00Z"), true);
  assert.equal(pag("2026-11-16T05:07:00Z"), true);
  assert.equal(pag("2026-07-07T02:07:00Z"), true); // en verano, también en UTC
  assert.equal(pag("2026-11-16T02:37:00Z"), false);
  assert.equal(pag("2026-11-16T04:07:00Z"), false);
  assert.equal(pag("2026-11-16T01:07:00Z"), false);
  assert.equal(pag("2026-11-16T06:07:00Z"), false);
});

test("lanza noche.yml del PAG con si_falta, junto a la ingesta si coinciden", async () => {
  const original = globalThis.fetch;
  const llamadas = [];
  globalThis.fetch = async (url, opciones) => { llamadas.push({ url, cuerpo: JSON.parse(opciones.body) }); return new Response(null, { status: 204 }); };
  const conPag = { ...env, PAG_REPO: "dueño/pag" };
  try {
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-16T02:07:00Z") }, conPag, {});
    assert.deepEqual(llamadas, [{
      url: "https://api.github.com/repos/dueño/pag/actions/workflows/noche.yml/dispatches",
      cuerpo: { ref: "main", inputs: { si_falta: "true" } },
    }]);
    llamadas.length = 0;
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-16T05:07:00Z") }, conPag, {}); // 6:07 en Madrid
    assert.deepEqual(llamadas.map((l) => l.url).sort(), [
      "https://api.github.com/repos/dueño/pag/actions/workflows/noche.yml/dispatches",
      "https://api.github.com/repos/dueño/repo/actions/workflows/actualizar.yml/dispatches",
    ]);
    llamadas.length = 0;
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-16T02:07:00Z") }, env, {}); // sin PAG_REPO
    assert.equal(llamadas.length, 0);
  } finally {
    globalThis.fetch = original;
  }
});

test("si falla un lanzamiento, el otro se hace igual y el fallo se ve", async () => {
  const original = globalThis.fetch;
  let ingesta = 0;
  globalThis.fetch = async (url) => {
    if (url.includes("noche.yml")) return new Response("Not Found", { status: 404 });
    ingesta++;
    return new Response(null, { status: 204 });
  };
  try {
    await assert.rejects(
      worker.scheduled({ scheduledTime: Date.parse("2026-11-16T05:07:00Z") }, { ...env, PAG_REPO: "dueño/pag" }, {}),
      /GitHub respondió 404 \(noche.yml\)/,
    );
    assert.equal(ingesta, 1);
  } finally {
    globalThis.fetch = original;
  }
});
