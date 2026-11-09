// D1 de mentira sobre node:sqlite, con la migración real: lo justo para los tests.
import { readFileSync, readdirSync } from "node:fs";
import { DatabaseSync } from "node:sqlite";

class Sentencia {
  constructor(db, sql, params = []) {
    Object.assign(this, { db, sql, params });
  }
  bind(...params) {
    return new Sentencia(this.db, this.sql, params.map((p) => (p === undefined ? null : p)));
  }
  _p() {
    return this.db.prepare(this.sql);
  }
  async first(columna) {
    const fila = this._p().get(...this.params);
    if (!fila) return null;
    return columna ? fila[columna] : { ...fila };
  }
  async all() {
    return { results: this._p().all(...this.params).map((f) => ({ ...f })) };
  }
  async run() {
    const r = this._p().run(...this.params);
    return { meta: { changes: Number(r.changes), last_row_id: Number(r.lastInsertRowid) } };
  }
}

export function d1() {
  const db = new DatabaseSync(":memory:");
  db.exec("PRAGMA foreign_keys = ON");
  const carpeta = new URL("../migrations/", import.meta.url);
  for (const f of readdirSync(carpeta).sort()) db.exec(readFileSync(new URL(f, carpeta), "utf8"));
  return {
    sqlite: db,
    prepare: (sql) => new Sentencia(db, sql),
    async batch(sentencias) {
      db.exec("BEGIN");
      try {
        const r = [];
        for (const s of sentencias) r.push(/^\s*select/i.test(s.sql) ? await s.all() : await s.run());
        db.exec("COMMIT");
        return r;
      } catch (error) {
        db.exec("ROLLBACK");
        throw error;
      }
    },
  };
}

export const LISTAS = {
  comunidades: [
    { ccaa: "03", nombre: "Asturias" }, { ccaa: "07", nombre: "Castilla y León" },
    { ccaa: "08", nombre: "Castilla-La Mancha" }, { ccaa: "09", nombre: "Cataluña" },
    { ccaa: "10", nombre: "Comunitat Valenciana" }, { ccaa: "12", nombre: "Galicia" },
    { ccaa: "13", nombre: "Comunidad de Madrid" },
  ],
  organismos: [
    { id: "tragsa", nombre: "Grupo Tragsa", grupo: "sepi" }, { id: "correos", nombre: "Grupo Correos", grupo: "sepi" },
    { id: "isdefe", nombre: "ISDEFE", grupo: "estatal" }, { id: "ciqus", nombre: "CiQUS (USC)", grupo: "investigacion" },
    { id: "cimus", nombre: "CiMUS (USC)", grupo: "investigacion" },
  ],
  areas: [{ id: "tic", nombre: "Informática y telecomunicaciones" }, { id: "admin", nombre: "Administración y gestión" }],
};

export const oferta = (id, extra = {}) => ({
  id: `tragsa:${id}/new/2026-11-09T06:00:00+00:00`, fecha: "2026-11-09T06:00:00+00:00", tipo: "oferta",
  evento: "new", organismo: "tragsa", ccaa: "12", areas: ["tic"], titulo: `Analista ${id}`,
  detalle: "Tragsatec · Lugo", url: `https://example.org/ofertas/tragsa-${id}/`, ...extra,
});

// Telegram de mentira: guarda las llamadas y responde ok.
export function telegramFalso(respuesta = () => ({ ok: true })) {
  const llamadas = [];
  const fetcher = async (url, opciones) => {
    const metodo = url.split("/").pop();
    const datos = JSON.parse(opciones.body);
    llamadas.push({ metodo, datos });
    const r = respuesta(metodo, datos);
    return Response.json(r, { status: r.status || (r.ok ? 200 : 400) });
  };
  return { llamadas, fetcher, mensajes: () => llamadas.filter((l) => l.metodo === "sendMessage").map((l) => l.datos) };
}
