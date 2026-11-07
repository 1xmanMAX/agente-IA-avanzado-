/* Calculadora de obra — mini app de PixAgent. Sin IA, sin eval: parser propio. ES2019 / Safari iOS 15. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var STORE = "pixagent.calc.v1";
  var store = { hist: [], angle: "deg", dos: null, tab: "sci", ucat: "longitud", use: {} };
  try { var raw = localStorage.getItem(STORE); if (raw) { var d = JSON.parse(raw); Object.keys(store).forEach(function (k) { if (d[k] !== undefined) store[k] = d[k]; }); } } catch (e) { /* sin almacenamiento */ }
  if (!store.use || typeof store.use !== "object") store.use = {};
  var COARSE = window.matchMedia("(pointer: coarse)").matches;
  function persist() { try { localStorage.setItem(STORE, JSON.stringify(store)); } catch (e) { /* ignorar */ } }

  var toastTimer;
  function toast(msg) {
    var t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2400);
    if (window.PixAgent && PixAgent.embedded) PixAgent.toast(msg);
  }
  function copyText(text) {
    var done = function () { toast("Copiado al portapapeles"); };
    var fallback = function () {
      var ta = document.createElement("textarea"); ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0"; document.body.appendChild(ta); ta.select();
      try { document.execCommand("copy"); done(); } catch (e) { toast("No se pudo copiar"); }
      document.body.removeChild(ta);
    };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, fallback); else fallback();
  }
  function saveJSON(name, data) {
    if (!window.PixAgent || !PixAgent.save) { toast("El SDK de PixAgent no está disponible"); return; }
    var p = function (n) { return (n < 10 ? "0" : "") + n; }, d = new Date();
    var stamp = d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "_" + p(d.getHours()) + p(d.getMinutes()) + p(d.getSeconds());
    data.generado = d.toISOString(); data.app = "Calculadora de obra";
    PixAgent.save(name + "_" + stamp + ".json", data, { folder: "calculadora" })
      .then(function (path) { toast("Guardado en " + path); })
      .catch(function (e) { toast("No se pudo guardar: " + ((e && e.message) || e)); });
  }

  /* ---------- formato numérico ---------- */
  function num(v) {
    if (typeof v === "number") return v;
    var s = String(v == null ? "" : v).trim().replace(/\s/g, "");
    if (!s) return NaN;
    // "1.234,5" → 1234.5 ; "1,5" → 1.5 ; "1,234.5" → 1234.5
    if (s.indexOf(",") >= 0 && s.indexOf(".") >= 0) {
      if (s.lastIndexOf(",") > s.lastIndexOf(".")) s = s.replace(/\./g, "").replace(",", "."); else s = s.replace(/,/g, "");
    } else s = s.replace(",", ".");
    return parseFloat(s);
  }
  function fmt(x, dec) {
    if (typeof x !== "number" || !isFinite(x)) return "—";
    if (dec !== undefined) return parseFloat(x.toFixed(dec)).toString().replace(/\.?0+$/, function (m) { return m.indexOf(".") >= 0 ? "" : m; });
    var a = Math.abs(x);
    if (a !== 0 && (a >= 1e15 || a < 1e-9)) return x.toExponential(8).replace(/\.?0+e/, "e");
    var s = parseFloat(x.toPrecision(12)).toString();
    return s;
  }
  function fmtU(x, u, dec) { var s = fmt(x, dec); return s === "—" ? s : s + (u ? '<small>' + u + "</small>" : ""); }

  /* ---------- parser seguro (sin eval) ---------- */
  var FUNCS = {
    sin: function (x) { return Math.sin(toRad(x)); }, cos: function (x) { return Math.cos(toRad(x)); }, tan: function (x) { return Math.tan(toRad(x)); },
    asin: function (x) { return fromRad(Math.asin(x)); }, acos: function (x) { return fromRad(Math.acos(x)); }, atan: function (x) { return fromRad(Math.atan(x)); },
    sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh,
    sqrt: Math.sqrt, cbrt: Math.cbrt, log: Math.log10, ln: Math.log, exp: Math.exp, abs: Math.abs,
    round: Math.round, floor: Math.floor, ceil: Math.ceil
  };
  var CONSTS = { pi: Math.PI, e: Math.E };
  var ANS = 0;
  function toRad(x) { return store.angle === "deg" ? x * Math.PI / 180 : x; }
  function fromRad(x) { return store.angle === "deg" ? x * 180 / Math.PI : x; }

  function tokenize(src) {
    var s = src.replace(/×|·/g, "*").replace(/÷|:/g, "/").replace(/−|–/g, "-").replace(/π/g, "pi").replace(/√/g, "sqrt").replace(/²/g, "^2").replace(/³/g, "^3");
    var toks = [], i = 0;
    while (i < s.length) {
      var c = s[i];
      if (c === " ") { i++; continue; }
      if (/[0-9.,]/.test(c)) {
        var j = i; while (j < s.length && /[0-9.,]/.test(s[j])) j++;
        var t = s.slice(i, j);
        if (/^[.,]$/.test(t)) throw new Error("Número incompleto");
        var v = num(t);
        if (isNaN(v)) throw new Error("Número no válido: " + t);
        toks.push({ t: "num", v: v }); i = j; continue;
      }
      if (/[a-zA-Z_]/.test(c)) {
        var k = i; while (k < s.length && /[a-zA-Z_0-9]/.test(s[k])) k++;
        toks.push({ t: "id", v: s.slice(i, k) }); i = k; continue;
      }
      if ("+-*/^%()!".indexOf(c) >= 0) { toks.push({ t: "op", v: c }); i++; continue; }
      throw new Error("Carácter no reconocido: " + c);
    }
    return toks;
  }
  function evaluate(src) {
    var toks = tokenize(src), p = 0;
    if (!toks.length) return null;
    function peek() { return toks[p]; }
    function isOp(v) { var t = peek(); return t && t.t === "op" && t.v === v; }
    function next() { return toks[p++]; }
    function expr() {
      var v = term();
      while (isOp("+") || isOp("-")) { var o = next().v, r = term(); v = o === "+" ? v + r : v - r; }
      return v;
    }
    function term() {
      var v = unary();
      for (;;) {
        if (isOp("*") || isOp("/")) { var o = next().v, r = unary(); if (o === "/" && r === 0) throw new Error("División entre cero"); v = o === "*" ? v * r : v / r; }
        else if (peek() && (peek().t === "num" || peek().t === "id" || isOp("("))) { v = v * unary(); }  // multiplicación implícita
        else break;
      }
      return v;
    }
    function unary() {
      if (isOp("-")) { next(); return -unary(); }
      if (isOp("+")) { next(); return unary(); }
      return power();
    }
    function power() {
      var b = postfix();
      if (isOp("^")) { next(); var e = unary(); return Math.pow(b, e); }
      return b;
    }
    function postfix() {
      var v = primary();
      for (;;) {
        if (isOp("%")) { next(); v = v / 100; }
        else if (isOp("!")) { next(); if (v < 0 || v !== Math.floor(v) || v > 170) throw new Error("Factorial solo de enteros 0–170"); var f = 1; for (var i = 2; i <= v; i++) f *= i; v = f; }
        else break;
      }
      return v;
    }
    function primary() {
      var t = next();
      if (!t) throw new Error("Expresión incompleta");
      if (t.t === "num") return t.v;
      if (t.t === "op" && t.v === "(") { var v = expr(); if (!isOp(")")) throw new Error("Falta cerrar paréntesis"); next(); return v; }
      if (t.t === "id") {
        var name = t.v.toLowerCase();
        if (name === "ans") return ANS;
        if (CONSTS[name] !== undefined) return CONSTS[name];
        if (FUNCS[name]) {
          var arg;
          if (isOp("(")) { next(); arg = expr(); if (!isOp(")")) throw new Error("Falta cerrar paréntesis en " + name); next(); }
          else arg = unary();                           // sin 30, sqrt 2
          var r = FUNCS[name](arg);
          if (typeof r !== "number" || isNaN(r)) throw new Error("Fuera de dominio: " + name);
          return r;
        }
        throw new Error("Desconocido: " + t.v);
      }
      throw new Error("Inesperado: " + t.v);
    }
    var result = expr();
    if (p < toks.length) throw new Error("Inesperado: " + toks[p].v);
    if (typeof result !== "number" || isNaN(result)) throw new Error("Resultado no válido");
    return result;
  }
  function clean(x) { return Math.abs(x) < 1e-12 ? 0 : parseFloat(x.toPrecision(13)); }

  /* ---------- científica: interfaz ---------- */
  var exprEl = $("#expr"), outEl = $("#out");
  function preview() {
    var s = exprEl.value.trim();
    outEl.className = "out";
    if (!s) { outEl.textContent = ""; return; }
    try { var v = evaluate(s); outEl.textContent = v === null ? "" : "= " + fmt(clean(v)); }
    catch (e) { outEl.textContent = ""; }
  }
  function commit() {
    var s = exprEl.value.trim();
    if (!s) return;
    try {
      var v = clean(evaluate(s));
      ANS = v;
      outEl.className = "out final"; outEl.textContent = "= " + fmt(v);
      $("#ansHint").textContent = "Ans = " + fmt(v);
      store.hist.unshift({ e: s, r: fmt(v) }); store.hist = store.hist.slice(0, 60); persist(); renderHist();
      exprEl.dataset.final = "1";
    } catch (e) { outEl.className = "out err"; outEl.textContent = e.message; }
  }
  function insert(txt) {
    var el = exprEl;
    if (el.dataset.final === "1") {                          // tras "=", un operador continúa con Ans; un número empieza de cero
      el.dataset.final = "";
      if (/^[+\-−×÷*/^%]/.test(txt)) el.value = "Ans"; else el.value = "";
    }
    var a = el.selectionStart == null ? el.value.length : el.selectionStart, b = el.selectionEnd == null ? a : el.selectionEnd;
    el.value = el.value.slice(0, a) + txt + el.value.slice(b);
    var pos = a + txt.length; try { el.setSelectionRange(pos, pos); } catch (e) { /* ok */ }
    preview();
  }
  function renderHist() {
    var h = $("#hist"); h.innerHTML = "";
    $("#histCount").textContent = store.hist.length ? store.hist.length + " cálculos" : "";
    if (!store.hist.length) { h.innerHTML = '<div class="none">Los cálculos que confirmes con = aparecen aquí. Toca uno para reutilizar su resultado.</div>'; return; }
    store.hist.forEach(function (it) {
      var b = document.createElement("button"); b.type = "button";
      b.innerHTML = '<span class="e"></span><span class="r"></span>';
      b.firstChild.textContent = it.e; b.lastChild.textContent = "= " + it.r;
      b.onclick = function () { exprEl.dataset.final = ""; insert(it.r); exprEl.focus(); };
      h.appendChild(b);
    });
  }
  $("#keys").addEventListener("click", function (e) {
    var b = e.target.closest("button"); if (!b) return;
    if (b.dataset.ins) insert(b.dataset.ins);
    else if (b.dataset.act === "clear") { exprEl.value = ""; exprEl.dataset.final = ""; preview(); }
    else if (b.dataset.act === "back") { exprEl.dataset.final = ""; var a = exprEl.selectionStart == null ? exprEl.value.length : exprEl.selectionStart; if (a > 0) { exprEl.value = exprEl.value.slice(0, a - 1) + exprEl.value.slice(a); try { exprEl.setSelectionRange(a - 1, a - 1); } catch (x) { /* ok */ } } preview(); }
    else if (b.dataset.act === "neg") { exprEl.dataset.final = ""; exprEl.value = exprEl.value.charAt(0) === "-" ? exprEl.value.slice(1) : "-" + exprEl.value; preview(); }
    else if (b.dataset.act === "eq") commit();
    if (!window.matchMedia("(pointer: coarse)").matches) exprEl.focus();
  });
  exprEl.addEventListener("input", function () { exprEl.dataset.final = ""; preview(); });
  exprEl.addEventListener("keydown", function (e) {
    if (e.key === "Enter" || e.key === "=") { e.preventDefault(); commit(); }
    else if (e.key === "Escape") { exprEl.value = ""; exprEl.dataset.final = ""; preview(); }
    else if (e.key === "ArrowUp" && store.hist.length) { e.preventDefault(); exprEl.value = store.hist[0].e; exprEl.dataset.final = ""; preview(); }
    else if (e.key.length === 1 && exprEl.dataset.final === "1") { exprEl.dataset.final = ""; if (/^[+\-*/^%]$/.test(e.key)) exprEl.value = "Ans"; else exprEl.value = ""; }
  });
  document.addEventListener("keydown", function (e) {
    if (store.tab !== "sci" || e.target === exprEl || /INPUT|SELECT|TEXTAREA/.test(e.target.tagName)) return;
    if (e.key.length === 1 && /[0-9+\-*/^%().,a-z]/i.test(e.key) || e.key === "Enter" || e.key === "Backspace") { exprEl.focus(); }
  });
  $$("#segAngle button").forEach(function (b) {
    b.setAttribute("aria-pressed", String(store.angle === b.dataset.v));
    b.onclick = function () { store.angle = b.dataset.v; persist(); $$("#segAngle button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); }); preview(); };
  });
  $("#btnHistClear").onclick = function () { store.hist = []; persist(); renderHist(); };
  $("#btnHistSave").onclick = function () {
    if (!store.hist.length) { toast("No hay cálculos que guardar"); return; }
    saveJSON("historial", { tipo: "historial", angulo: store.angle, calculos: store.hist.map(function (h) { return { expresion: h.e, resultado: h.r }; }) });
  };
  renderHist();

  /* ---------- unidades ---------- */
  var UNITS = {
    longitud: { name: "Longitud", units: [["mm", 0.001], ["cm", 0.01], ["m", 1], ["km", 1000], ["pulg", 0.0254], ["pie", 0.3048], ["yd", 0.9144], ["milla", 1609.344]] },
    area: { name: "Área", units: [["mm²", 1e-6], ["cm²", 1e-4], ["m²", 1], ["ha", 1e4], ["km²", 1e6], ["pulg²", 0.00064516], ["pie²", 0.09290304], ["yd²", 0.83612736], ["acre", 4046.8564224]] },
    volumen: { name: "Volumen", units: [["cm³", 1e-6], ["L", 1e-3], ["m³", 1], ["pulg³", 1.6387064e-5], ["pie³", 0.028316846592], ["yd³", 0.764554857984], ["gal (US)", 0.003785411784], ["barril", 0.158987294928]] },
    masa: { name: "Masa", units: [["g", 0.001], ["kg", 1], ["t", 1000], ["lb", 0.45359237], ["oz", 0.028349523125], ["qq (100 kg)", 100], ["bolsa cemento 42,5 kg", 42.5]] },
    presion: { name: "Presión / esfuerzo", units: [["Pa", 1], ["kPa", 1e3], ["MPa", 1e6], ["bar", 1e5], ["atm", 101325], ["psi", 6894.757293168], ["kgf/cm²", 98066.5], ["mmHg", 133.322387415], ["m.c.a.", 9806.65]] },
    fuerza: { name: "Fuerza", units: [["N", 1], ["kN", 1000], ["kgf", 9.80665], ["tf", 9806.65], ["lbf", 4.4482216152605]] },
    angulo: { name: "Ángulo / pendiente", special: true, units: [["°", 0], ["rad", 0], ["%", 0], ["1:n", 0], ["gon", 0]] }
  };
  var angleToRad = {
    "°": function (v) { return v * Math.PI / 180; }, "rad": function (v) { return v; }, "%": function (v) { return Math.atan(v / 100); },
    "1:n": function (v) { return v === 0 ? NaN : Math.atan(1 / v); }, "gon": function (v) { return v * Math.PI / 200; }
  };
  var radToAngle = {
    "°": function (r) { return r * 180 / Math.PI; }, "rad": function (r) { return r; }, "%": function (r) { return Math.tan(r) * 100; },
    "1:n": function (r) { var t = Math.tan(r); return t === 0 ? Infinity : 1 / t; }, "gon": function (r) { return r * 200 / Math.PI; }
  };
  function convert(cat, v, from, to) {
    var c = UNITS[cat];
    if (c.special) return radToAngle[to](angleToRad[from](v));
    var f = {}; c.units.forEach(function (u) { f[u[0]] = u[1]; });
    return v * f[from] / f[to];
  }
  var ucat = UNITS[store.ucat] ? store.ucat : "longitud";
  var COMMON_CATS = ["longitud", "area", "volumen", "angulo"], catsMore = false;
  function renderCats() {
    var box = $("#unitCats"); box.innerHTML = "";
    var showAll = catsMore || COMMON_CATS.indexOf(ucat) < 0;
    var keys = COMMON_CATS.concat(Object.keys(UNITS).filter(function (k) { return COMMON_CATS.indexOf(k) < 0; }));
    keys.forEach(function (k) {
      if (!showAll && COMMON_CATS.indexOf(k) < 0) return;
      var b = document.createElement("button"); b.type = "button"; b.className = "chip"; b.textContent = UNITS[k].name; b.setAttribute("aria-pressed", String(k === ucat));
      b.onclick = function () { ucat = k; store.ucat = k; persist(); renderCats(); fillUnits(); doConvert(); };
      box.appendChild(b);
    });
    if (!showAll) {
      var m = document.createElement("button"); m.type = "button"; m.className = "chip more"; m.textContent = "Más…"; m.title = "Masa, presión y fuerza";
      m.onclick = function () { catsMore = true; renderCats(); };
      box.appendChild(m);
    }
  }
  function fillUnits() {
    var from = $("#uFrom"), to = $("#uTo"); from.innerHTML = ""; to.innerHTML = "";
    UNITS[ucat].units.forEach(function (u, i) {
      var o1 = document.createElement("option"), o2 = document.createElement("option");
      o1.value = o2.value = u[0]; o1.textContent = o2.textContent = u[0]; from.appendChild(o1); to.appendChild(o2);
    });
    from.selectedIndex = ucat === "angulo" ? 2 : ucat === "presion" ? 6 : 2;
    to.selectedIndex = ucat === "angulo" ? 0 : ucat === "presion" ? 2 : Math.min(UNITS[ucat].units.length - 1, from.selectedIndex === 2 ? 1 : 2);
    if (from.selectedIndex === to.selectedIndex) to.selectedIndex = (to.selectedIndex + 1) % UNITS[ucat].units.length;
    $("#uNote").hidden = ucat !== "angulo";
    $("#uNote").textContent = "Pendiente: % = tan(θ)·100; 1:n es la relación 1 vertical por n horizontal (una rampa 1:12 ≈ 8,33 % ≈ 4,76°).";
  }
  function doConvert() {
    var v = num($("#uVal").value), from = $("#uFrom").value, to = $("#uTo").value;
    var out = $("#uOut"), table = $("#uAll"); table.innerHTML = "";
    if (isNaN(v)) { out.textContent = "—"; return; }
    var r = convert(ucat, v, from, to);
    out.textContent = isFinite(r) ? fmt(clean(r)) + " " + to.split(" (")[0] : "∞";
    UNITS[ucat].units.forEach(function (u) {
      var tr = document.createElement("tr"); var x = convert(ucat, v, from, u[0]);
      tr.innerHTML = "<td></td><td></td>"; tr.firstChild.textContent = u[0]; tr.lastChild.textContent = isFinite(x) ? fmt(clean(x)) : "∞";
      table.appendChild(tr);
    });
  }
  ["#uVal", "#uFrom", "#uTo"].forEach(function (id) { $(id).addEventListener("input", doConvert); $(id).addEventListener("change", doConvert); });
  $("#uSwap").onclick = function () { var a = $("#uFrom").value; $("#uFrom").value = $("#uTo").value; $("#uTo").value = a; doConvert(); };
  $("#uCopy").onclick = function () { copyText($("#uVal").value + " " + $("#uFrom").value + " = " + $("#uOut").textContent); };
  $("#uSave").onclick = function () { saveJSON("conversion", { tipo: "conversion", categoria: UNITS[ucat].name, valor: num($("#uVal").value), de: $("#uFrom").value, a: $("#uTo").value, resultado: $("#uOut").textContent }); };
  renderCats(); fillUnits(); doConvert();

  /* ---------- obra ---------- */
  var DOS_DEFAULT = [
    { fc: 140, prop: "1 : 2,5 : 3,5", cem: 7.0, arena: 0.56, grava: 0.57, agua: 184 },
    { fc: 175, prop: "1 : 2,5 : 2,5", cem: 8.4, arena: 0.54, grava: 0.55, agua: 185 },
    { fc: 210, prop: "1 : 2 : 2", cem: 9.7, arena: 0.52, grava: 0.53, agua: 186 },
    { fc: 280, prop: "1 : 1,5 : 1,5", cem: 11.5, arena: 0.47, grava: 0.51, agua: 190 }
  ];
  var dos = Array.isArray(store.dos) && store.dos.length === 4 ? store.dos : JSON.parse(JSON.stringify(DOS_DEFAULT));
  function fillFc() {
    $$("select.fc").forEach(function (s) {
      var cur = s.value || "210"; s.innerHTML = "";
      dos.forEach(function (d) { var o = document.createElement("option"); o.value = d.fc; o.textContent = "f'c " + d.fc + " kg/cm²"; s.appendChild(o); });
      s.value = cur;
    });
  }
  function renderDos() {
    var t = $("#dosTable");
    t.innerHTML = "<thead><tr><th>f'c (kg/cm²)</th><th>Proporción c:a:p</th><th>Cemento (bolsas)</th><th>Arena (m³)</th><th>Grava (m³)</th><th>Agua (L)</th></tr></thead>";
    var tb = document.createElement("tbody");
    dos.forEach(function (d, i) {
      var tr = document.createElement("tr"); if (String(d.fc) === $("#cn_fc").value) tr.className = "sel";
      tr.innerHTML = "<td>" + d.fc + "</td><td>" + d.prop + "</td>" +
        ["cem", "arena", "grava", "agua"].map(function (k) { return '<td><input class="inp" inputmode="decimal" data-i="' + i + '" data-k="' + k + '" value="' + d[k] + '" aria-label="' + k + " para f'c " + d.fc + '"></td>'; }).join("");
      tb.appendChild(tr);
    });
    t.appendChild(tb);
    $$("input", tb).forEach(function (inp) { inp.addEventListener("input", function () { var v = num(inp.value); if (!isNaN(v)) { dos[+inp.dataset.i][inp.dataset.k] = v; store.dos = dos; persist(); calcAll(); } }); });
  }
  $("#dosReset").onclick = function () { dos = JSON.parse(JSON.stringify(DOS_DEFAULT)); store.dos = null; persist(); renderDos(); calcAll(); toast("Dosificación restablecida"); };

  function materials(vol, fc, waste) {
    var d = dos.filter(function (x) { return String(x.fc) === String(fc); })[0] || dos[2];
    var k = vol * (1 + (waste || 0) / 100);
    return { volDis: k, fc: d.fc, prop: d.prop, cem: d.cem * k, arena: d.arena * k, grava: d.grava * k, agua: d.agua * k };
  }
  function row(label, value, unit, dec, big) { return '<div class="res' + (big ? " big" : "") + '"><span class="l">' + label + '</span><span class="v">' + fmtU(value, unit, dec) + "</span></div>"; }
  function matRows(m) {
    return row("Volumen con desperdicio", m.volDis, "m³", 2) +
      row("Cemento (bolsas 42,5 kg)", Math.ceil(m.cem), "bolsas", 0) + row("Arena gruesa", m.arena, "m³", 2) + row("Grava / piedra chancada", m.grava, "m³", 2) + row("Agua", m.agua, "L", 0) +
      '<div class="res"><span class="l">Dosificación f\'c ' + m.fc + '</span><span class="v" style="font-weight:500;font-size:13px">' + m.prop + "</span></div>";
  }
  var lastData = {};
  var CALCS = {
    losa: function () {
      var L = num($("#lo_l").value), A = num($("#lo_a").value), e = num($("#lo_e").value) / 100, w = num($("#lo_w").value) || 0;
      var area = L * A, vol = area * e, m = materials(vol, $("#lo_fc").value, w);
      lastData.losa = { tipo: "losa", largo_m: L, ancho_m: A, espesor_cm: e * 100, area_m2: area, volumen_m3: vol, desperdicio_pct: w, materiales: m };
      $("#lo_res").innerHTML = row("Área", area, "m²", 2, true) + row("Volumen de concreto", vol, "m³", 3, true) + matRows(m);
    },
    zapata: function () {
      var L = num($("#za_l").value), A = num($("#za_a").value), h = num($("#za_h").value) / 100, n = Math.max(1, Math.round(num($("#za_n").value) || 1)), w = num($("#za_w").value) || 0;
      var v1 = L * A * h, vol = v1 * n, m = materials(vol, $("#za_fc").value, w);
      lastData.zapata = { tipo: "zapata", largo_m: L, ancho_m: A, altura_cm: h * 100, cantidad: n, volumen_unitario_m3: v1, volumen_total_m3: vol, desperdicio_pct: w, materiales: m };
      $("#za_res").innerHTML = row("Volumen por zapata", v1, "m³", 3) + row("Volumen total (" + n + ")", vol, "m³", 3, true) + matRows(m);
    },
    columna: function () {
      var b = num($("#co_b").value) / 100, h = num($("#co_h").value) / 100, alt = num($("#co_alt").value), n = Math.max(1, Math.round(num($("#co_n").value) || 1)), w = num($("#co_w").value) || 0;
      var sec = b * h, v1 = sec * alt, vol = v1 * n, m = materials(vol, $("#co_fc").value, w);
      lastData.columna = { tipo: "columna", b_cm: b * 100, h_cm: h * 100, altura_m: alt, cantidad: n, seccion_m2: sec, volumen_unitario_m3: v1, volumen_total_m3: vol, desperdicio_pct: w, materiales: m };
      $("#co_res").innerHTML = row("Sección", sec * 1e4, "cm²", 0) + row("Volumen por columna", v1, "m³", 3) + row("Volumen total (" + n + ")", vol, "m³", 3, true) + matRows(m);
    },
    concreto: function () {
      var v = num($("#cn_v").value), w = num($("#cn_w").value) || 0, m = materials(v, $("#cn_fc").value, w);
      lastData.concreto = { tipo: "concreto", volumen_m3: v, desperdicio_pct: w, materiales: m, dosificacion_tabla: dos };
      $("#cn_res").innerHTML = row("Volumen", v, "m³", 2, true) + matRows(m);
      $$("#dosTable tbody tr").forEach(function (tr, i) { tr.className = String(dos[i].fc) === $("#cn_fc").value ? "sel" : ""; });
    },
    ladrillos: function () {
      var l = num($("#la_l").value) / 100, h = num($("#la_h").value) / 100, j = num($("#la_j").value) / 100, area = num($("#la_area").value), w = num($("#la_w").value) || 0;
      var perM2 = 1 / ((l + j) * (h + j)), total = perM2 * area, totalW = total * (1 + w / 100);
      var mortero = (1 - perM2 * l * h);           // fracción de la cara del muro ocupada por juntas
      lastData.ladrillos = { tipo: "ladrillos", largo_cm: l * 100, alto_cm: h * 100, junta_cm: j * 100, area_m2: area, ladrillos_por_m2: perM2, total: total, total_con_desperdicio: Math.ceil(totalW), desperdicio_pct: w };
      $("#la_res").innerHTML = row("Ladrillos por m²", perM2, "und/m²", 1, true) + row("Total para " + fmt(area, 2) + " m²", Math.ceil(total), "und", 0) + row("Con " + fmt(w, 1) + " % de desperdicio", Math.ceil(totalW), "und", 0, true) + row("Juntas (fracción de cara)", mortero * 100, "%", 1);
    },
    pendiente: function () {
      var h = num($("#pe_h").value), d = num($("#pe_d").value);
      var pct = h / d * 100, deg = Math.atan2(h, d) * 180 / Math.PI, n = h ? d / h : Infinity, len = Math.sqrt(h * h + d * d);
      var eh = num($("#es_h").value) * 100, ech = num($("#es_ch").value);
      var steps = Math.max(1, Math.round(eh / ech)), ch = eh / steps, huella = 63 - 2 * ch, blondel = 2 * ch + huella;
      var ok = ch >= 15 && ch <= 19 && huella >= 25 && huella <= 32;
      var angEs = Math.atan2(ch, huella) * 180 / Math.PI, devEs = (steps - 1) * huella / 100;
      lastData.pendiente = { tipo: "pendiente", desnivel_m: h, distancia_m: d, pendiente_pct: pct, angulo_deg: deg, razon_1_n: n, longitud_rampa_m: len,
        escalera: { altura_cm: eh, contrahuella_cm: ch, huella_cm: huella, peldanos: steps, desarrollo_m: devEs, angulo_deg: angEs } };
      $("#pe_res").innerHTML = row("Pendiente", pct, "%", 2, true) + row("Ángulo", deg, "°", 2) +
        '<div class="res"><span class="l">Relación vertical : horizontal</span><span class="v">1 : ' + (isFinite(n) ? fmt(n, 2) : "∞") + "</span></div>" + row("Longitud de la rampa", len, "m", 2) +
        '<div class="res"><span class="l">Accesibilidad</span><span class="v" style="font-size:12px;font-weight:500">' + (pct <= 8 ? "≤ 8 %: apta para rampa accesible" : pct <= 12 ? "8–12 %: rampa corta o con descansos" : "> 12 %: no apta para rampa peatonal") + "</span></div>";
      $("#es_res").innerHTML = row("Peldaños", steps, "", 0, true) + row("Contrahuella real", ch, "cm", 1) + row("Huella sugerida (2CH + H = 63)", huella, "cm", 1) + row("Desarrollo en planta", devEs, "m", 2) + row("Ángulo de la escalera", angEs, "°", 1) +
        '<div class="res"><span class="l">Comodidad</span><span class="blondel ' + (ok ? "ok" : "bad") + '">' + (ok ? "Blondel " + fmt(blondel, 1) + " cm · cómoda" : "Revisa: CH 15–19 cm y H 25–32 cm") + "</span></div>";
    }
  };
  function calcAll() { Object.keys(CALCS).forEach(function (k) { try { CALCS[k](); } catch (e) { /* entradas incompletas */ } }); }
  /* orden por uso: las 3 más usadas abiertas arriba, el resto plegadas en lista (se reordena al abrir la app) */
  var ORDER_DEFAULT = ["losa", "concreto", "ladrillos", "zapata", "columna", "pendiente"];
  function layoutObra() {
    var keys = ORDER_DEFAULT.slice().sort(function (a, b) { return (store.use[b] || 0) - (store.use[a] || 0) || ORDER_DEFAULT.indexOf(a) - ORDER_DEFAULT.indexOf(b); });
    var top = $("#obraTop"), more = $("#obraMore");
    keys.forEach(function (k, i) {
      var card = $('details.card[data-calc="' + k + '"]'); if (!card) return;
      card.open = i < 3; (i < 3 ? top : more).appendChild(card);
    });
  }
  var lastUseCard = null;
  function countUse(key) { if (!key) return; store.use[key] = (store.use[key] || 0) + 1; persist(); }
  $("#pane-obra").addEventListener("focusin", function (e) { var card = e.target.closest("details.card"); if (card && card !== lastUseCard && /INPUT|SELECT/.test(e.target.tagName)) { lastUseCard = card; countUse(card.dataset.calc); } });
  $("#pane-obra").addEventListener("toggle", function (e) { var card = e.target.closest && e.target.closest("details.card"); if (card && card === e.target && card.open && e.isTrusted) countUse(card.dataset.calc); }, true);
  function textOf(key) {
    var card = $('.card[data-calc="' + key + '"]');
    return card.querySelector("h2").firstChild.textContent.trim() + "\n" + $$(".res", card).map(function (r) { return r.querySelector(".l").textContent + ": " + r.querySelector(".v, .blondel").textContent.replace(/\s+/g, " ").trim(); }).join("\n");
  }
  $("#pane-obra").addEventListener("input", function (e) { var card = e.target.closest(".card"); if (card && CALCS[card.dataset.calc]) { CALCS[card.dataset.calc](); if (card.dataset.calc !== "concreto") CALCS.concreto(); } });
  $("#pane-obra").addEventListener("change", function (e) { var card = e.target.closest(".card"); if (card && CALCS[card.dataset.calc]) CALCS[card.dataset.calc](); });
  $("#pane-obra").addEventListener("click", function (e) {
    var b = e.target.closest("button[data-copy],button[data-save]"); if (!b) return;
    countUse(b.dataset.copy || b.dataset.save);
    if (b.dataset.copy) copyText(textOf(b.dataset.copy));
    else saveJSON(b.dataset.save, Object.assign({ resumen: textOf(b.dataset.save) }, lastData[b.dataset.save] || {}));
  });
  fillFc(); $("#cn_fc").value = "210"; renderDos(); calcAll(); layoutObra();

  /* ---------- campos numéricos: ↑/↓ ajustan (Shift = ×10), coma decimal, teclado virtual sin tapar ---------- */
  document.addEventListener("keydown", function (e) {
    var el = e.target; if (!el || el.tagName !== "INPUT" || !el.classList.contains("num")) return;
    if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
    e.preventDefault();
    var v = num(el.value); if (isNaN(v)) v = 0;
    var raw = String(el.value).replace(",", "."), dec = raw.indexOf(".") >= 0 ? Math.min(3, raw.split(".")[1].length) : 0;
    var step = (dec ? Math.pow(10, -dec) : 1) * (e.shiftKey ? 10 : 1);
    var nv = v + (e.key === "ArrowUp" ? step : -step);
    if (el.getAttribute("inputmode") === "numeric" || /_n$/.test(el.id)) nv = Math.max(1, Math.round(nv));
    el.value = fmt(parseFloat(nv.toFixed(Math.max(dec, 0))), Math.max(dec, 0));
    el.dispatchEvent(new Event("input", { bubbles: true }));
  });
  if (COARSE) document.addEventListener("focusin", function (e) { if (/INPUT|SELECT/.test(e.target.tagName) && e.target !== exprEl) setTimeout(function () { try { e.target.scrollIntoView({ block: "center", behavior: "smooth" }); } catch (x) { /* ok */ } }, 250); });

  /* ---------- pestañas ---------- */
  function setTab(t) {
    store.tab = t; persist();
    $$(".tabs [role=tab]").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.tab === t)); });
    ["sci", "units", "obra"].forEach(function (k) { $("#pane-" + k).hidden = k !== t; });
    if (t === "sci" && !window.matchMedia("(pointer: coarse)").matches) exprEl.focus();
  }
  $$(".tabs [role=tab]").forEach(function (b) { b.onclick = function () { setTab(b.dataset.tab); }; });
  setTab(["sci", "units", "obra"].indexOf(store.tab) >= 0 ? store.tab : "sci");
  $("#ansHint").textContent = "Ans = 0";
  preview();
})();
