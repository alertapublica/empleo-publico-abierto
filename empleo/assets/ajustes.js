// Mejora progresiva: panel «Aa» (apariencia), menú en pantallas estrechas y ayudas de lectura.
// Sin JavaScript no aparece ningún botón y la web sigue entera.
(function () {
  "use strict";
  var T = window.Tema;
  var $ = function (id) { return document.getElementById(id); };
  var fmt = function (n) { return Number(n).toLocaleString("es-ES", { maximumFractionDigits: 1 }); };

  // ---- menú en pantallas estrechas ----
  var menu = $("btn-menu");
  var nav = $("nav-principal");
  if (menu && nav) {
    menu.hidden = false;
    // Solo ahora, con el botón ya visible, la navegación puede plegarse.
    document.documentElement.classList.add("menu-js");
    var cerrar = function () { nav.classList.remove("abierto"); menu.setAttribute("aria-expanded", "false"); };
    menu.addEventListener("click", function () {
      var abierto = nav.classList.toggle("abierto");
      menu.setAttribute("aria-expanded", String(abierto));
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && nav.classList.contains("abierto")) { cerrar(); menu.focus(); }
    });
    // Al elegir un enlace el menú se cierra, también si lleva a otro punto de la misma página.
    nav.addEventListener("click", function (e) { if (e.target.closest("a")) cerrar(); });
    // Altura de la cabecera (fija al bajar) para el margen de desplazamiento de estilos.css y, con el
    // menú abierto, la de su fila de arriba: con letra grande la marca ocupa varias líneas.
    var cab = document.querySelector("header.sitio");
    if (cab && window.ResizeObserver) {
      new ResizeObserver(function () {
        var raiz = document.documentElement.style;
        raiz.setProperty("--cab-alto", cab.offsetHeight + "px");
        if (nav.offsetParent) raiz.setProperty("--cab-fila", (nav.getBoundingClientRect().top - cab.getBoundingClientRect().top) + "px");
      }).observe(cab);
    }
  }

  // ---- ayudas de lectura ----
  var guardado = new WeakMap();
  function objetivos() {
    return document.querySelectorAll("main .ofertas h2 a, main .texto-oficial p, main .texto-oficial li, main .resumen");
  }
  function negritaInicial(el) {
    var walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    var nodos = [];
    while (walker.nextNode()) nodos.push(walker.currentNode);
    nodos.forEach(function (nodo) {
      var texto = nodo.textContent;
      if (!/[\p{L}\p{N}]/u.test(texto)) return;
      var frag = document.createDocumentFragment();
      var re = /[\p{L}\p{N}]+/gu, ultimo = 0, m;
      while ((m = re.exec(texto)) !== null) {
        if (m.index > ultimo) frag.appendChild(document.createTextNode(texto.slice(ultimo, m.index)));
        var mitad = Math.max(1, Math.ceil(m[0].length / 2));
        var b = document.createElement("b");
        b.textContent = m[0].slice(0, mitad);
        frag.appendChild(b);
        frag.appendChild(document.createTextNode(m[0].slice(mitad)));
        ultimo = m.index + m[0].length;
      }
      if (ultimo < texto.length) frag.appendChild(document.createTextNode(texto.slice(ultimo)));
      nodo.parentNode.replaceChild(frag, nodo);
    });
  }
  function bionic(activo) {
    objetivos().forEach(function (el) {
      if (activo && !guardado.has(el)) {
        guardado.set(el, el.innerHTML);
        negritaInicial(el);
      } else if (!activo && guardado.has(el)) {
        el.innerHTML = guardado.get(el);
        guardado.delete(el);
      }
    });
  }

  var pendiente = false;
  function foco() {
    var items = document.querySelectorAll("main .ofertas > li:not([hidden])");
    var activo = document.documentElement.getAttribute("data-focus") === "1";
    var medio = window.innerHeight / 2, mejor = null, dist = Infinity;
    items.forEach(function (el) {
      if (!activo) { el.classList.remove("foco-atenuada"); return; }
      var r = el.getBoundingClientRect();
      var d = Math.abs((r.top + r.bottom) / 2 - medio);
      if (d < dist) { dist = d; mejor = el; }
    });
    if (activo) items.forEach(function (el) { el.classList.toggle("foco-atenuada", el !== mejor); });
    pendiente = false;
  }
  function pedirFoco() {
    if (!pendiente) { pendiente = true; requestAnimationFrame(foco); }
  }
  window.addEventListener("scroll", function () {
    if (document.documentElement.getAttribute("data-focus") === "1") pedirFoco();
  }, { passive: true });

  // ---- panel Aa ----
  var abrir = $("btn-aa");
  var dlg = $("ajustes");
  if (!T || !abrir || !dlg || typeof dlg.showModal !== "function") return;

  var s = T.cargar();
  var campos = {
    colores: $("colores"), fs: $("fs-val"), ancho: $("ancho-val")
  };

  function refrescar() {
    T.aplicar(s);
    T.guardar(s);
    pintar();
    bionic(s.bionic);
    pedirFoco();
  }
  function pintar() {
    dlg.querySelectorAll("input[name=tema]").forEach(function (i) { i.checked = i.value === s.tema; });
    dlg.querySelectorAll("input[name=fuente]").forEach(function (i) { i.checked = i.value === s.fuente; });
    dlg.querySelectorAll("input[name=extra]").forEach(function (i) { i.checked = !!s[i.value]; });
    campos.fs.textContent = fmt(s.fs) + " %";
    campos.ancho.textContent = s.ancho === T.ANCHO.completo ? "Completo" : s.ancho + " px";
    var personalizado = s.tema === "custom" && s.colores;
    campos.colores.hidden = !personalizado;
    if (!personalizado) return;
    T.CLAVES_COLOR.forEach(function (k) {
      var inp = $("color-" + k);
      if (inp.value !== s.colores[k]) inp.value = s.colores[k];
      var out = $("contraste-" + k);
      if (!out) return;
      var r = T.contraste(s.colores[k], s.colores.fondo);
      var poco = r < 4.5;
      out.classList.toggle("poco", poco);
      out.textContent = fmt(Math.round(r * 10) / 10) + ":1 " + (poco ? "· contraste insuficiente" : "· contraste suficiente");
    });
  }

  abrir.hidden = false;
  abrir.addEventListener("click", function () { pintar(); dlg.showModal(); });
  $("ajustes-cerrar").addEventListener("click", function () { dlg.close(); });
  dlg.addEventListener("click", function (e) { if (e.target === dlg) dlg.close(); });

  dlg.addEventListener("change", function (e) {
    var i = e.target;
    if (!(i instanceof HTMLInputElement)) return;
    if (i.name === "tema") {
      s.tema = i.value;
      if (i.value === "custom" && !s.colores) s.colores = T.coloresActuales();
    } else if (i.name === "fuente") {
      s.fuente = i.value;
    } else if (i.name === "extra") {
      s[i.value] = i.checked;
    }
    refrescar();
  });
  // Colores: se ven al mover el selector y se guardan al soltarlo.
  T.CLAVES_COLOR.forEach(function (k) {
    var inp = $("color-" + k);
    inp.addEventListener("input", function () {
      s.colores = T.limpiarColores(Object.assign({}, s.colores, { [k]: inp.value }));
      T.aplicar(s);
      pintar();
    });
    inp.addEventListener("change", function () { T.guardar(s); });
  });

  $("fs-menos").addEventListener("click", function () { s.fs = T.paso(s.fs, -1); refrescar(); });
  $("fs-mas").addEventListener("click", function () { s.fs = T.paso(s.fs, +1); refrescar(); });
  $("ancho-menos").addEventListener("click", function () { s.ancho = T.anchoMas(s.ancho, -1); refrescar(); });
  $("ancho-mas").addEventListener("click", function () { s.ancho = T.anchoMas(s.ancho, +1); refrescar(); });
  $("ajustes-reset").addEventListener("click", function () { s = T.limpiar(null); refrescar(); });

  pintar();
  bionic(s.bionic);
  pedirFoco();
})();
