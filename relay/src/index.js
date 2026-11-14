// Relay con salida en España para los portales que no responden a las IP de GitHub Actions (EE. UU.)
// y a los que no llega el relay de Piensa: el portal de candidatos de Tragsa da timeout desde
// Actions y solo atiende en el puerto 8443, que Piensa bloquea de salida. El placement de
// wrangler.jsonc lo ejecuta en Madrid aunque lo llame Actions desde EE. UU.
//
//   POST|GET /?url=<codificada>   con cabeceras x-ts y x-firma
//
// firma = HMAC-SHA256(RELAY_CLAVE, ts + "\n" + método + "\n" + url + "\n" + cuerpo); caduca a los
// VENTANA_S segundos. Solo a los orígenes de ORIGENES, también en las redirecciones, que sigue él
// mismo con las cookies de la sesión. Las cookies van en cabeceras propias porque las del destino
// no son de este dominio: x-relay-cookie (de entrada, como Cookie) y una x-relay-set-cookie de
// salida por cada Set-Cookie recibido.

export const ORIGENES = new Set(["https://rrhhcandidato.tragsa.es:8443"]);
const VENTANA_S = 120;
const MAX_SALTOS = 5;
const ESPERA_MS = 25000;
const PASAN = ["user-agent", "accept", "accept-language", "content-type"];

const texto = new TextEncoder();

export async function firmar(clave, ts, metodo, url, cuerpo) {
  const k = await crypto.subtle.importKey("raw", texto.encode(clave), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const cabeza = texto.encode(`${ts}\n${metodo}\n${url}\n`);
  const datos = new Uint8Array(cabeza.length + cuerpo.length);
  datos.set(cabeza);
  datos.set(cuerpo, cabeza.length);
  const firma = new Uint8Array(await crypto.subtle.sign("HMAC", k, datos));
  return [...firma].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function iguales(a, b) {
  if (a.length !== b.length) return false;
  let distinto = 0;
  for (let i = 0; i < a.length; i++) distinto |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return distinto === 0;
}

export function permitido(url) {
  try {
    const u = new URL(url);
    return ORIGENES.has(u.origin) && !u.username && !u.password;
  } catch {
    return false;
  }
}

function leerCookies(valor, tarro) {
  for (const par of (valor || "").split(";")) {
    const i = par.indexOf("=");
    if (i > 0) tarro.set(par.slice(0, i).trim(), par.slice(i + 1).trim());
  }
}

function cabecerasCookie(tarro) {
  return [...tarro].map(([n, v]) => `${n}=${v}`).join("; ");
}

function respuesta(estado, mensaje, extra = {}) {
  return new Response(mensaje + "\n", { status: estado, headers: { "Content-Type": "text/plain; charset=utf-8", ...extra } });
}

export async function atender(req, env, pedir = fetch, ahora = Date.now()) {
  const metodo = req.method;
  if (metodo !== "GET" && metodo !== "POST") return respuesta(405, "solo GET y POST");
  const url = new URL(req.url).searchParams.get("url") || "";
  const ts = req.headers.get("x-ts") || "";
  const firma = (req.headers.get("x-firma") || "").toLowerCase();
  const cuerpo = metodo === "POST" ? new Uint8Array(await req.arrayBuffer()) : new Uint8Array();
  const clave = env.RELAY_CLAVE || "";
  if (!clave || !/^\d{1,12}$/.test(ts) || Math.abs(ahora / 1000 - Number(ts)) > VENTANA_S
      || !iguales(await firmar(clave, ts, metodo, url, cuerpo), firma)) {
    return respuesta(403, "no");
  }
  if (!permitido(url)) return respuesta(400, "destino no permitido");

  const t0 = Date.now();
  const tarro = new Map();
  leerCookies(req.headers.get("x-relay-cookie"), tarro);
  const recibidas = [];
  let destino = url, verbo = metodo, datos = metodo === "POST" ? cuerpo : undefined;
  for (let salto = 0; ; salto++) {
    const cabeceras = {};
    for (const nombre of PASAN) {
      const valor = req.headers.get(nombre);
      if (valor && (datos || nombre !== "content-type")) cabeceras[nombre] = valor;
    }
    if (tarro.size) cabeceras.cookie = cabecerasCookie(tarro);
    let r;
    try {
      r = await pedir(destino, { method: verbo, headers: cabeceras, body: datos, redirect: "manual", signal: AbortSignal.timeout(ESPERA_MS) });
    } catch (error) {
      return respuesta(502, String(error), { "x-relay-error": "red" });
    }
    for (const linea of r.headers.getSetCookie()) {
      recibidas.push(linea);
      leerCookies(linea.split(";")[0], tarro);
    }
    const location = r.headers.get("location");
    if (![301, 302, 303, 307, 308].includes(r.status)) {
      const salida = new Headers({ "Content-Type": r.headers.get("content-type") || "application/octet-stream", "x-relay-ms": String(Date.now() - t0) });
      for (const linea of recibidas) salida.append("x-relay-set-cookie", linea);
      return new Response(r.body, { status: r.status, headers: salida });
    }
    if (!location) return respuesta(502, "redirección sin destino", { "x-relay-error": "red" });
    if (salto >= MAX_SALTOS) return respuesta(502, "demasiadas redirecciones", { "x-relay-error": "red" });
    destino = new URL(location, destino).href;
    if (!permitido(destino)) return respuesta(502, "redirección fuera del ámbito del relay", { "x-relay-error": "red" });
    if (r.status !== 307 && r.status !== 308) {
      verbo = "GET";
      datos = undefined;
    }
  }
}

export default {
  fetch: (req, env) => atender(req, env),
};
