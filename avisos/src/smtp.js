// Cliente SMTP mínimo para enviar los avisos por el buzón de Piensa: TLS directo (puerto 465),
// AUTH PLAIN y texto plano en UTF-8. Una sesión sirve para todos los correos de una tanda, así que
// cada minuto se inicia sesión una sola vez.
//
// `conectar` es connect() de cloudflare:sockets; los tests pasan un servidor de mentira.

const ESPERA_MS = 15000;
const codificar = (texto) => new TextEncoder().encode(texto);

// El mensaje no lleva el texto del servidor, que suele incluir la dirección: los registros del worker
// no guardan datos personales.
export class ErrorSmtp extends Error {
  constructor(fase, codigo = null) {
    super(codigo ? `SMTP ${codigo} en ${fase}` : `SMTP sin respuesta en ${fase}`);
    this.fase = fase;
    this.codigo = codigo;
    // El servidor rechaza al destinatario: reintentar no sirve de nada.
    this.definitivo = fase === "RCPT" && codigo >= 500;
  }
}

const base64 = (bytes) => btoa(Array.from(bytes, (b) => String.fromCharCode(b)).join(""));

// Cabecera con tildes (RFC 2047): palabras codificadas cortas (30 bytes, 52 caracteres) para que
// quepan con el nombre de la cabecera en 78, sin partir ningún carácter, en líneas plegadas.
export function cabecera(texto) {
  const limpio = String(texto).replace(/[\x00-\x1f\x7f]+/g, " ").trim();
  if (/^[\x20-\x7e]*$/.test(limpio)) return limpio;
  const trozos = [];
  let actual = [];
  for (const caracter of limpio) {
    const bytes = codificar(caracter);
    if (actual.length + bytes.length > 30) {
      trozos.push(actual);
      actual = [];
    }
    actual.push(...bytes);
  }
  if (actual.length) trozos.push(actual);
  return trozos.map((b) => `=?UTF-8?B?${base64(b)}?=`).join("\r\n ");
}

// Quoted-printable (RFC 2045): legible, sin líneas de más de 76 caracteres y sin depender de 8BITMIME.
export function quotedPrintable(texto) {
  return String(texto).replace(/\r\n?/g, "\n").split("\n").map((linea) => {
    const bytes = codificar(linea);
    const lineas = [];
    let actual = "";
    bytes.forEach((b, i) => {
      const literal = (b >= 33 && b <= 126 && b !== 61) || ((b === 32 || b === 9) && i < bytes.length - 1);
      const t = literal ? String.fromCharCode(b) : `=${b.toString(16).toUpperCase().padStart(2, "0")}`;
      if (actual.length + t.length > 75) {
        lineas.push(`${actual}=`);
        actual = "";
      }
      actual += t;
    });
    lineas.push(actual);
    return lineas.join("\r\n");
  }).join("\r\n");
}

// Mensaje completo (cabeceras y cuerpo) con saltos CRLF.
export function componer({ de, nombre, para, asunto, texto, baja, fecha = new Date(), id = crypto.randomUUID() }) {
  const dominio = de.split("@").pop();
  const cabeceras = [
    `Date: ${fecha.toUTCString().replace("GMT", "+0000")}`,
    `From: ${nombre ? `${cabecera(nombre)} ` : ""}<${de}>`,
    `To: <${para}>`,
    `Subject: ${cabecera(asunto)}`,
    `Message-ID: <${id}@${dominio}>`,
    "MIME-Version: 1.0",
    "Content-Type: text/plain; charset=utf-8",
    "Content-Transfer-Encoding: quoted-printable",
    "Auto-Submitted: auto-generated", // sin respuestas automáticas («estoy de vacaciones»)
  ];
  if (baja) cabeceras.push(`List-Unsubscribe: <${baja}>`, "List-Unsubscribe-Post: List-Unsubscribe=One-Click");
  return `${cabeceras.join("\r\n")}\r\n\r\n${quotedPrintable(texto)}\r\n`;
}

export async function abrirSesion({ servidor, puerto = 465, usuario, clave, nombre = "localhost", espera = ESPERA_MS }, conectar) {
  const socket = conectar({ hostname: servidor, port: Number(puerto) }, { secureTransport: "on", allowHalfOpen: false });
  socket.opened?.catch?.(() => {}); // los fallos de conexión se ven al leer el saludo
  socket.closed?.catch?.(() => {});
  const lector = socket.readable.getReader();
  const escritor = socket.writable.getWriter();
  const decodificador = new TextDecoder();
  let pendiente = "";
  let rota = false;

  async function leer(fase) {
    let temporizador;
    const limite = new Promise((_, rechazar) => {
      temporizador = setTimeout(() => rechazar(new ErrorSmtp(fase)), espera);
    });
    try {
      return await Promise.race([lector.read(), limite]);
    } catch (error) {
      throw error instanceof ErrorSmtp ? error : new ErrorSmtp(fase);
    } finally {
      clearTimeout(temporizador);
    }
  }

  // Lee una respuesta completa (las de varias líneas usan «250-…» hasta la última «250 …»).
  async function respuesta(fase) {
    for (;;) {
      while (!pendiente.includes("\n")) {
        const { value, done } = await leer(fase);
        if (done) throw new ErrorSmtp(fase);
        pendiente += decodificador.decode(value, { stream: true });
      }
      const fin = pendiente.indexOf("\n");
      const linea = pendiente.slice(0, fin).replace(/\r$/, "");
      pendiente = pendiente.slice(fin + 1);
      if (!/^\d{3}([ -]|$)/.test(linea)) throw new ErrorSmtp(fase);
      if (linea[3] !== "-") return Number(linea.slice(0, 3));
    }
  }

  async function orden(texto, fase, esperado) {
    try {
      if (texto !== null) await escritor.write(codificar(`${texto}\r\n`));
    } catch {
      throw new ErrorSmtp(fase);
    }
    const codigo = await respuesta(fase);
    if (Math.floor(codigo / 100) !== esperado) throw new ErrorSmtp(fase, codigo);
  }

  const cerrar = async () => {
    if (!rota) {
      rota = true;
      try { await orden("QUIT", "QUIT", 2); } catch { /* ya da igual */ }
    }
    try { await socket.close(); } catch { /* ya cerrado */ }
  };

  try {
    await orden(null, "saludo", 2);
    await orden(`EHLO ${nombre}`, "EHLO", 2);
    await orden(`AUTH PLAIN ${base64(codificar(`\0${usuario}\0${clave}`))}`, "AUTH", 2);
  } catch (error) {
    rota = true;
    await cerrar();
    throw error;
  }

  return {
    get rota() { return rota; },
    cerrar,
    // Envía un mensaje ya compuesto. Si el servidor lo rechaza, la sesión sigue sirviendo (RSET);
    // si deja de responder, queda rota.
    async enviar(de, para, mensaje) {
      if (rota) throw new ErrorSmtp("sesión");
      try {
        await orden(`MAIL FROM:<${de}>`, "MAIL", 2);
        await orden(`RCPT TO:<${para}>`, "RCPT", 2);
        await orden("DATA", "DATA", 3);
        const datos = mensaje.replace(/\r?\n/g, "\r\n").replace(/^\./gm, ".."); // los puntos al inicio se doblan
        await orden(`${datos.endsWith("\r\n") ? datos : `${datos}\r\n`}.`, "fin de DATA", 2);
      } catch (error) {
        if (error.codigo) {
          try { await orden("RSET", "RSET", 2); } catch { rota = true; }
        } else rota = true;
        throw error;
      }
    },
  };
}
