// Lanza la ingesta en GitHub Actions (workflow_dispatch sin fuentes: lee todas) y la lectura nocturna del PAG
// (noche.yml del repo privado PAG_REPO, que va en un secreto para no publicar su nombre).

// Horario en hora de Madrid. El cron se dispara a :07 y a :37 (UTC) y esta función decide si toca:
// lunes a viernes, cada 30 min de 6:00 a 18:59 y a las 20 y las 22 h; sábado y domingo, cada 3 horas de las 8
// a las 20 h (8, 11, 14, 17 y 20); de madrugada, nunca. El minuto < 30 es la lectura «en punto». Responde a
// cuándo publican los organismos: casi todo entre semana de 9 a 16 h, algo hasta las 19 h y casi nada después
// ni en fin de semana (recuento de noviembre de 2026).
// La web lo publica en «Datos abiertos» (`SCHEDULE`, empleo/site.py): si cambia aquí, hay que cambiarlo allí.
export function toca(fecha) {
  const partes = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Madrid", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(fecha).map((p) => [p.type, p.value]),
  );
  const hora = Number(partes.hour);
  const enPunto = Number(partes.minute) < 30;
  const finDeSemana = partes.weekday === "Sat" || partes.weekday === "Sun";
  if (hora < 6) return false;
  if (finDeSemana) return enPunto && hora >= 8 && hora <= 20 && (hora - 8) % 3 === 0;
  if (hora < 19) return true;
  return enPunto && (hora === 20 || hora === 22);
}

// Lectura nocturna del PAG, en UTC: su robots.txt la permite de 01:00 a 06:45 GMT. Tres intentos (2:07, 3:07 y 5:07);
// noche.yml no hace nada si ya está la lectura del día.
export function tocaPag(fecha) {
  return [2, 3, 5].includes(fecha.getUTCHours()) && fecha.getUTCMinutes() < 30;
}

export async function lanzar(env, fetcher = fetch, { repo = env.REPO, workflow = env.WORKFLOW, ref = env.REF, inputs } = {}) {
  if (!env.GITHUB_TOKEN) throw new Error("Falta el secreto GITHUB_TOKEN");
  const url = `https://api.github.com/repos/${repo}/actions/workflows/${workflow}/dispatches`;
  const respuesta = await fetcher(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "empleo-cron",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(inputs ? { ref, inputs } : { ref }),
  });
  // GitHub responde 204 sin cuerpo; cualquier otra cosa es un fallo y debe verse en los registros.
  if (respuesta.status !== 204) {
    const texto = (await respuesta.text()).slice(0, 300);
    throw new Error(`GitHub respondió ${respuesta.status} (${workflow}): ${texto}`);
  }
}

export default {
  async scheduled(evento, env, _ctx) {
    const fecha = new Date(evento.scheduledTime);
    const lanzamientos = [];
    if (toca(fecha)) lanzamientos.push(lanzar(env));
    if (env.PAG_REPO && tocaPag(fecha)) {
      lanzamientos.push(lanzar(env, undefined, { repo: env.PAG_REPO, workflow: "noche.yml", ref: "main", inputs: { si_falta: "true" } }));
    }
    // Uno que falle no impide el otro; el fallo se ve en los registros del worker.
    const fallos = (await Promise.allSettled(lanzamientos)).filter((r) => r.status === "rejected").map((r) => r.reason);
    if (fallos.length) throw new AggregateError(fallos, fallos.map((f) => f.message).join("; "));
  },
};
