// Paleta personalizada y estado guardado de «Aa». Sin navegador: node --test tests/tema/tema.test.mjs
import test from "node:test";
import assert from "node:assert/strict";
import { createRequire } from "node:module";

const T = createRequire(import.meta.url)("../../empleo/assets/tema.js");

const MUESTRAS = [
  { fondo: "#ffffff", texto: "#222222", enlaces: "#0a5a3c", titulos: "#222222" },
  { fondo: "#000000", texto: "#ffffff", enlaces: "#00ffff", titulos: "#ffffff" },
  { fondo: "#f4ecd8", texto: "#3b2f1e", enlaces: "#7d3b1c", titulos: "#3b2f1e" },
  { fondo: "#1a1a2e", texto: "#e0e0ff", enlaces: "#ffd166", titulos: "#ffffff" },
  { fondo: "#ffff00", texto: "#000000", enlaces: "#0000cc", titulos: "#000000" },
  // lo elegido con poco contraste: lo derivado debe seguir siendo legible
  { fondo: "#808080", texto: "#8a8a8a", enlaces: "#909090", titulos: "#999999" },
];

test("lo derivado de la paleta personalizada cumple 4,5:1 (texto secundario y alerta) con cualquier elección", () => {
  for (const c of MUESTRAS) {
    const { vars } = T.paleta(c);
    for (const fondo of [vars.bg, vars.surface]) {
      assert.ok(T.contraste(vars.muted, fondo) >= 4.5, `muted sobre ${fondo} con ${JSON.stringify(c)}`);
    }
    assert.ok(T.contraste(vars.alert, vars.bg) >= 4.5, `alert con ${JSON.stringify(c)}`);
    assert.ok(T.contraste(vars.alert, vars["alert-bg"]) >= 4.5, `alert-bg con ${JSON.stringify(c)}`);
    assert.ok(T.contraste(vars["accent-ink"], vars.accent) >= 4.5, `accent-ink con ${JSON.stringify(c)}`);
  }
});

test("la paleta respeta lo elegido y escoge base clara u oscura según el fondo", () => {
  assert.equal(T.paleta(MUESTRAS[0]).base, "light");
  assert.equal(T.paleta(MUESTRAS[1]).base, "dark");
  const { vars } = T.paleta(MUESTRAS[3]);
  assert.equal(vars.bg, "#1a1a2e");
  assert.equal(vars.ink, "#e0e0ff");
  assert.equal(vars.accent, "#ffd166");
});

test("limpiar descarta valores inválidos y acota", () => {
  const s = T.limpiar({ tema: "x", fuente: "comic", fs: 9999, ancho: 1, just: "sí", colores: { fondo: "rojo" } });
  assert.deepEqual(s, { ...T.DEF, fs: 200, ancho: 480 });
  assert.equal(T.limpiar(null).tema, "auto");
  assert.equal(T.limpiar({ tema: "sepia" }).tema, "sepia");
});

test("los pasos de tamaño y ancho no salen de los límites", () => {
  assert.equal(T.paso(112.5, 1), 125);
  assert.equal(T.paso(112.5, -1), 100);
  assert.equal(T.paso(200, 1), 200);
  assert.equal(T.paso(75, -1), 75);
  assert.equal(T.anchoMas(960, 1), 1000);
  // Pasado el máximo, ancho completo; de ahí, «−» vuelve al máximo.
  assert.equal(T.anchoMas(1560, 1), 1600);
  assert.equal(T.anchoMas(1600, 1), "completo");
  assert.equal(T.anchoMas("completo", 1), "completo");
  assert.equal(T.anchoMas("completo", -1), 1600);
  assert.equal(T.limpiar({ ancho: "completo" }).ancho, "completo");
  assert.equal(T.limpiar({ ancho: "todo" }).ancho, T.DEF.ancho);
  assert.equal(T.anchoMas(480, -1), 480);
});

test("sin almacenamiento disponible carga los valores por defecto", () => {
  assert.deepEqual(T.cargar(), T.DEF); // en Node no hay localStorage: no debe lanzar
});
