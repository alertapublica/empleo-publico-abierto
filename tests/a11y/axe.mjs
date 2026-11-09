// Audita la web generada con axe: todos los temas de «Aa», panel y menú abiertos, escritorio y móvil.
import { createServer } from "node:http";
import { readFile, readdir } from "node:fs/promises";
import { extname, join, normalize } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { chromium } from "playwright";

const ROOT = join(import.meta.dirname, "..", "..", "_site");
const TYPES = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml" };

const server = createServer(async (request, response) => {
  const path = normalize(decodeURIComponent(new URL(request.url, "http://x").pathname));
  const file = join(ROOT, path, path.endsWith("/") ? "index.html" : "");
  try {
    const body = await readFile(file);
    response.writeHead(200, { "content-type": `${TYPES[extname(file)] ?? "text/plain"}; charset=utf-8` });
    response.end(body);
  } catch {
    response.writeHead(404).end();
  }
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const base = `http://127.0.0.1:${server.address().port}/`;

const offers = await readdir(join(ROOT, "ofertas"));
const paths = ["", "organismos/", "organismos/tragsa/", "anuncios/", "historico/", "avisos/", "acerca/", "accesibilidad/", "datos/", `ofertas/${offers[0]}/`];
const browser = await chromium.launch(
  process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH, args: ["--no-sandbox"] } : {},
);

let problems = 0;
let checks = 0;
for (const colorScheme of ["light", "dark"]) {
  for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 740 }]) {
    const context = await browser.newContext({ colorScheme, viewport, locale: "es-ES" });
    for (const path of paths) {
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
      await page.goto(base + path, { waitUntil: "load" });
      const { violations } = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
        .analyze();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth > document.documentElement.clientWidth,
      );
      checks += 1;
      for (const violation of violations) {
        problems += 1;
        console.log(`[${colorScheme} ${viewport.width}] /${path} ${violation.id}: ${violation.help}`);
        console.log(`   ${violation.nodes[0].html.slice(0, 180)}`);
      }
      if (overflow) { problems += 1; console.log(`[${viewport.width}] /${path} desbordamiento horizontal`); }
      if (errors.length) { problems += 1; console.log(`/${path} errores de consola: ${errors.join(" | ")}`); }
      await page.close();
    }
    await context.close();
  }
}

// Temas de «Aa», panel abierto y menú móvil: mismas reglas de axe y sin desbordamiento.
const CLAVE = "empleo-ajustes-v1";
const PROPIOS = { fondo: "#1a1a2e", texto: "#e0e0ff", enlaces: "#ffd166", titulos: "#ffffff" };
async function auditar(page, etiqueta) {
  const { violations } = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"])
    .analyze();
  checks += 1;
  for (const violation of violations) {
    problems += 1;
    console.log(`[${etiqueta}] ${violation.id}: ${violation.help}`);
    console.log(`   ${violation.nodes[0].html.slice(0, 180)}`);
  }
  if (await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth)) {
    problems += 1;
    console.log(`[${etiqueta}] desbordamiento horizontal`);
  }
}
for (const tema of ["light", "sepia", "dark", "contrast", "custom"]) {
  for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 740 }]) {
    const context = await browser.newContext({ viewport, locale: "es-ES" });
    await context.addInitScript(([clave, valor]) => localStorage.setItem(clave, valor), [
      CLAVE, JSON.stringify({ tema, colores: PROPIOS, fs: 125 }),
    ]);
    for (const path of ["", `ofertas/${offers[0]}/`]) {
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (error) => errors.push(error.message));
      page.on("console", (message) => message.type() === "error" && errors.push(message.text()));
      await page.goto(base + path, { waitUntil: "load" });
      await auditar(page, `tema ${tema} ${viewport.width} /${path}`);
      if (path === "") {
        await page.locator("#btn-aa").click();
        await page.waitForSelector("#ajustes[open]");
        await auditar(page, `panel Aa, tema ${tema} ${viewport.width}`);
      }
      if (errors.length) { problems += 1; console.log(`tema ${tema} /${path} errores de consola: ${errors.join(" | ")}`); }
      await page.close();
    }
    await context.close();
  }
}

