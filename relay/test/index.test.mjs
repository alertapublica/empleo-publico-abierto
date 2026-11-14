import assert from "node:assert/strict";
import { test } from "node:test";
import { atender, firmar, permitido } from "../src/index.js";

const CLAVE = "clave-de-prueba";
const env = { RELAY_CLAVE: CLAVE };
const PORTAL = "https://rrhhcandidato.tragsa.es:8443/psc/portalrh/x.GBL?Page=A";
const AHORA = 1_800_000_000_000;
const TS = String(AHORA / 1000);

async function peticion(url, { metodo = "GET", cuerpo = "", clave = CLAVE, ts = TS, cabeceras = {} } = {}) {
  const firma = await firmar(clave, ts, metodo, url, new TextEncoder().encode(cuerpo));
  return new Request(`https://relay.test/?url=${encodeURIComponent(url)}`, {
    method: metodo,
    headers: { "x-ts": ts, "x-firma": firma, ...cabeceras },
    body: metodo === "POST" ? cuerpo : undefined,
  });
}

function servidor(respuestas) {
  const vistas = [];
  const pedir = async (url, opciones) => {
    vistas.push({ url, ...opciones });
    return respuestas.shift();
  };
  return { vistas, pedir };
}

test("solo admite el origen del portal, con su puerto y sin credenciales", () => {
  assert.ok(permitido(PORTAL));
  assert.ok(!permitido("https://rrhhcandidato.tragsa.es/psc/portalrh/x.GBL"));
  assert.ok(!permitido("http://rrhhcandidato.tragsa.es:8443/"));
  assert.ok(!permitido("https://www.tragsa.es/"));
  assert.ok(!permitido("https://u:p@rrhhcandidato.tragsa.es:8443/"));
  assert.ok(!permitido("no es una url"));
});

test("sin firma válida, caducada o con otra clave no pide nada", async () => {
  const { vistas, pedir } = servidor([]);
  for (const req of [
    new Request(`https://relay.test/?url=${encodeURIComponent(PORTAL)}`),
    await peticion(PORTAL, { clave: "otra" }),
    await peticion(PORTAL, { ts: String(AHORA / 1000 - 121) }),
  ]) {
    assert.equal((await atender(req, env, pedir, AHORA)).status, 403);
  }
  assert.equal((await atender(await peticion(PORTAL), {}, pedir, AHORA)).status, 403);
  assert.equal(vistas.length, 0);
});

test("la firma cubre el cuerpo del POST", async () => {
  const { vistas, pedir } = servidor([]);
  const buena = await peticion(PORTAL, { metodo: "POST", cuerpo: "a=1" });
  const cambiada = new Request(buena.url, { method: "POST", headers: buena.headers, body: "a=2" });
  assert.equal((await atender(cambiada, env, pedir, AHORA)).status, 403);
  assert.equal(vistas.length, 0);
});

test("destino fuera de la lista: 400 sin pedir nada", async () => {
  const { vistas, pedir } = servidor([]);
  assert.equal((await atender(await peticion("https://www.tragsa.es/"), env, pedir, AHORA)).status, 400);
  assert.equal(vistas.length, 0);
});

test("solo GET y POST", async () => {
  const req = new Request("https://relay.test/?url=x", { method: "PUT", body: "x" });
  assert.equal((await atender(req, env, servidor([]).pedir, AHORA)).status, 405);
});

