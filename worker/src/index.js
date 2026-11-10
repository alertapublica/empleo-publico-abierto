// Lanza la ingesta en GitHub Actions (workflow_dispatch sin fuentes: lee todas).

// Horario en hora de Madrid. El cron se dispara a :07 y a :37 (UTC) y esta función decide si toca:
// lunes a viernes, cada 30 min de 6:00 a 15:59 y cada hora hasta las 23:59; sábado y domingo, cada hora
// de 6:00 a 15:59 y a las 19 y las 22 h; de madrugada, nunca. El minuto < 30 es la lectura «en punto».
export function toca(fecha) {
  const partes = Object.fromEntries(
    new Intl.DateTimeFormat("en-GB", { timeZone: "Europe/Madrid", weekday: "short", hour: "2-digit", minute: "2-digit", hourCycle: "h23" })
      .formatToParts(fecha).map((p) => [p.type, p.value]),
  );
  const hora = Number(partes.hour);
  const enPunto = Number(partes.minute) < 30;
  const finDeSemana = partes.weekday === "Sat" || partes.weekday === "Sun";
  if (hora < 6) return false;
  if (hora < 16) return finDeSemana ? enPunto : true;
  return enPunto && (!finDeSemana || hora === 19 || hora === 22);
}

export async function lanzar(env, fetcher = fetch) {
  if (!env.GITHUB_TOKEN) throw new Error("Falta el secreto GITHUB_TOKEN");
  const url = `https://api.github.com/repos/${env.REPO}/actions/workflows/${env.WORKFLOW}/dispatches`;
  const respuesta = await fetcher(url, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "empleo-cron",
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ ref: env.REF }),
  });
  // GitHub responde 204 sin cuerpo; cualquier otra cosa es un fallo y debe verse en los registros.
  if (respuesta.status !== 204) {
    const texto = (await respuesta.text()).slice(0, 300);
    throw new Error(`GitHub respondió ${respuesta.status}: ${texto}`);
  }
}

export default {
  async scheduled(evento, env, _ctx) {
    if (toca(new Date(evento.scheduledTime))) await lanzar(env);
  },
};