// Menú plegable en móvil: cerrado por defecto, se abre con el botón y deja ver la navegación.
{
  const context = await browser.newContext({ viewport: { width: 360, height: 740 }, locale: "es-ES" });
  const page = await context.newPage();
  await page.goto(base);
  const cerrado = !(await page.locator("#nav-principal").isVisible());
  await page.locator("#btn-menu").click();
  const abierto = await page.locator("#nav-principal").isVisible();
  if (!cerrado || !abierto || (await page.locator("#btn-menu").getAttribute("aria-expanded")) !== "true") {
    problems += 1;
    console.log(`Menú móvil incorrecto: cerrado=${cerrado} abierto=${abierto}`);
  }
  await auditar(page, "menú móvil abierto");
  await context.close();
}

// Los ajustes cambian la página, se recuerdan al recargar y se restablecen.
{
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "es-ES" });
  const page = await context.newPage();
  await page.goto(base);
  const letra = () => page.evaluate(() => parseFloat(getComputedStyle(document.documentElement).fontSize));
  const antes = await letra();
  await page.locator("#btn-aa").click();
  await page.locator("#fs-mas").click();
  await page.locator("#tema-dark").check();
  await page.locator("#ajustes-cerrar").click();
  await page.reload();
  const tema = await page.evaluate(() => document.documentElement.dataset.theme);
  if (!((await letra()) > antes) || tema !== "dark") {
    problems += 1;
    console.log(`Los ajustes no se aplican o no se recuerdan: letra ${antes}→${await letra()}, tema ${tema}`);
  }
  await page.locator("#btn-aa").click();
  await page.locator("#ajustes-reset").click();
  const restablecido = await page.evaluate(() => document.documentElement.hasAttribute("data-theme"));
  if (restablecido || (await letra()) !== antes) {
    problems += 1;
    console.log("Restablecer apariencia no devuelve los valores por defecto");
  }
  await context.close();
}

// En móvil el botón de apariencia se queda en «Aa», pero conserva su nombre y abre el diálogo.
{
  const context = await browser.newContext({ viewport: { width: 360, height: 740 }, locale: "es-ES" });
  const page = await context.newPage();
  await page.goto(base);
  const boton = page.getByRole("button", { name: "Apariencia" });
  const visible = await boton.isVisible();
  if (visible) await boton.click();
  const abierto = await page.locator("#ajustes").isVisible();
  if (abierto) await auditar(page, "apariencia en móvil");
  if (!visible || !abierto) {
    problems += 1;
    console.log(`Botón de apariencia en móvil incorrecto: visible=${visible} diálogo=${abierto}`);
  }
  await context.close();
}

// «Guardar»: la pastilla aparece al guardar, filtra, recuerda al recargar y avisa de las ya cerradas.
for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 740 }]) {
  const context = await browser.newContext({ viewport, locale: "es-ES" });
  await context.addInitScript(() => {
    if (!sessionStorage.getItem("sembrado")) {
      sessionStorage.setItem("sembrado", "1");
      localStorage.setItem("empleo-guardadas-v1", JSON.stringify({
        "o:cerrada-de-prueba": { t: "Oferta ya cerrada", u: "https://ejemplo.es/cerrada/" },
      }));
    }
  });
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(base);
  const visibleAntes = await page.locator("#pastilla-guardadas").isVisible();
  await page.locator("#lista-ofertas > li button.guardar").first().click();
  const pulsado = await page.locator("#lista-ofertas > li button.guardar").first().getAttribute("aria-pressed");
  await page.locator("#pastilla-guardadas").click();
  await page.waitForFunction(() => document.querySelectorAll("#lista-ofertas > li:not([hidden])").length === 1);
  const nota = await page.locator("#guardadas-cerradas:visible").count();
  await auditar(page, `guardadas en la portada ${viewport.width}`);
  await page.reload();
  const tras = await page.evaluate(() => [
    location.search, document.querySelectorAll("#lista-ofertas > li:not([hidden])").length,
    document.getElementById("n-guardadas").textContent,
  ]);
  // «Quitar filtros» también quita la nota; al volver a marcar la pastilla, vuelve.
  await page.locator('button[type="reset"]').first().click();
  await page.waitForFunction(() => !location.search);
  const trasQuitarFiltros = await page.locator("#guardadas-cerradas:visible").count() === 0;
  await page.locator("#pastilla-guardadas").click();
  const enAcciones = await page.locator("#lista-ofertas > li .tarjeta-acciones button.guardar").count() > 0;
  await page.locator("#guardadas-cerradas button").click();
  const quitada = await page.locator("#guardadas-cerradas:visible").count() === 0
    && (await page.evaluate(() => document.activeElement?.name)) === "guardadas";
  await page.goto(base + "anuncios/");
  await page.locator("#lista-ofertas > li button.guardar").first().click();
  const procesos = await page.locator("#pastilla-guardadas").textContent();
  await auditar(page, `guardados en procesos ${viewport.width}`);
  await page.goto(base + `ofertas/${offers[0]}/`);
  const ficha = await page.locator(".guardar-ficha button.guardar").isVisible();
  await auditar(page, `guardar en la ficha ${viewport.width}`);
  if (!visibleAntes || pulsado !== "true" || nota !== 1 || tras[0] !== "?guardadas=1" || tras[1] !== 1
      || tras[2] !== " (2)" || !trasQuitarFiltros || !enAcciones || !quitada || !procesos.includes("(1)") || !ficha || errors.length) {
    problems += 1;
    console.log(`Guardadas incorrecto (${viewport.width}): pastilla=${visibleAntes} pulsado=${pulsado} nota=${nota} `
      + `recarga=${tras} quitarFiltros=${trasQuitarFiltros} enAcciones=${enAcciones} quitada=${quitada} procesos=${procesos} ficha=${ficha} errores=${errors.join(" | ")}`);
  }
  await context.close();
}

