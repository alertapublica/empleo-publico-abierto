// «Guardar» ofertas y procesos para volver a ellos. Mejora progresiva: sin JavaScript no aparece.
// Todo queda en este navegador (localStorage): no se envía nada ni pasa a otros dispositivos.
// Se carga antes que filtros.js, que filtra con la casilla «guardadas» y el dato data-guardadas.
(function (global) {
  "use strict";

  var KEY = "empleo-guardadas-v1";
  // «o:» ofertas (o:<organismo>-<ref>), «p:» procesos (p:<hash>). Lo demás se descarta.
  var ID = /^[op]:[a-z0-9_-]{1,200}$/;
  var TEXTOS = {
    o: { uno: "1 de sus ofertas guardadas ya ha cerrado:", varios: " de sus ofertas guardadas ya han cerrado:",
         quitar: "Quitarlas de guardadas" },
    p: { uno: "1 de sus procesos guardados ya no está en marcha:", varios: " de sus procesos guardados ya no están en marcha:",
         quitar: "Quitarlos de guardados" }
  };

  // ---- estado ----
  function limpiar(o) {
    var salida = {};
    if (!o || typeof o !== "object" || Array.isArray(o)) return salida;
    Object.keys(o).forEach(function (id) {
      var g = o[id];
      if (!ID.test(id) || !g || typeof g.t !== "string" || typeof g.u !== "string" || !/^https?:\/\//i.test(g.u)) return;
      salida[id] = { t: g.t.slice(0, 300), u: g.u };
    });
    return salida;
  }
  function cargar() {
    try {
      var raw = global.localStorage.getItem(KEY);
      return limpiar(raw ? JSON.parse(raw) : null);
    } catch (e) {
      return {};
    }
  }
  function guardar(s) {
    try { global.localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* sin almacenamiento: vale solo esta visita */ }
  }
  function deTipo(s, tipo) {
    return Object.keys(s).filter(function (id) { return id.charAt(0) === tipo; });
  }
  // Las guardadas de un tipo que ya no están en la lista de abiertas (o de procesos en marcha).
  function fuera(s, tipo, presentes) {
    return deTipo(s, tipo).filter(function (id) { return presentes.indexOf(id) === -1; });
  }

  // ---- página ----
  function iniciar(doc) {
    var estado = cargar();
    var botones = [];
    var casilla = doc.querySelector('#filtros input[name="guardadas"]');
    var pastilla = casilla && casilla.closest(".pastilla");
    var contador = doc.getElementById("n-guardadas");
    var lista = doc.getElementById("lista-ofertas");
    var nota = null;

    Array.prototype.forEach.call(doc.querySelectorAll("[data-guardar]"), function (el) {
      var id = el.dataset.guardar;
      if (!ID.test(id)) return;
      var enlace = el.querySelector("h2 a, h3 a");
      var h1 = doc.querySelector("h1");
      var titulo = (enlace ? enlace.textContent : h1 ? h1.textContent : "").trim();
      var destino = enlace ? enlace.href : global.location.href.split(/[?#]/)[0];
      var boton = doc.createElement("button");
      var estrella = doc.createElement("span");
      boton.type = "button";
      boton.className = "guardar";
      // En las listas hay un botón por tarjeta: el nombre dice cuál.
      if (enlace) boton.setAttribute("aria-label", "Guardar: " + titulo);
      estrella.setAttribute("aria-hidden", "true");
      boton.append(estrella, " Guardar");
      boton.addEventListener("click", function () {
        estado = cargar();
        if (estado[id]) delete estado[id];
        else estado[id] = { t: titulo, u: destino };
        guardar(estado);
        pintar();
      });
      // En las ofertas, a la derecha del título; en los procesos, junto al RSS (o al pie).
      (el.querySelector(".tarjeta-acciones, .proceso-acciones") || el).appendChild(boton);
      if (el.tagName !== "LI") el.hidden = false;  // la ficha: su párrafo espera oculto al botón
      botones.push({ id: id, el: el, boton: boton, estrella: estrella });
    });

    var presentes = lista
      ? Array.prototype.map.call(lista.querySelectorAll("li[data-guardar]"), function (li) { return li.dataset.guardar; })
      : [];

    function pintarNota(tipo) {
      var cerradas = fuera(estado, tipo, presentes);
      if (!casilla.checked || !cerradas.length) {
        if (nota) nota.hidden = true;
        return;
      }
      if (!nota) {
        nota = doc.createElement("div");
        nota.className = "nota";
        nota.id = "guardadas-cerradas";
        var resultados = doc.querySelector(".resultados");
        var form = casilla.form;
        form.parentNode.insertBefore(nota, resultados || form.nextSibling);
      }
      var t = TEXTOS[tipo];
      var p = doc.createElement("p");
      p.textContent = cerradas.length === 1 ? t.uno : cerradas.length + t.varios;
      var ul = doc.createElement("ul");
      cerradas.forEach(function (id) {
        var li = doc.createElement("li");
        var a = doc.createElement("a");
        a.href = estado[id].u;
        a.textContent = estado[id].t;
        li.appendChild(a);
        ul.appendChild(li);
      });
      var quitar = doc.createElement("button");
      quitar.type = "button";
      quitar.className = "quitar";
      quitar.textContent = t.quitar;
      quitar.addEventListener("click", function () {
        estado = cargar();
        fuera(estado, tipo, presentes).forEach(function (id) { delete estado[id]; });
        guardar(estado);
        pintar();
        casilla.focus();  // la nota desaparece: el foco no se pierde
      });
      nota.replaceChildren(p, ul, quitar);
      nota.hidden = false;
    }

    function pintar() {
      botones.forEach(function (x) {
        var si = Boolean(estado[x.id]);
        x.boton.setAttribute("aria-pressed", String(si));
        x.estrella.textContent = si ? "★" : "☆";
        // Al guardar o quitar no se vuelve a filtrar: la tarjeta (y el foco) se quedan donde están.
        if (x.el.tagName === "LI") x.el.dataset.guardadas = si ? "1" : "0";
      });
      if (!pastilla) return;
      var tipo = pastilla.dataset.tipo;
      var n = deTipo(estado, tipo).length;
      pastilla.hidden = !n && !casilla.checked;
      contador.textContent = n ? " (" + n + ")" : "";
      pintarNota(tipo);
    }

    if (casilla) {
      // filtros.js marca la casilla desde la dirección después; aquí hace falta ya para mostrarla.
      if (new URLSearchParams(global.location.search).get("guardadas") === "1") casilla.checked = true;
      casilla.addEventListener("change", pintar);
      // «Quitar filtros» desmarca la casilla sin evento «change»: la nota y la pastilla se repintan igual.
      casilla.form.addEventListener("reset", function () { setTimeout(pintar, 0); });
    }
    // Lo guardado en otra pestaña se refleja aquí.
    global.addEventListener("storage", function (event) {
      if (event.key === KEY || event.key === null) {
        estado = cargar();
        pintar();
      }
    });
    pintar();
  }

  var Guardadas = { KEY: KEY, limpiar: limpiar, cargar: cargar, guardar: guardar, deTipo: deTipo, fuera: fuera };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = Guardadas;
  } else {
    iniciar(global.document);
  }
})(typeof window !== "undefined" ? window : globalThis);
