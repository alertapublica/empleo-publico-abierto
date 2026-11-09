// Lanza la ingesta horaria en GitHub Actions (workflow_dispatch sin fuentes: lee todas).

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
  async scheduled(_evento, env, _ctx) {
    await lanzar(env);
  },
};
