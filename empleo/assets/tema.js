// Preferencias de apariencia («Aa»). Se carga en <head>, sin diferir, para pintar
// el tema guardado antes del primer fotograma. Todo queda en este navegador
// (localStorage): no se envía nada. Sin JavaScript, la web usa el tema del sistema.
(function (global) {
  "use strict";

  var KEY = "empleo-ajustes-v1";
  var TEMAS = ["auto", "light", "sepia", "dark", "contrast", "custom"];
  var FUENTES = ["sans", "serif", "dyslexic"];
  // Tamaño: porcentaje de la letra que el navegador tiene configurada (100 = la tuya).
  var PASOS_FS = [75, 87.5, 100, 112.5, 125, 150, 175, 200];
  // Pasado el máximo, «completo»: sin límite de ancho, solo el margen lateral (lo elige cada persona).
  var ANCHO = { min: 480, max: 1600, paso: 40, completo: "completo" };
  var DEF = { tema: "auto", fuente: "sans", fs: 112.5, ancho: 1200, just: false, bionic: false, focus: false, colores: null };
  var CLAVES_COLOR = ["fondo", "texto", "enlaces", "titulos"];
  var VARS = ["bg", "surface", "ink", "muted", "line", "accent", "accent-ink", "alert", "alert-bg", "focus", "titulos"];

  // ---- color ----
  function canales(hex) {
    return [1, 3, 5].map(function (i) { return parseInt(hex.slice(i, i + 2), 16); });
  }
  function aHex(rgb) {
    return "#" + rgb.map(function (c) {
      return Math.round(Math.max(0, Math.min(255, c))).toString(16).padStart(2, "0");
    }).join("");
  }
  function luminancia(hex) {
    var c = canales(hex).map(function (v) {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
  }
  function contraste(a, b) {
    var x = luminancia(a), y = luminancia(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  function mezcla(a, b, t) {
    var ca = canales(a), cb = canales(b);
    return aHex(ca.map(function (c, i) { return c + (cb[i] - c) * t; }));
  }
  function extremo(c) {
    return contraste("#000000", c) >= contraste("#ffffff", c) ? "#000000" : "#ffffff";
  }
  // Acerca `color` hacia `hacia` hasta llegar a `minimo` sobre todos los fondos.
  function hastaContraste(color, fondos, minimo, hacia) {
    var lista = [].concat(fondos);
    var ok = function (c) { return lista.every(function (f) { return contraste(c, f) >= minimo; }); };
    var destinos = [hacia, extremo(lista[0])];
    for (var d = 0; d < destinos.length; d++) {
      for (var i = 0; i <= 20; i++) {
        var c = mezcla(color, destinos[d], i / 20);
        if (ok(c)) return c;
      }
    }
    return extremo(lista[0]);
  }
  function hex6(v) {
    return typeof v === "string" && /^#[0-9a-f]{6}$/i.test(v) ? v.toLowerCase() : null;
  }
  function limpiarColores(c) {
    if (!c || typeof c !== "object") return null;
    var salida = {};
    for (var i = 0; i < CLAVES_COLOR.length; i++) {
      var v = hex6(c[CLAVES_COLOR[i]]);
      if (!v) return null;
      salida[CLAVES_COLOR[i]] = v;
    }
    return salida;
  }
  // De cuatro colores elegidos sale el resto, con el contraste de lo derivado garantizado.
  // Lo elegido no se corrige: la interfaz avisa si baja de 4,5:1.
  function paleta(c) {
    var oscuro = luminancia(c.fondo) < 0.18;
    var superficie = mezcla(c.fondo, c.texto, 0.05);
    var fondos = [c.fondo, superficie];
    var alertaFondo = mezcla(c.fondo, oscuro ? "#ffc592" : "#8a3100", 0.14);
    return {
      base: oscuro ? "dark" : "light",
      vars: {
        "color-scheme": oscuro ? "dark" : "light",
        bg: c.fondo,
        surface: superficie,
        ink: c.texto,
        titulos: c.titulos,
        muted: hastaContraste(mezcla(c.texto, c.fondo, 0.35), fondos, 4.5, c.texto),
        line: mezcla(c.fondo, c.texto, 0.25),
        accent: c.enlaces,
        "accent-ink": extremo(c.enlaces),
        alert: hastaContraste(oscuro ? "#ffc592" : "#8a3100", [c.fondo, alertaFondo], 4.5, c.texto),
        "alert-bg": alertaFondo,
        focus: contraste(c.enlaces, c.fondo) >= 3 ? c.enlaces : c.texto
      }
    };
  }

  // ---- estado ----
  function acotar(n, min, max, def) {
    return typeof n === "number" && isFinite(n) ? Math.max(min, Math.min(max, n)) : def;
  }
  function limpiar(o) {
    o = o && typeof o === "object" ? o : {};
    return {
      tema: TEMAS.indexOf(o.tema) >= 0 ? o.tema : DEF.tema,
      fuente: FUENTES.indexOf(o.fuente) >= 0 ? o.fuente : DEF.fuente,
      fs: acotar(o.fs, PASOS_FS[0], PASOS_FS[PASOS_FS.length - 1], DEF.fs),
      ancho: o.ancho === ANCHO.completo ? ANCHO.completo : acotar(o.ancho, ANCHO.min, ANCHO.max, DEF.ancho),
      just: o.just === true,
      bionic: o.bionic === true,
      focus: o.focus === true,
      colores: limpiarColores(o.colores)
    };
  }
  function cargar() {
    try {
      var raw = global.localStorage.getItem(KEY);
      return limpiar(raw ? JSON.parse(raw) : null);
    } catch (e) {
      return limpiar(null);
    }
  }
  function guardar(s) {
    try { global.localStorage.setItem(KEY, JSON.stringify(s)); } catch (e) { /* sin almacenamiento: vale solo esta visita */ }
  }
  function paso(fs, dir) {
    var i = 0;
    for (var k = 0; k < PASOS_FS.length; k++) if (PASOS_FS[k] <= fs) i = k;
    return PASOS_FS[Math.max(0, Math.min(PASOS_FS.length - 1, i + dir))];
  }
  function anchoMas(ancho, dir) {
    if (ancho === ANCHO.completo) return dir < 0 ? ANCHO.max : ANCHO.completo;
    if (ancho >= ANCHO.max && dir > 0) return ANCHO.completo;
    return acotar(ancho + dir * ANCHO.paso, ANCHO.min, ANCHO.max, DEF.ancho);
  }
  // Colores del tema que se ve ahora, para empezar a personalizar desde ellos.
  function coloresActuales() {
    var cs = global.getComputedStyle(global.document.documentElement);
    var leer = function (v, def) { return hex6(cs.getPropertyValue(v).trim()) || def; };
    return {
      fondo: leer("--bg", "#ffffff"), texto: leer("--ink", "#222222"),
      enlaces: leer("--accent", "#0a5a3c"), titulos: leer("--titulos", "#222222")
    };
  }

  function aplicar(s) {
    var h = global.document.documentElement;
    VARS.concat(["color-scheme"]).forEach(function (v) {
      h.style.removeProperty(v === "color-scheme" ? v : "--" + v);
    });
    var colores = s.tema === "custom" ? s.colores : null;
    if (s.tema === "auto" || (s.tema === "custom" && !colores)) {
      h.removeAttribute("data-theme");
    } else if (colores) {
      var p = paleta(colores);
      h.setAttribute("data-theme", "custom");
      Object.keys(p.vars).forEach(function (k) {
        h.style.setProperty(k === "color-scheme" ? k : "--" + k, p.vars[k]);
      });
    } else {
      h.setAttribute("data-theme", s.tema);
    }
    h.setAttribute("data-font", s.fuente);
    h.setAttribute("data-just", s.just ? "1" : "0");
    h.setAttribute("data-bionic", s.bionic ? "1" : "0");
    h.setAttribute("data-focus", s.focus ? "1" : "0");
    h.style.setProperty("--fs", String(s.fs));
    h.style.setProperty("--ancho", s.ancho === ANCHO.completo ? "none" : s.ancho + "px");
  }

  var Tema = {
    KEY: KEY, DEF: DEF, PASOS_FS: PASOS_FS, ANCHO: ANCHO, CLAVES_COLOR: CLAVES_COLOR,
    cargar: cargar, guardar: guardar, aplicar: aplicar, limpiar: limpiar, limpiarColores: limpiarColores,
    paso: paso, anchoMas: anchoMas, paleta: paleta, contraste: contraste, coloresActuales: coloresActuales
  };

  if (typeof module !== "undefined" && module.exports) {
    module.exports = Tema;
  } else {
    global.Tema = Tema;
    aplicar(cargar());
  }
})(typeof window !== "undefined" ? window : globalThis);
