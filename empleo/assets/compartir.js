// «Compartir» en las tarjetas y en la ficha de cada oferta. Mejora progresiva: sin JavaScript, o si el
// navegador no tiene menú de compartir (la mayoría de escritorios), el enlace abre el correo (mailto:).
// Con él, abre el menú nativo del sistema: WhatsApp, correo, copiar enlace…
(function () {
  "use strict";
  if (!navigator.share) return;
  document.addEventListener("click", function (ev) {
    var enlace = ev.target.closest && ev.target.closest("a.compartir");
    if (!enlace) return;
    ev.preventDefault();
    navigator.share({ title: enlace.dataset.titulo, url: enlace.dataset.url }).catch(function (err) {
      // Si se cierra el menú no se hace nada; si falla por otra razón, se recurre al correo.
      if (err && err.name !== "AbortError") window.location.href = enlace.href;
    });
  });
})();