// El buscador de un organismo abre la portada filtrada por él y por el texto.
{
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "es-ES" });
  const page = await context.newPage();
  await page.goto(base + "organismos/tragsa/");
  await page.locator("#q-organismo").fill("ingeniero");
  await page.locator("#q-organismo").press("Enter");
  await page.waitForURL(/\?organismo=tragsa&q=ingeniero/);
  const valores = await page.evaluate(() => [document.getElementById("organismo")?.value, document.getElementById("q").value]);
  if (valores[0] !== "tragsa" || valores[1] !== "ingeniero") {
    problems += 1;
    console.log(`El buscador del organismo no filtra la portada: ${valores}`);
  }
  await context.close();
}

// Avisos: grupos cerrados; el buscador abre los que coinciden y anuncia el recuento; «Copiar» visible.
for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 740 }]) {
  const context = await browser.newContext({ viewport, locale: "es-ES" });
  const page = await context.newPage();
  await page.goto(base + "avisos/");
  const cerrados = await page.locator("details.grupo-listas[open]").count() === 0;
  const copiar = await page.locator("button.copiar:visible").count();
  await page.locator("#q-listas").fill("galicia");
  await page.waitForFunction(() => document.getElementById("estado-listas").textContent !== "");
  const abiertos = await page.locator("details.grupo-listas[open]").count();
  const visibles = await page.locator("details.grupo-listas tbody tr:visible").count();
  const mensaje = await page.locator("#estado-listas").textContent();
  await auditar(page, `avisos con búsqueda ${viewport.width}`);
  await page.locator("#q-listas").fill("");
  await page.waitForFunction(() => document.getElementById("estado-listas").textContent === "");
  const restaurado = await page.locator("details.grupo-listas[open]").count() === 0;
  // Una empresa: se ve debajo de su organismo, que sigue a la vista, y solo la tabla de su grupo.
  await page.locator("#q-listas").fill("tragsatec");
  await page.waitForFunction(() => document.getElementById("estado-listas").textContent !== "");
  const empresa = await page.locator("tr.sublista:visible").count() === 1
    && await page.locator("tbody tr:visible", { hasText: "Grupo Tragsa" }).count() === 1
    && await page.locator("table.tabla-listas:visible").count() === 1;
  await page.locator("#q-listas").fill("");
  await page.waitForFunction(() => document.getElementById("estado-listas").textContent === "");
  if (!cerrados || !copiar || !abiertos || !visibles || !mensaje.startsWith(String(visibles)) || !restaurado || !empresa) {
    problems += 1;
    console.log(`Avisos incorrecto: cerrados=${cerrados} copiar=${copiar} abiertos=${abiertos} visibles=${visibles} «${mensaje}» restaurado=${restaurado} empresa=${empresa}`);
  }
  await context.close();
}

