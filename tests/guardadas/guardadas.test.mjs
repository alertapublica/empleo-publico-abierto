// Estado de «Guardadas» (localStorage). Sin navegador: node --test tests/guardadas/guardadas.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const G = createRequire(import.meta.url)("../../empleo/assets/guardadas.js");

const OFERTA = { t: "Técnico", u: "https://ejemplo.es/ofertas/tragsa-1/" };

test("limpiar conserva lo válido y descarta claves, títulos y enlaces que no lo son", () => {
  const s = G.limpiar({
    "o:tragsa-1": OFERTA,
    "p:0123abcd45": { t: "Proceso", u: "http://oficial.es/p" },
    "x:otra": OFERTA,                                   // tipo desconocido
    "o:<script>": OFERTA,                               // clave con caracteres raros
    "o:sin-enlace": { t: "Sin enlace" },
    "o:javascript": { t: "Malo", u: "javascript:alert(1)" },
    "o:titulo-raro": { t: 42, u: OFERTA.u },
  });
  assert.deepEqual(Object.keys(s).sort(), ["o:tragsa-1", "p:0123abcd45"]);
  assert.deepEqual(s["o:tragsa-1"], OFERTA);
});

test("limpiar tolera basura y recorta títulos largos", () => {
  for (const basura of [null, undefined, 3, "texto", [], [OFERTA]]) assert.deepEqual(G.limpiar(basura), {});
  assert.equal(G.limpiar({ "o:a": { t: "x".repeat(1000), u: OFERTA.u } })["o:a"].t.length, 300);
});

test("deTipo y fuera separan ofertas de procesos y detectan las que ya no están", () => {
  const s = { "o:a": OFERTA, "o:b": OFERTA, "p:c": OFERTA };
  assert.deepEqual(G.deTipo(s, "o"), ["o:a", "o:b"]);
  assert.deepEqual(G.deTipo(s, "p"), ["p:c"]);
  assert.deepEqual(G.fuera(s, "o", ["o:a", "o:z"]), ["o:b"]);
  assert.deepEqual(G.fuera(s, "p", []), ["p:c"]);
  assert.deepEqual(G.fuera({}, "o", ["o:a"]), []);
});

test("sin almacenamiento, cargar devuelve vacío y guardar no rompe", () => {
  assert.deepEqual(G.cargar(), {});
  assert.doesNotThrow(() => G.guardar({ "o:a": OFERTA }));
});

test("cargar y guardar ida y vuelta con un localStorage simulado", () => {
  const datos = {};
  globalThis.localStorage = { getItem: (k) => datos[k] ?? null, setItem: (k, v) => { datos[k] = v; } };
  try {
    G.guardar({ "o:a": OFERTA });
    assert.deepEqual(G.cargar(), { "o:a": OFERTA });
    datos[G.KEY] = "{roto";
    assert.deepEqual(G.cargar(), {});
  } finally {
    delete globalThis.localStorage;
  }
});
