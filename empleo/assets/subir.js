// Botón flotante «Arriba»: aparece al bajar más de una pantalla y media. Sin JavaScript no se muestra
// y queda el enlace «Volver arriba» del pie.
(function () {
  "use strict";
  var boton = document.getElementById("subir-flotante");
  if (!boton) return;
  var pendiente = false;
  function actualizar() {
    pendiente = false;
    boton.hidden = window.scrollY < window.innerHeight * 1.5;
  }
  window.addEventListener("scroll", function () {
    if (!pendiente) {
      pendiente = true;
      window.requestAnimationFrame(actualizar);
    }
  }, { passive: true });
  actualizar();
})();