// Organismos: «Sin ofertas» plegado; el buscador filtra y anuncia el recuento; al vaciarlo vuelve todo.
for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 740 }]) {
  const context = await browser.newContext({ viewport, locale: "es-ES" });
  const page = await context.newPage();
  await page.goto(base + "organismos/");
  const plegados = await page.locator("details.sin-ofertas-grupo[open]").count() === 0;
  const todos = await page.locator("li[data-texto]").count();
  await page.locator("#q-organismos").fill("correos");
  await page.waitForFunction(() => document.getElementById("estado-organismos").textContent !== "");
  const visibles = await page.locator("li[data-texto]:visible").count();
  const mensaje = await page.locator("#estado-organismos").textContent();
  await auditar(page, `organismos con búsqueda ${viewport.width}`);
  await page.locator("#q-organismos").fill("");
  await page.waitForFunction(() => document.getElementById("estado-organismos").textContent === "");
  const restaurado = await page.locator("details.sin-ofertas-grupo[open]").count() === 0
    && await page.locator("section.grupo-organismos:visible").count() === await page.locator("section.grupo-organismos").count();
  if (!plegados || !visibles || visibles >= todos || !mensaje.startsWith(String(visibles)) || !restaurado) {
    problems += 1;
    console.log(`Organismos incorrecto: plegados=${plegados} visibles=${visibles}/${todos} «${mensaje}» restaurado=${restaurado}`);
  }
  await context.close();
}

// Botón flotante «Arriba»: oculto al cargar, visible al bajar, y lleva al principio de la página (#arriba es el body).
for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 740 }]) {
  const context = await browser.newContext({ viewport, locale: "es-ES" });
  const page = await context.newPage();
  await page.goto(base);
  const ocultoAlCargar = !(await page.locator("#subir-flotante").isVisible());
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await page.waitForFunction(() => !document.getElementById("subir-flotante").hidden);
  await auditar(page, `flotante «Arriba» ${viewport.width}`);
  await page.locator("#subir-flotante").click();
  await page.waitForFunction(() => window.scrollY < 50);
  const arriba = await page.evaluate(() => location.hash === "#arriba");
  if (!ocultoAlCargar || !arriba) {
    problems += 1;
    console.log(`Flotante «Arriba» incorrecto: ocultoAlCargar=${ocultoAlCargar} arriba=${arriba}`);
  }
  await context.close();
}

// Cabecera fija: al bajar sigue arriba con el menú a mano; en móvil el menú abierto cabe en pantalla y se
// cierra al elegir un enlace. Con poca altura (zoom fuerte, apaisado) no se fija.
for (const viewport of [{ width: 1280, height: 900 }, { width: 360, height: 740 }, { width: 740, height: 360 }]) {
  const context = await browser.newContext({ viewport, locale: "es-ES" });
  const page = await context.newPage();
  await page.goto(base);
  // «Saltar al contenido», al recibir el foco, se ve por encima de la cabecera.
  await page.keyboard.press("Tab");
  const salto = await page.evaluate(() => {
    const a = document.querySelector(".salto");
    const r = a.getBoundingClientRect();
    return document.activeElement === a && document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2) === a;
  });
  await page.evaluate(() => window.scrollTo(0, 2000));
  await page.waitForFunction(() => window.scrollY > 0);
  const top = await page.evaluate(() => document.querySelector("header.sitio").getBoundingClientRect().top);
  const fija = viewport.height >= 480;
  let ok = salto && (fija ? Math.abs(top) < 1 : top < -1);
  let detalle = `salto=${salto} top=${top}`;
  if (fija && viewport.width < 600) {
    await page.locator("#btn-menu").click();
    const nav = await page.evaluate(() => document.getElementById("nav-principal").getBoundingClientRect().bottom);
    await auditar(page, "menú móvil abierto con la cabecera fija");
    await page.locator("#nav-principal a").first().evaluate((a) => a.addEventListener("click", (e) => e.preventDefault()));
    await page.locator("#nav-principal a").first().click();
    const cerrado = (await page.locator("#btn-menu").getAttribute("aria-expanded")) === "false";
    ok = ok && nav <= viewport.height && cerrado;
    detalle += ` navBottom=${nav} cerradoAlElegir=${cerrado}`;
  }
  if (!ok) {
    problems += 1;
    console.log(`Cabecera fija incorrecta ${viewport.width}x${viewport.height}: ${detalle}`);
  }
  await context.close();
}

