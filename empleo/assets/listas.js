// Página de avisos. Mejora progresiva: sin JavaScript los grupos se abren a mano y el enlace se copia
// con el botón derecho. Con él, un buscador filtra los grupos y cada lista tiene un botón «Copiar».
(function () {
  "use strict";
  var form = document.getElementById("buscar-listas");
  var input = document.getElementById("q-listas");
  var estado = document.getElementById("estado-listas");
  var estadoCopia = document.getElementById("estado-copia");
  var grupos = Array.prototype.slice.call(document.querySelectorAll("details.grupo-listas"));
  var timer = null;
  var abiertos = null; // grupos abiertos antes de buscar, para dejarlos igual al vaciar la búsqueda

  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function filtrar() {
    var words = plain(input.value).split(/\s+/).filter(Boolean);
    if (!words.length) {
      grupos.forEach(function (g, i) {
        g.hidden = false;
        if (abiertos) g.open = abiertos[i];
        g.querySelectorAll("tr, table").forEach(function (el) { el.hidden = false; });
      });
      abiertos = null;
      estado.textContent = "";
      return;
    }
    if (!abiertos) abiertos = grupos.map(function (g) { return g.open; });
    var total = 0;
    grupos.forEach(function (g) {
      var n = 0;
      var organismo = null;
      g.querySelectorAll("tbody tr").forEach(function (tr) {
        var texto = plain(tr.querySelector("a").textContent);
        var match = words.every(function (w) { return texto.indexOf(w) !== -1; });
        tr.hidden = !match;
        if (match) n += 1;
        // Las filas de empresa van debajo de su organismo, que sigue a la vista si coincide alguna.
        if (!tr.classList.contains("sublista")) organismo = tr;
        else if (match && organismo) organismo.hidden = false;
      });
      // Cada tabla, solo si le queda algo que mostrar.
      g.querySelectorAll("table").forEach(function (t) {
        t.hidden = !t.querySelector("tbody tr:not([hidden])");
      });
      g.hidden = n === 0;
      g.open = n > 0;
      total += n;
    });
    estado.textContent = total === 0
      ? "Ninguna lista coincide."
      : total === 1 ? "1 lista encontrada." : total + " listas encontradas.";
  }

  // ?organismo=tragsa (enlace desde otra web): deja marcada su casilla en el formulario de correo y
  // abierto su grupo. Solo se compara con las casillas que ya existen.
  var pedido = new URLSearchParams(location.search).get("organismo");
  if (pedido) {
    document.querySelectorAll('.form-correo input[name="organismos"]').forEach(function (casilla) {
      if (casilla.value !== pedido) return;
      casilla.checked = true;
      var grupo = casilla.closest("details");
      if (grupo) grupo.open = true;
    });
  }

  if (form && input && estado && grupos.length) {
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

  // «Copiar»: copia la dirección completa del feed, no la relativa del enlace.
  if (!navigator.clipboard || !estadoCopia) return;
  document.querySelectorAll("button.copiar").forEach(function (boton) {
    var enlace = boton.closest("li, tr").querySelector("a");
    var texto = boton.firstChild;
    boton.hidden = false;
    boton.addEventListener("click", function () {
      var url = new URL(enlace.getAttribute("href"), location.href).href;
      navigator.clipboard.writeText(url).then(function () {
        texto.textContent = "Copiado";
        estadoCopia.textContent = "Enlace de «" + enlace.textContent + "» copiado. Péguelo en su lector de RSS.";
        setTimeout(function () { texto.textContent = "Copiar"; }, 2500);
      }, function () {
        estadoCopia.textContent = "No se ha podido copiar. Copie el enlace con el botón derecho o con una pulsación larga.";
      });
    });
  });
})();
