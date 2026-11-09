// Página «Datos abiertos». Mejora progresiva: sin JavaScript se ven todas las tablas y los ejemplos
// de cada sistema uno debajo de otro. Con él, un buscador filtra los campos (sin tener en cuenta
// acentos), los ejemplos pasan a pestañas y cada uno tiene un botón «Copiar». El sistema elegido se
// recuerda en este navegador (localStorage); no se envía nada.
(function () {
  "use strict";

  // --- Buscador de campos ---
  var form = document.getElementById("buscar-campos");
  var input = document.getElementById("q-campos");
  var estado = document.getElementById("estado-campos");
  var secciones = Array.prototype.slice.call(document.querySelectorAll("section.campos-fichero"));
  var timer = null;

  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function filtrar() {
    var words = plain(input.value).split(/\s+/).filter(Boolean);
    var total = 0;
    secciones.forEach(function (s) {
      var n = 0;
      s.querySelectorAll("tbody tr").forEach(function (tr) {
        var texto = plain(tr.textContent);
        var match = words.every(function (w) { return texto.indexOf(w) !== -1; });
        tr.hidden = !match;
        if (match) n += tr.querySelectorAll("th code").length;
      });
      s.hidden = n === 0;
      total += n;
    });
    estado.textContent = !words.length ? ""
      : total === 0 ? "Ningún campo coincide."
      : total === 1 ? "1 campo encontrado." : total + " campos encontrados.";
  }

  if (form && input && estado && secciones.length) {
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      clearTimeout(timer);
      filtrar();
    });
    input.addEventListener("input", function () {
      clearTimeout(timer);
      timer = setTimeout(filtrar, 300);
    });
    form.hidden = false;
  }

  // --- Ejemplos en pestañas, con el mismo sistema elegido en todos ---
  var KEY = "datos-sistema";
  var ejemplos = Array.prototype.slice.call(document.querySelectorAll("div.ejemplo"));
  var estadoCopia = document.getElementById("estado-copia");
  var pestanas = []; // [{sistema, tab, panel}] de todos los ejemplos

  function guardado() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function elegir(sistema, guardar) {
    pestanas.forEach(function (p) {
      var activa = p.sistema === sistema;
      p.tab.setAttribute("aria-selected", activa ? "true" : "false");
      p.tab.tabIndex = activa ? 0 : -1;
      p.panel.hidden = !activa;
    });
    if (guardar) {
      try { localStorage.setItem(KEY, sistema); } catch (e) { /* sin almacenamiento: vale solo esta visita */ }
    }
  }

  ejemplos.forEach(function (ejemplo, i) {
    var bloques = Array.prototype.slice.call(ejemplo.querySelectorAll(".ejemplo-bloque"));
    var barra = document.createElement("div");
    barra.className = "barra-ejemplo";
    var lista = document.createElement("div");
    lista.setAttribute("role", "tablist");
    lista.setAttribute("aria-label", "Sistema");
    var propias = [];
    bloques.forEach(function (bloque) {
      var sistema = bloque.dataset.sistema;
      var etiqueta = bloque.querySelector(".sistema");
      var tab = document.createElement("button");
      tab.type = "button";
      tab.id = "tab-" + i + "-" + sistema;
      tab.setAttribute("role", "tab");
      tab.setAttribute("aria-controls", "panel-" + i + "-" + sistema);
      tab.textContent = etiqueta.textContent;
      bloque.id = "panel-" + i + "-" + sistema;
      bloque.setAttribute("role", "tabpanel");
      bloque.setAttribute("aria-labelledby", tab.id);
      etiqueta.hidden = true; // la pestaña ya lo dice
      tab.addEventListener("click", function () { elegir(sistema, true); });
      lista.appendChild(tab);
      propias.push(tab);
      pestanas.push({ sistema: sistema, tab: tab, panel: bloque });
    });
    // Teclado: flechas, Inicio y Fin cambian de pestaña dentro del ejemplo.
    lista.addEventListener("keydown", function (event) {
      var actual = propias.indexOf(document.activeElement);
      if (actual === -1) return;
      var destino = { ArrowRight: actual + 1, ArrowLeft: actual - 1, Home: 0, End: propias.length - 1 }[event.key];
      if (destino === undefined) return;
      event.preventDefault();
      var tab = propias[(destino + propias.length) % propias.length];
      tab.click();
      tab.focus();
    });
    barra.appendChild(lista);

    if (navigator.clipboard && estadoCopia) {
      var copiar = document.createElement("button");
      copiar.type = "button";
      copiar.className = "copiar";
      var texto = document.createTextNode("Copiar");
      var oculto = document.createElement("span");
      oculto.className = "sr-only";
      oculto.textContent = " el código";
      copiar.appendChild(texto);
      copiar.appendChild(oculto);
      copiar.addEventListener("click", function () {
        var visible = propias.filter(function (t) { return t.getAttribute("aria-selected") === "true"; })[0];
        var panel = document.getElementById(visible.getAttribute("aria-controls"));
        navigator.clipboard.writeText(panel.querySelector("pre").textContent).then(function () {
          texto.textContent = "Copiado";
          estadoCopia.textContent = "Código para " + visible.textContent + " copiado.";
          setTimeout(function () { texto.textContent = "Copiar"; }, 2500);
        }, function () {
          estadoCopia.textContent = "No se ha podido copiar. Seleccione el código y cópielo a mano.";
        });
      });
      barra.appendChild(copiar);
    }
    ejemplo.insertBefore(barra, ejemplo.firstChild);
  });

  if (pestanas.length) {
    var inicial = guardado();
    var sistemas = pestanas.map(function (p) { return p.sistema; });
    if (sistemas.indexOf(inicial) === -1) {
      inicial = /Win/.test(navigator.platform || navigator.userAgent) ? "windows" : "unix";
    }
    elegir(inicial, false);
  }
})();