// Los filtros funcionan y anuncian el resultado.
const page = await (await browser.newContext({ viewport: { width: 1280, height: 900 }, locale: "es-ES" })).newPage();
await page.goto(base);
const total = await page.locator("#lista-ofertas > li").count();
await page.locator("#btn-filtros").click();
await page.locator("#comunidad").selectOption({ index: 1 });
const visible = await page.locator("#lista-ofertas > li:visible").count();
const message = await page.locator("#estado-filtros").textContent();
if (!(visible > 0 && visible < total) || !message.startsWith(String(visible))) {
  problems += 1;
  console.log(`Filtro incorrecto: ${visible}/${total} «${message}»`);
}
await page.locator("button[type=reset]").click();
await page.waitForFunction((n) => document.querySelectorAll("#lista-ofertas > li:not([hidden])").length === n, total);

// Se filtra por empresa con el selector del panel; «Quitar filtros», junto al recuento, lo deshace.
await page.locator("#empresa").selectOption({ index: 1 });
const empresa = await page.locator("#empresa").inputValue();
const deOtra = await page.locator(`#lista-ofertas > li:visible:not([data-empresa="${empresa}"])`).count();
const quitar = page.locator(".resultados button[type=reset]");
if (deOtra !== 0 || !(await quitar.isVisible())) {
  problems += 1;
  console.log(`Filtro de empresa incorrecto: ${deOtra} ofertas de otra empresa`);
}
await auditar(page, "empresa elegida y panel de filtros abierto");
await quitar.click();
await page.waitForFunction((n) => document.querySelectorAll("#lista-ofertas > li:not([hidden])").length === n, total);
if ((await page.locator("#empresa").inputValue()) !== "" || (await quitar.isVisible())) {
  problems += 1;
  console.log("«Quitar filtros» no deja la portada sin filtros");
}
// Una búsqueda sin ofertas propone buscar entre los procesos.
await page.locator("#q").fill("zzzzqqq");
await page.waitForTimeout(800);
if (!(await page.locator("#sin-resultados a[href^='anuncios/?q=']").isVisible())) {
  problems += 1;
  console.log("Sin resultados no propone buscar en los procesos");
}
await page.locator("button[type=reset]").click();
await page.locator("#orden").selectOption("empresa");
const empresas = await page.locator("#lista-ofertas > li").evaluateAll((li) => li.map((x) => x.dataset.empresa));
const ordenadas = [...empresas].sort((a, b) => a.localeCompare(b, "es"));
if (empresas.join("|") !== ordenadas.join("|")) {
  problems += 1;
  console.log("Ordenar por empresa no ordena la lista");
}

// Anuncios de procesos e histórico: el buscador filtra y se puede deshacer.
for (const ruta of ["anuncios/", "historico/"]) {
  await page.goto(base + ruta);
  if (!(await page.locator("#filtros").isVisible().catch(() => false))) {
    if (ruta === "anuncios/") { problems += 1; console.log("Anuncios sin buscador visible"); }
    continue;
  }
  const todos = await page.locator("#lista-ofertas > li").count();
  const texto = await page.locator("#lista-ofertas > li h2").first().textContent();
  const palabra = texto.trim().split(/\s+/).sort((a, b) => b.length - a.length)[0];
  await page.locator("#q").fill(palabra);
  await page.waitForTimeout(800); // el buscador espera 500 ms desde la última tecla
  const quedan = await page.locator("#lista-ofertas > li:visible").count();
  if (quedan < 1 || quedan > todos) {
    problems += 1;
    console.log(`Buscador de ${ruta} incorrecto: ${quedan}/${todos} con «${palabra}»`);
  }
  await page.locator("button[type=reset]").click();
  await page.waitForFunction((n) => document.querySelectorAll("#lista-ofertas > li:not([hidden])").length === n, todos);
}

await browser.close();
server.close();
console.log(`${checks} combinaciones auditadas, ${problems} problemas. Filtro: ${visible} de ${total}.`);
process.exit(problems ? 1 : 0);
