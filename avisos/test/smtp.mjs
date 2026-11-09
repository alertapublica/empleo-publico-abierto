// Servidor SMTP de mentira con la interfaz de connect() de cloudflare:sockets: guarda las órdenes
// y los mensajes, y responde lo que se le diga (por defecto, todo bien).

const enc = new TextEncoder();
const dec = new TextDecoder();

const RESPUESTAS = {
  EHLO: "250-falso\r\n250-8BITMIME\r\n250 AUTH PLAIN LOGIN",
  AUTH: "235 2.7.0 OK",
  MAIL: "250 2.1.0 OK",
  RCPT: "250 2.1.5 OK",
  DATA: "354 Adelante",
  FIN: "250 2.0.0 En cola",
  RSET: "250 2.0.0 OK",
  QUIT: "221 2.0.0 Adiós",
};

// respuestas: { ORDEN: "texto" | (linea, sesion) => "texto" | null }. null = no contestar nunca.
export function smtpFalso(respuestas = {}) {
  const sesiones = [];
  const conectar = (direccion, opciones) => {
    const s = { direccion, opciones, ordenes: [], mensajes: [], cerrada: false };
    sesiones.push(s);
    let salida;
    let entrada = "";
    let enDatos = false;
    const responder = (orden, linea) => {
      const r = orden in respuestas ? respuestas[orden] : RESPUESTAS[orden] || "500 No entiendo";
      const texto = typeof r === "function" ? r(linea, s) : r;
      if (texto !== null && !s.cerrada) salida.enqueue(enc.encode(`${texto}\r\n`));
      if (orden === "QUIT") cerrar();
      return texto;
    };
    const cerrar = () => {
      if (s.cerrada) return;
      s.cerrada = true;
      try { salida.close(); } catch { /* ya cerrado */ }
    };
    const readable = new ReadableStream({ start(c) { salida = c; } });
    const writable = new WritableStream({
      write(trozo) {
        entrada += dec.decode(trozo, { stream: true });
        for (;;) {
          if (enDatos) {
            const fin = entrada.indexOf("\r\n.\r\n");
            if (fin < 0) return;
            // Deshace el doblado de puntos, como un servidor de verdad.
            s.mensajes.push(entrada.slice(0, fin + 2).replace(/^\.\./gm, "."));
            entrada = entrada.slice(fin + 5);
            enDatos = false;
            responder("FIN", "");
            continue;
          }
          const fin = entrada.indexOf("\r\n");
          if (fin < 0) return;
          const linea = entrada.slice(0, fin);
          entrada = entrada.slice(fin + 2);
          s.ordenes.push(linea);
          const orden = linea.split(/[ :]/)[0].toUpperCase();
          const texto = responder(orden, linea);
          if (orden === "DATA" && String(texto).startsWith("354")) enDatos = true;
        }
      },
    });
    queueMicrotask(() => responder("SALUDO", ""));
    return { readable, writable, opened: Promise.resolve(), closed: Promise.resolve(), close: async () => cerrar() };
  };
  respuestas.SALUDO ??= "220 falso ESMTP";
  return { conectar, sesiones };
}

// Decodifica un mensaje compuesto por src/smtp.js: cabeceras (con palabras codificadas) y cuerpo.
export function leerMensaje(crudo) {
  const [cabeza, ...resto] = crudo.split("\r\n\r\n");
  const cabeceras = {};
  for (const linea of cabeza.replace(/\r\n /g, " ").split("\r\n")) {
    const i = linea.indexOf(":");
    cabeceras[linea.slice(0, i)] = linea.slice(i + 2).replace(/\?=\s+=\?/g, "?==?").replace(/=\?UTF-8\?B\?([^?]+)\?=/g, (_, b) => {
      const bytes = Uint8Array.from(atob(b), (c) => c.charCodeAt(0));
      return dec.decode(bytes);
    }).trim();
  }
  const qp = resto.join("\r\n\r\n").replace(/=\r\n/g, "");
  const bytes = [];
  for (let i = 0; i < qp.length; i++) {
    if (qp[i] === "=") {
      bytes.push(parseInt(qp.slice(i + 1, i + 3), 16));
      i += 2;
    } else bytes.push(qp.charCodeAt(i));
  }
  return { cabeceras, texto: dec.decode(Uint8Array.from(bytes)).replace(/\r\n/g, "\n") };
}
