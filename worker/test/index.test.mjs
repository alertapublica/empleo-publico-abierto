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

test("entre semana: cada 30 min de 6:00 a 15:59, luego cada hora, y nada de madrugada", () => {
  assert.equal(lanza("2026-11-10T05:07:00Z"), true); // martes 6:07
  assert.equal(lanza("2026-11-10T05:37:00Z"), true); // martes 6:37
  assert.equal(lanza("2026-11-10T14:37:00Z"), true); // martes 15:37
  assert.equal(lanza("2026-11-10T15:07:00Z"), true); // martes 16:07
  assert.equal(lanza("2026-11-10T15:37:00Z"), false); // martes 16:37
  assert.equal(lanza("2026-11-10T22:07:00Z"), true); // martes 23:07
  assert.equal(lanza("2026-11-10T22:37:00Z"), false); // martes 23:37
  assert.equal(lanza("2026-11-10T04:37:00Z"), false); // martes 5:37
  assert.equal(lanza("2026-11-10T23:07:00Z"), false); // miércoles 0:07
});

test("fin de semana: cada hora hasta las 16:00 y solo a las 19 y las 22 h después", () => {
  assert.equal(lanza("2026-11-14T05:07:00Z"), true); // sábado 6:07
  assert.equal(lanza("2026-11-14T05:37:00Z"), false); // sábado 6:37
  assert.equal(lanza("2026-11-14T14:07:00Z"), true); // sábado 15:07
  assert.equal(lanza("2026-11-14T15:07:00Z"), false); // sábado 16:07
  assert.equal(lanza("2026-11-14T18:07:00Z"), true); // sábado 19:07
  assert.equal(lanza("2026-11-15T21:07:00Z"), true); // domingo 22:07
  assert.equal(lanza("2026-11-15T20:07:00Z"), false); // domingo 21:07
  assert.equal(lanza("2026-11-15T04:07:00Z"), false); // domingo 5:07
});

test("sigue la hora de Madrid en verano", () => {
  assert.equal(lanza("2026-07-07T04:07:00Z"), true); // martes 6:07 (+2)
  assert.equal(lanza("2026-07-07T03:37:00Z"), false); // martes 5:37
  assert.equal(lanza("2026-07-11T17:07:00Z"), true); // sábado 19:07
  assert.equal(lanza("2026-07-11T18:07:00Z"), false); // sábado 20:07
  // El domingo 29 de marzo de 2026 se adelanta la hora: 6:07 ya son las 4:07 UTC.
  assert.equal(lanza("2026-03-29T04:07:00Z"), true);
  assert.equal(lanza("2026-03-29T05:07:00Z"), true); // 7:07
  assert.equal(lanza("2026-03-29T03:07:00Z"), false); // 5:07
});

test("scheduled lanza el workflow solo cuando toca", async () => {
  const original = globalThis.fetch;
  let llamadas = 0;
  globalThis.fetch = async () => { llamadas++; return new Response(null, { status: 204 }); };
  try {
    await worker.scheduled({ scheduledTime: Date.parse("2026-11-10T15:37:00Z") }, env, {});
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
