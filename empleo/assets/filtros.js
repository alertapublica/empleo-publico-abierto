// Mejora progresiva: sin JavaScript la página sigue mostrando toda la lista.
// Sirve a las ofertas, a los anuncios de procesos y al histórico: cada formulario
// declara solo los campos que usa y el script se adapta a ellos.
(function () {
  "use strict";
  var form = document.getElementById("filtros");
  var list = document.getElementById("lista-ofertas");
  if (!form || !list) return;
  var status = document.getElementById("estado-filtros");
  var items = Array.prototype.slice.call(list.children);
  var selects = ["grupo", "comunidad", "organismo", "empresa", "area", "tipo", "acceso", "sistema", "contrato"].filter(function (n) { return form[n]; });
  // Campos con varios valores separados por espacios (una oferta puede tener dos áreas).
  var VARIOS = { area: true };
  // Casillas: nombre del campo y dato de la tarjeta que tiene que valer "1" («guardadas»: lo pone guardadas.js).
  var casillas = ["pronto", "teletrabajo", "guardadas"].filter(function (n) { return form[n]; });
  // Panel de filtros plegado, que abre el botón «Filtros».
  var mas = document.getElementById("mas-filtros");
  var botonMas = document.getElementById("btn-filtros");
  var plegados = selects.filter(function (n) { return mas && mas.contains(form[n]); });
  var sinResultados = document.getElementById("sin-resultados");
  var ordenCampo = document.getElementById("orden-campo");
  var names = ["q"].concat(selects, form.orden ? ["orden"] : []);
  var hayPlazas = items.some(function (item) { return item.dataset.plazas !== undefined; });
  var uno = form.dataset.uno || "oferta encontrada";
  var varios = form.dataset.varios || "ofertas encontradas";
  var timer = null;

  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  // Por qué campo se ordena y en qué sentido. A igualdad, lo más reciente primero.
  var ORDEN = { reciente: ["publicada", -1], plazo: ["plazo", 1], empresa: ["empresa", 1] };
  function comparar(clave) {
    var campo = ORDEN[clave][0], sentido = ORDEN[clave][1];
    return function (a, b) {
      var r = sentido * a.dataset[campo].localeCompare(b.dataset[campo], "es");
      return r || b.dataset.publicada.localeCompare(a.dataset.publicada);
    };
  }

  function apply(announce) {
    var words = plain(form.q.value).split(/\s+/).filter(Boolean);
    var marcadas = casillas.filter(function (n) { return form[n].checked; });
    var shown = 0;
    var seats = 0;
    items.forEach(function (item) {
      var d = item.dataset;
      var match =
        words.every(function (word) { return d.texto.indexOf(word) !== -1; }) &&
        selects.every(function (n) {
          var v = form[n].value;
          return !v || (VARIOS[n] ? (d[n] || "").split(" ").indexOf(v) !== -1 : d[n] === v);
        }) &&
        marcadas.every(function (n) { return d[n] === "1"; });
      item.hidden = !match;
      if (match) {
        shown += 1;
        seats += Number(d.plazas) || 0;
      }
    });
    var activos = plegados.filter(function (n) { return form[n].value; }).length;
    // «Quitar filtros» solo aparece cuando hay algo que quitar.
    // En la portada va junto al recuento, fuera del formulario (atributo form): se busca en form.elements.
    var quitar = Array.prototype.filter.call(form.elements, function (el) { return el.type === "reset"; })[0];
    if (quitar) {
      quitar.hidden = !(words.length || marcadas.length || selects.some(function (n) { return form[n].value; }));
    }
    var contador = document.getElementById("n-filtros");
    if (contador) contador.textContent = activos ? " (" + activos + (activos === 1 ? " activo)" : " activos)") : "";
    // Sin resultados, se propone la misma búsqueda entre los procesos selectivos.
    if (sinResultados) {
      var procesos = form.dataset.procesos;
      sinResultados.hidden = shown !== 0;
      sinResultados.textContent = "";
      if (shown === 0 && procesos && words.length) {
        var enlace = document.createElement("a");
        enlace.href = procesos + "?q=" + encodeURIComponent(form.q.value.trim());
        enlace.textContent = "Buscar «" + form.q.value.trim() + "» en los procesos selectivos";
        sinResultados.append("Ninguna oferta abierta coincide con la búsqueda. ", enlace, ".");
      } else if (shown === 0) {
        sinResultados.textContent = "Ningún resultado coincide con estos filtros. Pruebe a quitar alguno.";
      }
    }
    if (form.orden && ORDEN[form.orden.value]) {
      items.slice().sort(comparar(form.orden.value)).forEach(function (item) { list.appendChild(item); });
    }

    if (announce && status) {
      status.textContent = shown === 1
        ? "1 " + uno + "."
        : shown + " " + varios + (hayPlazas ? ", con " + seats + " plazas" : "") + ".";
    }
    var params = new URLSearchParams();
    names.forEach(function (name) {
      if (form[name].value && !(name === "orden" && form.orden.value === "reciente")) {
        params.set(name, form[name].value);
      }
    });
    marcadas.forEach(function (n) { params.set(n, "1"); });
    var query = params.toString();
    history.replaceState(null, "", query ? "?" + query : location.pathname);
  }

  var initial = new URLSearchParams(location.search);
  names.forEach(function (name) {
    if (initial.has(name)) form[name].value = initial.get(name);
  });
  casillas.forEach(function (n) { form[n].checked = initial.get(n) === "1"; });
  function abrirPanel(abierto) {
    mas.hidden = !abierto;
    botonMas.setAttribute("aria-expanded", String(abierto));
  }
  if (mas && botonMas) {
    botonMas.addEventListener("click", function () { abrirPanel(mas.hidden); });
    if (plegados.some(function (n) { return initial.has(n); })) abrirPanel(true);
  }
  // El orden va junto al recuento, fuera del formulario (atributo form): su cambio no llega al formulario.
  if (form.orden) form.orden.addEventListener("change", function () { apply(true); });
  if (ordenCampo) ordenCampo.hidden = false;
  form.hidden = false;
  apply(initial.toString() !== "");

  form.addEventListener("submit", function (event) {
    event.preventDefault();
    apply(true);
  });
  form.addEventListener("change", function () { apply(true); });
  form.q.addEventListener("input", function () {
    clearTimeout(timer);
    timer = setTimeout(function () { apply(true); }, 500);
  });
  form.addEventListener("reset", function () {
    // El botón se oculta al no quedar filtros: el foco pasa a la barra de búsqueda.
    setTimeout(function () { apply(true); form.q.focus(); }, 0);
  });
})();
