// Página de organismos. Mejora progresiva: sin JavaScript se ve todo y el buscador no aparece.
// Con él, filtra tarjetas y listas «Sin ofertas» por nombre o comunidad, sin tener en cuenta acentos.
(function () {
  "use strict";
  var form = document.getElementById("buscar-organismos");
  var input = document.getElementById("q-organismos");
  var estado = document.getElementById("estado-organismos");
  var grupos = Array.prototype.slice.call(document.querySelectorAll("section.grupo-organismos"));
  if (!form || !input || !estado || !grupos.length) return;
  var plegables = Array.prototype.slice.call(document.querySelectorAll("details.sin-ofertas-grupo"));
  var timer = null;
  var abiertos = null; // «Sin ofertas» abiertos antes de buscar, para dejarlos igual al vaciar la búsqueda

  function plain(text) {
    return text.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
  }

  function filtrar() {
    var words = plain(input.value).split(/\s+/).filter(Boolean);
    if (!words.length) {
      grupos.forEach(function (g) {
        g.hidden = false;
        g.querySelectorAll("li[data-texto], ol.organismos").forEach(function (el) { el.hidden = false; });
      });
      plegables.forEach(function (d, i) {
        d.hidden = false;
        if (abiertos) d.open = abiertos[i];
      });
      abiertos = null;
      estado.textContent = "";
      return;
    }
    if (!abiertos) abiertos = plegables.map(function (d) { return d.open; });
    var total = 0;
    grupos.forEach(function (g) {
      var n = 0;
      g.querySelectorAll("li[data-texto]").forEach(function (li) {
        var texto = plain(li.dataset.texto);
        var match = words.every(function (w) { return texto.indexOf(w) !== -1; });
        li.hidden = !match;
        if (match) n += 1;
      });
      g.querySelectorAll("ol.organismos, details.sin-ofertas-grupo").forEach(function (bloque) {
        var hay = bloque.querySelector("li[data-texto]:not([hidden])") !== null;
        bloque.hidden = !hay;
        if (bloque.tagName === "DETAILS") bloque.open = hay;
      });
      g.hidden = n === 0;
      total += n;
    });
    estado.textContent = total === 0
      ? "Ningún organismo coincide."
      : total === 1 ? "1 organismo encontrado." : total + " organismos encontrados.";
  }

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
})();