test("POST con cuerpo, cookies de entrada y Set-Cookie devueltas", async () => {
  const destino = new Response("<html>página 2</html>", {
    status: 200,
    headers: [["content-type", "text/html; charset=UTF-8"], ["set-cookie", "S=2; path=/; HttpOnly"]],
  });
  const { vistas, pedir } = servidor([destino]);
  const req = await peticion(PORTAL, {
    metodo: "POST",
    cuerpo: "ICAction=abajo",
    cabeceras: { "x-relay-cookie": "S=1; B=x", "content-type": "application/x-www-form-urlencoded", "user-agent": "ua" },
  });
  const r = await atender(req, env, pedir, AHORA);
  assert.equal(r.status, 200);
  assert.equal(await r.text(), "<html>página 2</html>");
  assert.equal(r.headers.get("content-type"), "text/html; charset=UTF-8");
  assert.deepEqual(JSON.parse(r.headers.get("x-relay-set-cookie")), ["S=2; path=/; HttpOnly"]);
  assert.ok(r.headers.has("x-relay-ms"));
  assert.equal(vistas[0].method, "POST");
  assert.equal(new TextDecoder().decode(vistas[0].body), "ICAction=abajo");
  assert.equal(vistas[0].headers.cookie, "S=1; B=x");
  assert.equal(vistas[0].headers["content-type"], "application/x-www-form-urlencoded");
  assert.equal(vistas[0].headers["user-agent"], "ua");
  assert.equal(vistas[0].redirect, "manual");
});

test("sigue la redirección con la cookie recibida y la devuelve", async () => {
  const { vistas, pedir } = servidor([
    new Response(null, { status: 302, headers: [["location", "/psc/portalrh/x.GBL?Page=B"], ["set-cookie", "SESION=abc; path=/"]] }),
    new Response("ok", { status: 200, headers: { "content-type": "text/html" } }),
  ]);
  const r = await atender(await peticion(PORTAL, { metodo: "POST", cuerpo: "a=1" }), env, pedir, AHORA);
  assert.equal(r.status, 200);
  assert.equal(vistas[1].url, "https://rrhhcandidato.tragsa.es:8443/psc/portalrh/x.GBL?Page=B");
  assert.equal(vistas[1].method, "GET");
  assert.equal(vistas[1].body, undefined);
  assert.equal(vistas[1].headers.cookie, "SESION=abc");
  assert.deepEqual(JSON.parse(r.headers.get("x-relay-set-cookie")), ["SESION=abc; path=/"]);
});

test("varias cookies, una cambiada en la redirección: todas, en orden y en una sola cabecera", async () => {
  const { vistas, pedir } = servidor([
    new Response(null, {
      status: 302,
      headers: [["location", "/psc/portalrh/x.GBL?Page=B"], ["set-cookie", "S=1; path=/; HttpOnly"],
                ["set-cookie", "B=x; Expires=Wed, 21 Oct 2026 07:28:00 GMT; path=/"]],
    }),
    new Response("ok", { status: 200, headers: [["content-type", "text/html"], ["set-cookie", "S=2; path=/"]] }),
  ]);
  const r = await atender(await peticion(PORTAL), env, pedir, AHORA);
  assert.equal(vistas[1].headers.cookie, "S=1; B=x");
  assert.deepEqual(JSON.parse(r.headers.get("x-relay-set-cookie")),
    ["S=1; path=/; HttpOnly", "B=x; Expires=Wed, 21 Oct 2026 07:28:00 GMT; path=/", "S=2; path=/"]);
});

test("sin Set-Cookie no hay cabecera de cookies", async () => {
  const { pedir } = servidor([new Response("ok", { status: 200 })]);
  const r = await atender(await peticion(PORTAL), env, pedir, AHORA);
  assert.equal(r.headers.has("x-relay-set-cookie"), false);
});

test("no sigue redirecciones fuera del origen ni sin fin", async () => {
  const fuera = servidor([new Response(null, { status: 302, headers: { location: "https://otro.example/" } })]);
  assert.equal((await atender(await peticion(PORTAL), env, fuera.pedir, AHORA)).status, 502);
  assert.equal(fuera.vistas.length, 1);
  const bucle = servidor(Array.from({ length: 10 }, () => new Response(null, { status: 302, headers: { location: PORTAL } })));
  const r = await atender(await peticion(PORTAL), env, bucle.pedir, AHORA);
  assert.equal(r.status, 502);
  assert.equal(bucle.vistas.length, 6);
});

test("fallo de red del destino: 502 marcado como red", async () => {
  const pedir = async () => {
    throw new Error("timed out");
  };
  const r = await atender(await peticion(PORTAL), env, pedir, AHORA);
  assert.equal(r.status, 502);
  assert.equal(r.headers.get("x-relay-error"), "red");
});
