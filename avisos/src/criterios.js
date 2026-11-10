// Criterios de un aviso y si una novedad de api/novedades.json los cumple.
//
// Criterios (JSON en la tabla avisos):
//   palabras:    comienzos de palabra en el título, sin el código interno («ingenier» → Ingeniero/a, Ingeniera)
//   areas:       ids de área (api/listas.json)
//   teletrabajo: solo ofertas cuya ficha menciona el teletrabajo (las que no traen texto no se
//                pueden comprobar y no se avisan)
//   ccaa:        códigos INE de comunidad; sin_ccaa: incluir también las ofertas y los comunicados sin
//                comunidad concreta (casi todos los procesos son estatales o no dicen dónde)
//   organismos:  ids de organismo
//   comunicados: incluir los comunicados de procesos selectivos de esos organismos
// Dentro de un mismo criterio basta con que coincida uno; entre criterios, tienen que coincidir todos.
// Un criterio vacío no filtra.

export const MAX_AVISOS = 10;
export const MAX_PALABRAS = 10;

// Minúsculas, sin tildes y sin signos: «Ingeniero/a (Lugo)» → «ingeniero a lugo».
export function normalizar(texto) {
  return (texto || "")
    .normalize("NFD")
    .replace(/\p{M}/gu, "")
    .toLowerCase()
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

// ¿Alguna palabra del texto empieza por `clave`? Las claves de varias palabras van seguidas.
export function empiezaPalabra(texto, clave) {
  const t = normalizar(texto);
  const c = normalizar(clave);
  return c !== "" && ` ${t}`.includes(` ${c}`);
}

const lista = (valor) => (Array.isArray(valor) ? valor : []);

export function coincide(criterios, novedad) {
  const palabras = lista(criterios.palabras);
  const organismos = lista(criterios.organismos);
  if (organismos.length && !organismos.includes(novedad.organismo)) return false;
  const ccaa = lista(criterios.ccaa);
  if (ccaa.length && !(novedad.ccaa ? ccaa.includes(novedad.ccaa) : criterios.sin_ccaa !== false)) return false;

  if (novedad.tipo === "comunicado") {
    if (!criterios.comunicados) return false;
    const texto = `${novedad.proceso || ""} ${novedad.titulo || ""}`;
    return !palabras.length || palabras.some((p) => empiezaPalabra(texto, p));
  }
  if (novedad.tipo !== "oferta") return false;

  const areas = lista(criterios.areas);
  if (areas.length && !lista(novedad.areas).some((a) => areas.includes(a))) return false;
  if (criterios.teletrabajo && typeof novedad.teletrabajo !== "string") return false;
  return !palabras.length || palabras.some((p) => empiezaPalabra(novedad.titulo, p));
}

// Deja solo claves válidas según api/listas.json; null si el aviso no es válido.
export function limpiar(criterios, listas) {
  const validos = (valores, permitidos) => [...new Set(lista(valores).filter((v) => permitidos.has(v)))];
  const palabras = [...new Set(lista(criterios.palabras).map((p) => normalizar(String(p))).filter(Boolean))];
  if (palabras.length > MAX_PALABRAS || palabras.some((p) => p.length > 60)) return null;
  const limpio = {
    palabras,
    areas: validos(criterios.areas, new Set(listas.areas.map((a) => a.id))),
    ccaa: validos(criterios.ccaa, new Set(listas.comunidades.map((c) => c.ccaa))),
    organismos: validos(criterios.organismos, new Set(listas.organismos.map((o) => o.id))),
  };
  limpio.sin_ccaa = limpio.ccaa.length ? criterios.sin_ccaa !== false : true;
  limpio.teletrabajo = criterios.teletrabajo === true;
  limpio.comunicados = limpio.organismos.length ? Boolean(criterios.comunicados) : false;
  return limpio;
}

// Texto legible de un aviso: «analista · Galicia (y sin comunidad concreta) · Grupo Tragsa».
export function describir(criterios, listas) {
  const nombre = (items, clave, valores) =>
    valores.map((v) => items.find((i) => i[clave] === v)?.nombre || v).join(", ");
  const partes = [];
  if (lista(criterios.palabras).length) partes.push(`«${criterios.palabras.join("», «")}»`);
  if (lista(criterios.areas).length) partes.push(nombre(listas.areas, "id", criterios.areas));
  if (criterios.teletrabajo) partes.push("que mencionen teletrabajo");
  if (lista(criterios.ccaa).length) {
    partes.push(nombre(listas.comunidades, "ccaa", criterios.ccaa)
      + (criterios.sin_ccaa === false ? "" : " (y sin comunidad concreta)"));
  }
  if (lista(criterios.organismos).length) {
    partes.push(nombre(listas.organismos, "id", criterios.organismos)
      + (criterios.comunicados ? " (con comunicados de procesos)" : ""));
  }
  return partes.join(" · ") || "Todas las ofertas nuevas";
}

// Otros nombres de comunidad con que la gente las escribe.
const ALIAS_CCAA = {
  baleares: "04", "islas baleares": "04", euskadi: "16", catalunya: "09", "pais valencia": "10",
  valencia: "10", navarra: "15", madrid: "13", murcia: "14", rioja: "17",
};
const VACIAS = new Set(["comunidad", "de", "la", "el", "y", "region", "foral", "illes", "comunitat", "del"]);

// Reconoce cada término escrito por la persona («galicia, madrid») en una lista de opciones.
// Devuelve { ok: [ids], dudas: [{termino, opciones}], fallos: [terminos] }.
export function reconocer(texto, opciones, alias = {}) {
  const resultado = { ok: [], dudas: [], fallos: [] };
  const terminos = String(texto).split(/[,;\n]+/).map((t) => t.trim()).filter(Boolean);
  for (const termino of terminos) {
    const n = normalizar(termino);
    if (!n || VACIAS.has(n)) continue;
    const exactos = opciones.filter((o) => normalizar(o.id) === n || normalizar(o.nombre) === n);
    const candidatos = alias[n] ? opciones.filter((o) => o.id === alias[n])
      : exactos.length ? exactos
        : opciones.filter((o) => empiezaPalabra(o.nombre, n) || empiezaPalabra(o.id, n));
    if (candidatos.length === 1) resultado.ok.push(candidatos[0].id);
    else if (candidatos.length > 1) resultado.dudas.push({ termino, opciones: candidatos.map((o) => o.nombre) });
    else resultado.fallos.push(termino);
  }
  resultado.ok = [...new Set(resultado.ok)];
  return resultado;
}

export const reconocerComunidades = (texto, listas) =>
  reconocer(texto, listas.comunidades.map((c) => ({ id: c.ccaa, nombre: c.nombre })), ALIAS_CCAA);

export const reconocerOrganismos = (texto, listas) => reconocer(texto, listas.organismos);
