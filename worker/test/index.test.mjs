import assert from "node:assert/strict";
import { test } from "node:test";
import { lanzar } from "../src/index.js";

const env = { GITHUB_TOKEN: "t", REPO: "dueño/repo", WORKFLOW: "actualizar.yml", REF: "main" };

test("lanza el workflow en la rama indicada", async () => {
  let llamada;
  await lanzar(env, async (url, opciones) => {
    llamada = { url, opciones };
    return new Response(null, { status: 204 });
  });
  assert.equal(llamada.url, "https://api.github.com/repos/dueño/repo/actions/workflows/actualizar.yml/dispatches");
  assert.equal(llamada.opciones.method, "POST");
  assert.equal(llamada.opciones.headers.Authorization, "Bearer t");
  assert.deepEqual(JSON.parse(llamada.opciones.body), { ref: "main" });
});

test("falla si GitHub no responde 204", async () => {
  await assert.rejects(
    lanzar(env, async () => new Response("Bad credentials", { status: 401 })),
    /GitHub respondió 401: Bad credentials/,
  );
});

test("falla sin token", async () => {
  await assert.rejects(lanzar({ ...env, GITHUB_TOKEN: "" }, async () => assert.fail("no debe llamar")), /GITHUB_TOKEN/);
});
