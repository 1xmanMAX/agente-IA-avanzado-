/* IA local — mini app de PixAgent.
   Estado de los motores locales (Ollama / llama.cpp / LM Studio), guía de instalación, kit de
   modelos recomendado con descarga en vivo, modelo por tarea y una prueba rápida con imagen.
   Sin IA en la nube: todo pasa por /api/local/*. ES2019 / Safari iOS 15. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  var CAP_LABEL = { vision: "Visión", ocr: "OCR", video: "Vídeo", text: "Texto" };
  var CAP_ORDER = ["vision", "ocr", "video", "text"];
  var TASK_LABEL = { vision: "visión", ocr: "OCR", text: "texto" };

  var st = null;            // último /api/local/status
  var pulls = {};           // model -> {pct, status, error}
  var tryFile = null, tryPath = null, tryUrl = null;
  var busy = { caption: false, ocr: false };
  var platform = detectPlatform();
  var lightbox = null;

  /* ---------------- utilidades de interfaz ---------------- */
  var toastTimer;
  function toast(msg) {
    var t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2600);
  }
  function notice(kind, title, body, actions) {
    var box = $("#notices");
    var el = document.createElement("div");
    el.className = "notice " + kind;
    var icon = kind === "ok" ? "i-check" : kind === "err" ? "i-alert" : kind === "warn" ? "i-alert" : "i-info";
    el.innerHTML = '<svg class="i"><use href="#' + icon + '"/></svg>' +
      '<div class="body"><b>' + esc(title) + "</b>" + (body ? "<span>" + esc(body) + "</span>" : "") + (actions ? '<div class="acts"></div>' : "") + "</div>" +
      '<button class="close" type="button" aria-label="Cerrar"><svg class="i sm"><use href="#i-x"/></svg></button>';
    el.querySelector(".close").onclick = function () { el.remove(); };
    if (actions) actions.forEach(function (a) { el.querySelector(".acts").appendChild(a); });
    box.insertBefore(el, box.firstChild);
    while (box.children.length > 2) box.removeChild(box.lastChild);
    return el;
  }
  function friendlyError(e) {
    var m = (e && e.message) || String(e);
    if (/Failed to fetch|NetworkError|network/i.test(m)) return "No hay conexión con el servidor de PixAgent.";
    return m.length > 300 ? m.slice(0, 300) + "…" : m;
  }
  function copy(text, okMsg) {
    var done = function () { toast(okMsg || "Copiado"); };
    if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, function () { fallbackCopy(text); done(); });
    else { fallbackCopy(text); done(); }
  }
  function fallbackCopy(text) {
    var ta = document.createElement("textarea"); ta.value = text; ta.setAttribute("readonly", ""); ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select(); try { document.execCommand("copy"); } catch (e) { /* sin portapapeles */ } ta.remove();
  }
  function cmdBox(cmd) {
    var d = document.createElement("div"); d.className = "cmd";
    d.innerHTML = "<code>" + esc(cmd) + '</code><button class="btn sm icon ghost" type="button" aria-label="Copiar comando" title="Copiar"><svg class="i sm"><use href="#i-copy"/></svg></button>';
    d.querySelector("button").onclick = function () { copy(cmd, "Comando copiado"); };
    return d;
  }
  function fmtGb(gb) { return gb == null ? "" : (gb < 1 ? Math.round(gb * 1000) + " MB" : (Math.round(gb * 10) / 10).toString().replace(".", ",") + " GB"); }
  function fmtSec(s) { return s == null ? "" : (s < 10 ? (Math.round(s * 10) / 10).toString().replace(".", ",") : Math.round(s)) + " s"; }
  function detectPlatform() {
    var ua = navigator.userAgent || "";
    if (/android/i.test(ua) || /iphone|ipad|ipod/i.test(ua) || (/Macintosh/.test(ua) && navigator.maxTouchPoints > 1)) return "mobile";
    if (/windows/i.test(ua)) return "win";
    if (/mac os x|macintosh/i.test(ua)) return "mac";
    if (/linux|x11/i.test(ua)) return "linux";
    return "win";
  }

  /* ---------------- estado ---------------- */
  function onlineEngines() { return (st && st.engines || []).filter(function (e) { return e.online; }); }
  function ollamaOnline() { return onlineEngines().some(function (e) { return e.kind === "ollama"; }); }
  function installedIds() { return (st && st.installed || []).map(function (m) { return m.id; }); }
  function isInstalled(id) {
    var base = id.split(":")[0].toLowerCase();
    return installedIds().some(function (x) { x = x.toLowerCase(); return x === id.toLowerCase() || (id.indexOf(":") < 0 && x.split(":")[0] === base); });
  }
  function caps(id) { var m = (st.installed || []).filter(function (x) { return x.id === id; })[0]; return m ? m.caps : []; }

  function load(refresh) {
    setPill("busy", refresh ? "Buscando motores…" : "Comprobando…");
    return PixAgent.local.status(refresh).then(function (s) { st = s; render(); }).catch(function (e) {
      setPill("err", "Sin conexión");
      notice("err", "No se pudo consultar la IA local", friendlyError(e));
    });
  }
  function setPill(kind, text) {
    var p = $("#statusPill"); p.className = "pill " + kind; p.lastElementChild.textContent = text;
  }

  function render() {
    var on = onlineEngines();
    var nModels = (st.installed || []).length;
    var narrow = window.matchMedia("(max-width: 900px)").matches;
    var nTxt = nModels + (nModels === 1 ? " modelo" : " modelos");
    if (!on.length) setPill("err", "Sin motor en marcha");
    else if (!nModels) setPill("warn", narrow ? "Sin modelos" : on[0].name + " · sin modelos");
    else setPill("ok", narrow ? nTxt : on.map(function (e) { return e.name; }).join(", ") + " · " + nTxt);
    renderEngines(on);
    renderModels();
    renderProfiles();
    renderAssign();
    renderCustom();
    renderCatalog();
    renderDeps();
    $("#btnCaption").disabled = !tryFile || !on.length || busy.caption;
    $("#btnOcr").disabled = !tryFile || !on.length || busy.ocr;
  }

  function renderEngines(on) {
    var ul = $("#engines"); ul.innerHTML = "";
    var list = (st.engines || []).slice();
    // en línea primero; los apagados de serie se resumen para no abrumar
    var offDefault = list.filter(function (e) { return !e.online && !isCustom(e); });
    list.filter(function (e) { return e.online || isCustom(e); }).forEach(function (e) { ul.appendChild(engineRow(e)); });
    if (on.length) {
      $("#engineSub").textContent = on.length === 1 ? on[0].name + " está en marcha" + (on[0].version ? " (v" + on[0].version + ")" : "") : on.length + " motores en marcha";
      if (offDefault.length) {
        var li = document.createElement("li"); li.className = "hint"; li.style.margin = "4px 0 0";
        li.textContent = "También se buscan: " + offDefault.map(function (e) { return e.name; }).join(", ") + " (apagados).";
        ul.appendChild(li);
      }
    } else {
      $("#engineSub").textContent = "No se ha encontrado ningún motor en marcha en este equipo";
      offDefault.forEach(function (e) { ul.appendChild(engineRow(e)); });
    }
    $("#guide").hidden = !!on.length;
    $("#guideMore").hidden = !on.length;
    if (!on.length) renderGuide($("#steps"), $("#guideFoot"), platform); else renderGuideCompact();
  }
  function isCustom(e) { return (st.customEngines || customFromSettings()).some(function (c) { return c.url === e.url; }); }
  function customFromSettings() {
    // los motores personalizados son los que no están entre los 4 de serie
    var defaults = ["http://127.0.0.1:11434", "http://127.0.0.1:8080", "http://127.0.0.1:9931", "http://127.0.0.1:1234"];
    return (st.engines || []).filter(function (e) { return defaults.indexOf(e.url) < 0; }).map(function (e) { return { name: e.name, url: e.url, kind: e.kind }; });
  }
  function engineRow(e) {
    var li = document.createElement("li"); li.className = "engine" + (e.online ? " on" : "");
    var stt = e.online ? ((e.models || 0) + (e.models === 1 ? " modelo" : " modelos") + (e.version ? " · v" + e.version : "")) : "apagado";
    li.innerHTML = '<i class="dot"></i><div class="nm"><b>' + esc(e.name) + "</b><code>" + esc(e.url) + "</code></div>" +
      '<span class="st">' + esc(stt) + "</span>";
    if (isCustom(e)) {
      var rm = document.createElement("button"); rm.className = "rm"; rm.type = "button"; rm.title = "Quitar este motor"; rm.setAttribute("aria-label", "Quitar " + e.name);
      rm.innerHTML = '<svg class="i sm"><use href="#i-trash"/></svg>';
      rm.onclick = function () { removeEngine(e.url); };
      li.appendChild(rm);
    }
    return li;
  }

  /* ---------------- guía de instalación ---------------- */
  var GUIDE = {
    win: { steps: [
      ["Descarga Ollama para Windows en ", "https://ollama.com/download", "ollama.com/download"],
      ["Ejecuta el instalador. Ollama arranca solo y queda en la bandeja del sistema (icono de la llama)."],
      ["Vuelve aquí y pulsa el botón de actualizar. Después descarga un modelo del kit recomendado."]],
      foot: "Necesitas unos 4 GB libres para el primer modelo. Sin tarjeta gráfica también funciona, más despacio." },
    mac: { steps: [
      ["Descarga Ollama para Mac en ", "https://ollama.com/download", "ollama.com/download"],
      ["Abre la app y acepta instalar la herramienta de línea de comandos. Queda en la barra de menús."],
      ["Vuelve aquí y pulsa el botón de actualizar. Después descarga un modelo del kit recomendado."]],
      foot: "En los Mac con chip M los modelos de 4 B responden en pocos segundos." },
    linux: { steps: [
      ["Instala Ollama con el script oficial:", null, null, "curl -fsSL https://ollama.com/install.sh | sh"],
      ["Comprueba que el servicio está en marcha:", null, null, "ollama --version"],
      ["Vuelve aquí y pulsa el botón de actualizar. Después descarga un modelo del kit recomendado."]],
      foot: "Alternativa sin instalar nada: llama.cpp (llama-server --port 8080) o LM Studio; PixAgent los detecta en sus puertos habituales." },
    mobile: { steps: [
      ["Los modelos se ejecutan en el equipo anfitrión (el PC o Mac donde está PixAgent). Instala Ollama allí siguiendo la guía de Windows, Mac o Linux."],
      ["Abre PixAgent desde el móvil (código QR del anfitrión) y usa las mini apps: la IA local trabaja en el anfitrión y tú ves el resultado aquí."],
      ["En Android existe la posibilidad de ejecutar Ollama dentro de Termux, pero es una vía avanzada que no hemos verificado y no la recomendamos de momento."]],
      foot: "La IA dentro del propio móvil (sin anfitrión) está en evaluación; la añadiremos cuando funcione de forma fiable." }
  };
  function renderGuide(ol, foot, p) {
    $$("#platforms button").forEach(function (b) { b.setAttribute("aria-pressed", String(b.dataset.p === p)); });
    ol.innerHTML = "";
    GUIDE[p].steps.forEach(function (s) {
      var li = document.createElement("li"); var body = document.createElement("div"); body.className = "body";
      var span = document.createElement("span"); span.textContent = s[0];
      if (s[1]) { var a = document.createElement("a"); a.href = s[1]; a.target = "_blank"; a.rel = "noopener"; a.textContent = s[2]; span.appendChild(a); }
      body.appendChild(span);
      if (s[3]) body.appendChild(cmdBox(s[3]));
      li.appendChild(body); ol.appendChild(li);
    });
    foot.textContent = GUIDE[p].foot;
  }
  function renderGuideCompact() {
    var box = $("#guideMoreBody");
    if (box.childElementCount) return;
    var seg = document.createElement("div"); seg.className = "seg platforms"; seg.style.marginBottom = "10px";
    ["win", "mac", "linux", "mobile"].forEach(function (p) {
      var b = document.createElement("button"); b.type = "button"; b.textContent = { win: "Windows", mac: "Mac", linux: "Linux", mobile: "Móvil" }[p];
      b.setAttribute("aria-pressed", String(p === platform));
      b.onclick = function () { $$("button", seg).forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); }); fill(p); };
      seg.appendChild(b);
    });
    var ol = document.createElement("ol"); ol.className = "steps"; var foot = document.createElement("p"); foot.className = "hint";
    function fill(p) { ol.innerHTML = ""; GUIDE[p].steps.forEach(function (s) {
      var li = document.createElement("li"); var body = document.createElement("div"); body.className = "body";
      var span = document.createElement("span"); span.textContent = s[0];
      if (s[1]) { var a = document.createElement("a"); a.href = s[1]; a.target = "_blank"; a.rel = "noopener"; a.textContent = s[2]; span.appendChild(a); }
      body.appendChild(span); if (s[3]) body.appendChild(cmdBox(s[3])); li.appendChild(body); ol.appendChild(li); }); foot.textContent = GUIDE[p].foot; }
    fill(platform);
    box.appendChild(seg); box.appendChild(ol); box.appendChild(foot);
  }

  /* ---------------- modelos instalados ---------------- */
  function chipsFor(capList) {
    return '<div class="chips">' + CAP_ORDER.map(function (c) { return '<span class="chip' + (capList.indexOf(c) >= 0 ? " on" : "") + '">' + CAP_LABEL[c] + "</span>"; }).join("") + "</div>";
  }
  function renderModels() {
    var ul = $("#models"); ul.innerHTML = "";
    var list = st.installed || [];
    $("#modelsCount").textContent = list.length ? String(list.length) : "";
    $("#modelsEmpty").hidden = !!list.length;
    $("#modelsEmpty").textContent = onlineEngines().length ? "Aún no hay modelos. Descarga uno del kit recomendado." : "Aparecerán aquí cuando haya un motor en marcha.";
    $("#modelsSub").textContent = list.length ? "Cada modelo indica para qué sirve" : "Ningún modelo todavía";
    list.forEach(function (m) {
      var li = document.createElement("li"); li.className = "model";
      li.innerHTML = '<span class="id" title="' + esc(m.id) + '">' + esc(m.id) + '</span><span class="meta">' + esc(m.engine) + (m.size_gb ? " · " + fmtGb(m.size_gb) : "") + "</span>" + chipsFor(m.caps || []);
      ul.appendChild(li);
    });
  }

  /* ---------------- kit recomendado ---------------- */
  function catalogEntry(id) {
    var base = id.split(":")[0];
    return (st.catalog || []).filter(function (c) { return c.id === id; })[0] || (st.catalog || []).filter(function (c) { return c.id.split(":")[0] === base; })[0] || { id: id, task: [], note: "" };
  }
  function guessProfile() {
    // navigator.deviceMemory solo existe en Chrome/Edge y nunca pasa de 8: solo sirve para detectar equipos justos
    var mem = navigator.deviceMemory;
    return { key: mem && mem < 8 ? "pc_basico" : "equilibrado", sure: !!(mem && mem < 8) };
  }
  function renderProfiles() {
    var box = $("#profiles"); box.innerHTML = "";
    var profiles = st.profiles || {};
    var fits = guessProfile();
    Object.keys(profiles).forEach(function (key) {
      var p = profiles[key];
      var card = document.createElement("article"); card.className = "profile" + (key === fits.key ? " fits" : "");
      var total = 0;
      p.models.forEach(function (id) { var c = catalogEntry(id); if (c.size_gb) total += c.size_gb; });
      card.innerHTML = "<h4>" + esc(p.label) + (key === fits.key ? '<span class="tag">' + (fits.sure ? "Parece tu equipo" : "Recomendado") + "</span>" : "") + "</h4>" +
        (total ? '<p class="total">Descarga total: ' + fmtGb(total) + "</p>" : "");
      p.models.forEach(function (id) { card.appendChild(kitModel(id)); });
      box.appendChild(card);
    });
    $("#kitHint").textContent = !onlineEngines().length ? "Instala un motor para poder descargar modelos desde aquí."
      : ollamaOnline() ? "Las descargas se hacen con Ollama y siguen aunque cierres esta ventana."
      : "Tu motor no descarga modelos desde aquí: copia el comando o usa su propia aplicación.";
  }
  function kitModel(id) {
    var c = catalogEntry(id);
    var el = document.createElement("div"); el.className = "kitm"; el.dataset.model = id;
    el.innerHTML = '<div class="top"><span class="id">' + esc(id) + '</span><span class="size">' + (c.size_gb ? fmtGb(c.size_gb) : "") + (c.ram_gb ? " · " + c.ram_gb + " GB RAM" : "") + "</span></div>" +
      (c.note ? '<p class="note">' + esc(c.note) + "</p>" : "") + '<div class="act"></div>';
    renderKitAction(el, id);
    return el;
  }
  function renderKitAction(el, id) {
    var act = el.querySelector(".act"); act.innerHTML = "";
    var p = pulls[id];
    if (p && p.status !== "success" && p.status !== "error") {
      var w = document.createElement("div"); w.className = "pulling";
      w.innerHTML = '<div class="lbl2"><span>' + esc(p.status || "Descargando…") + "</span><span class=\"num\">" + (p.pct != null ? Math.round(p.pct) + " %" : "") + "</span></div>" +
        '<div class="progress' + (p.pct == null ? " indet" : "") + '"><i style="width:' + (p.pct || 0) + '%"></i></div>';
      act.appendChild(w);
      return;
    }
    if (isInstalled(id)) { act.innerHTML = '<span class="done"><svg class="i sm"><use href="#i-check"/></svg> Instalado</span>'; return; }
    var b = document.createElement("button"); b.type = "button"; b.className = "btn sm" + (ollamaOnline() ? " soft" : "");
    if (p && p.status === "error") {
      b.innerHTML = '<svg class="i sm"><use href="#i-refresh"/></svg> Reintentar';
      var e = document.createElement("span"); e.className = "hint"; e.style.margin = "0"; e.style.color = "var(--err)"; e.textContent = p.error || "Falló la descarga";
      act.appendChild(e);
    } else if (ollamaOnline()) b.innerHTML = '<svg class="i sm"><use href="#i-download"/></svg> Descargar';
    else { b.innerHTML = '<svg class="i sm"><use href="#i-copy"/></svg> Copiar comando'; b.title = "ollama pull " + id; }
    b.onclick = function () { if (ollamaOnline()) pull(id); else copy("ollama pull " + id, "Comando copiado: ollama pull " + id); };
    act.insertBefore(b, act.firstChild);
  }
  function refreshKit(id) { $$('.kitm[data-model="' + id.replace(/"/g, '\\"') + '"]').forEach(function (el) { renderKitAction(el, id); }); }
  function pull(id) {
    pulls[id] = { status: "Conectando con Ollama…", pct: null }; refreshKit(id);
    PixAgent.local.pull(id).catch(function (e) {
      pulls[id] = { status: "error", error: friendlyError(e) }; refreshKit(id);
      notice("err", "No se pudo iniciar la descarga de " + id, friendlyError(e));
    });
  }
  function onPullEvent(ev) {
    var id = ev.model; if (!id) return;
    if (ev.status === "error") { pulls[id] = { status: "error", error: ev.error || "Error" }; refreshKit(id); notice("err", "Falló la descarga de " + id, ev.error || ""); return; }
    if (ev.status === "success") {
      pulls[id] = { status: "success", pct: 100 }; refreshKit(id); toast(id + " descargado");
      load(true);
      return;
    }
    pulls[id] = { status: prettyStatus(ev.status), pct: ev.pct }; refreshKit(id);
  }
  function prettyStatus(s) {
    s = String(s || "");
    if (/pulling manifest/i.test(s)) return "Preparando…";
    if (/^pulling/i.test(s)) return "Descargando…";
    if (/verifying/i.test(s)) return "Verificando…";
    if (/writing/i.test(s)) return "Guardando…";
    if (/success/i.test(s)) return "Listo";
    return s || "Descargando…";
  }

  /* ---------------- modelo por tarea ---------------- */
  // El servidor guarda la elección en los ajustes de PixAgent; aquí se recuerda en este navegador
  // para mostrar el select en la opción elegida (el estado del servidor no la distingue de "automático").
  var MIRROR = "pixagent.ialocal.models.v1";
  function mirror() { try { return JSON.parse(localStorage.getItem(MIRROR) || "{}") || {}; } catch (e) { return {}; } }
  function renderAssign() {
    var any = onlineEngines().length;
    $$("#assignCard select").forEach(function (sel) {
      var task = sel.dataset.task;
      var current = mirror()[task] || "";
      var assigned = st.assigned && st.assigned[task];
      var auto = assigned ? "Automático (" + assigned[1] + ")" : (any ? "Automático (falta un modelo de " + TASK_LABEL[task] + ")" : "Automático");
      var opts = '<option value="">' + esc(auto) + "</option>";
      var pool = (st.installed || []).filter(function (m) { return (m.caps || []).indexOf(task) >= 0 || !(m.caps || []).length; });
      // los demás modelos, por si el catálogo no reconoce la familia
      var rest = (st.installed || []).filter(function (m) { return pool.indexOf(m) < 0; });
      pool.forEach(function (m) { opts += '<option value="' + esc(m.id) + '">' + esc(m.id) + "</option>"; });
      if (rest.length) { opts += '<optgroup label="Otros modelos instalados">'; rest.forEach(function (m) { opts += '<option value="' + esc(m.id) + '">' + esc(m.id) + "</option>"; }); opts += "</optgroup>"; }
      sel.innerHTML = opts;
      sel.value = current; if (sel.value !== current) sel.value = "";
      sel.disabled = !any;
    });
    $("#assignHint").textContent = any ? "" : "Disponible cuando haya un motor en marcha.";
  }
  function saveAssign() {
    var models = {};
    $$("#assignCard select").forEach(function (sel) { if (sel.value) models[sel.dataset.task] = sel.value; });
    try { localStorage.setItem(MIRROR, JSON.stringify(models)); } catch (e) { /* sin almacenamiento local */ }
    postSettings({ models: models }).then(function () { toast("Asignación guardada"); });
  }
  function postSettings(body) {
    return fetch("/api/local/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) })
      .then(function (r) { return r.json(); })
      .then(function (d) { if (!d.ok) throw new Error(d.error || "Error"); st = d.status; render(); return d; })
      .catch(function (e) { notice("err", "No se pudo guardar", friendlyError(e)); throw e; });
  }

  /* ---------------- motores personalizados ---------------- */
  function renderCustom() {
    var ul = $("#customList"); ul.innerHTML = "";
    customFromSettings().forEach(function (c) {
      var e = (st.engines || []).filter(function (x) { return x.url === c.url; })[0] || { name: c.name, url: c.url, online: false };
      ul.appendChild(engineRow(e));
    });
  }
  function addEngine() {
    var name = $("#cName").value.trim(), url = $("#cUrl").value.trim(), kind = $("#cKind").value;
    if (!/^https?:\/\//i.test(url)) { toast("Escribe la URL completa, con http:// o https://"); $("#cUrl").focus(); return; }
    url = url.replace(/\/+$/, "").replace(/\/v1$/, "");
    var list = customFromSettings().filter(function (c) { return c.url !== url; });
    list.push({ name: name || url.replace(/^https?:\/\//, ""), url: url, kind: kind });
    $("#btnAddEngine").disabled = true;
    postSettings({ engines: list }).then(function () {
      $("#cName").value = ""; $("#cUrl").value = "";
      var e = (st.engines || []).filter(function (x) { return x.url === url; })[0];
      toast(e && e.online ? "Motor añadido y en línea" : "Motor añadido, pero no responde en " + url);
    }).catch(function () { /* avisado */ }).then(function () { $("#btnAddEngine").disabled = false; });
  }
  function removeEngine(url) {
    postSettings({ engines: customFromSettings().filter(function (c) { return c.url !== url; }) }).then(function () { toast("Motor quitado"); });
  }

  /* ---------------- catálogo y dependencias ---------------- */
  function renderCatalog() {
    var t = $("#catalog");
    var rows = (st.catalog || []).map(function (c) {
      var inst = isInstalled(c.id);
      return "<tr><td class=\"id\">" + esc(c.id) + "</td><td>" + (c.task || []).map(function (k) { return CAP_LABEL[k] || k; }).join(", ") + "</td>" +
        '<td class="n">' + fmtGb(c.size_gb) + '</td><td class="n">' + (c.ram_gb || "") + " GB</td><td>" + esc(c.note || "") + "</td>" +
        "<td>" + (inst ? '<span class="chip on">Instalado</span>' : '<button class="btn sm" type="button" data-pull="' + esc(c.id) + '">' + (ollamaOnline() ? "Descargar" : "Copiar") + "</button>") + "</td></tr>";
    }).join("");
    t.innerHTML = "<thead><tr><th>Modelo</th><th>Tareas</th><th>Tamaño</th><th>RAM</th><th>Para qué</th><th></th></tr></thead><tbody>" + rows + "</tbody>";
  }
  function renderDeps() {
    var v = st.video || {}, asr = st.asr || {};
    var items = [
      ["ffmpeg (fotogramas de vídeo)", !!v.ffmpeg, "pip install imageio-ffmpeg"],
      ["yt-dlp (vídeos por enlace)", !!v.youtube, "pip install yt-dlp"],
      ["faster-whisper (transcribir audio)", !!asr.faster_whisper, "pip install faster-whisper"]
    ];
    $("#deps").innerHTML = items.map(function (it) { return '<li class="' + (it[1] ? "on" : "") + '"><i class="dot"></i>' + esc(it[0]) + (it[1] ? "" : "<code>" + esc(it[2]) + "</code>") + "</li>"; }).join("");
  }

  /* ---------------- probar con una imagen ---------------- */
  function setTryFile(file) {
    if (!file || !/^image\//.test(file.type)) { toast("Elige una imagen (JPG, PNG, WebP…)"); return; }
    tryFile = file; tryPath = null;
    if (tryUrl) URL.revokeObjectURL(tryUrl);
    tryUrl = URL.createObjectURL(file);
    var img = $("#tryImg"); img.src = tryUrl; img.hidden = false; img.alt = file.name || "Imagen de prueba";
    $("#dropIn").hidden = true; $("#drop").classList.add("has"); $("#btnTryClear").hidden = false;
    $("#tryResults").innerHTML = "";
    render();
  }
  function clearTry() {
    tryFile = null; tryPath = null; if (tryUrl) URL.revokeObjectURL(tryUrl); tryUrl = null;
    $("#tryImg").hidden = true; $("#tryImg").removeAttribute("src"); $("#dropIn").hidden = false; $("#drop").classList.remove("has"); $("#btnTryClear").hidden = true;
    $("#tryResults").innerHTML = ""; $("#filePick").value = "";
    render();
  }
  function ensureUploaded() {
    if (tryPath) return Promise.resolve(tryPath);
    return PixAgent.upload([tryFile]).then(function (paths) { tryPath = paths[0]; return tryPath; });
  }
  function runTry(task) {
    if (!tryFile || busy[task]) return;
    busy[task] = true; render();
    var box = $("#tryResults");
    var title = task === "caption" ? "Descripción" : "Texto leído (OCR)";
    var old = $('.res[data-task="' + task + '"]', box); if (old) old.remove();
    var res = document.createElement("div"); res.className = "res"; res.dataset.task = task;
    res.innerHTML = '<div class="rh"><b>' + title + '</b><span class="time"><svg class="i sm"><use href="#i-clock"/></svg> <span class="num">…</span></span></div>' +
      '<div class="busy"><span class="spin"></span> ' + (tryPath ? "" : "Subiendo la imagen y ") + "consultando al modelo local…</div>";
    box.insertBefore(res, box.firstChild);
    var t0 = Date.now();
    ensureUploaded().then(function (p) { return PixAgent.local.run(task, { images: [p] }); }).then(function (r) {
      var secs = (r.usage && r.usage.seconds) || (Date.now() - t0) / 1000;
      var timeEl = res.querySelector(".time"); timeEl.classList.add(secs < 8 ? "fast" : secs > 30 ? "slow" : "x");
      timeEl.querySelector("span").textContent = fmtSec(secs);
      var rh = res.querySelector(".rh"); var m = document.createElement("span"); m.className = "mono"; m.style.color = "var(--text-3)"; m.textContent = r.model || ""; rh.insertBefore(m, timeEl);
      res.querySelector(".busy").remove();
      var pre = document.createElement("pre"); if (task === "ocr") pre.className = "mono"; pre.textContent = r.text || "(sin respuesta)"; res.appendChild(pre);
      var acts = document.createElement("div"); acts.className = "hrow"; acts.style.padding = "0 10px 10px";
      var cp = document.createElement("button"); cp.type = "button"; cp.className = "btn sm ghost"; cp.innerHTML = '<svg class="i sm"><use href="#i-copy"/></svg> Copiar';
      cp.onclick = function () { copy(r.text || ""); }; acts.appendChild(cp); res.appendChild(acts);
    }).catch(function (e) {
      res.classList.add("err"); res.querySelector(".busy").remove(); res.querySelector(".time").hidden = true;
      var pre = document.createElement("pre"); pre.textContent = friendlyError(e); res.appendChild(pre);
    }).then(function () { busy[task] = false; render(); });
  }
  function openLightbox() {
    if (!tryUrl) return;
    if (!lightbox) {
      lightbox = document.createElement("div"); lightbox.className = "lightbox"; lightbox.hidden = true;
      lightbox.innerHTML = '<div class="lb-box"><img alt="Imagen de prueba"></div><div class="lb-bar"><span></span><button class="btn light" type="button" aria-label="Cerrar"><svg class="i"><use href="#i-x"/></svg></button></div>';
      document.body.appendChild(lightbox);
      lightbox.querySelector("button").onclick = function () { lightbox.hidden = true; };
      document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !lightbox.hidden) lightbox.hidden = true; });
    }
    var img = lightbox.querySelector("img"); img.src = tryUrl;
    lightbox.querySelector(".lb-bar span").textContent = tryFile ? tryFile.name : "";
    lightbox.hidden = false;
    if (window.PixZoom && !lightbox._z) { try { lightbox._z = PixZoom.attach(lightbox.querySelector(".lb-box"), img, { wheel: "zoom" }); } catch (e) { lightbox._z = null; } }
    if (lightbox._z) { img.onload = function () { lightbox._z.fit(); }; if (img.complete) lightbox._z.fit(); }
    else { img.style.maxWidth = "100%"; img.style.maxHeight = "100%"; img.style.margin = "auto"; img.style.position = "absolute"; img.style.inset = "0"; img.style.objectFit = "contain"; img.style.width = "100%"; img.style.height = "100%"; }
  }

  /* ---------------- WebSocket: progreso de descargas ---------------- */
  var wsRetry = 0;
  function connectWS() {
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (s) {
      var ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
      ws.onopen = function () { wsRetry = 0; ws.send(JSON.stringify({ type: "hello", after: s.seq || 0 })); };
      ws.onmessage = function (m) {
        var ev; try { ev = JSON.parse(m.data); } catch (e) { return; }
        if (ev && ev.type === "local_pull") onPullEvent(ev);
      };
      ws.onclose = function () { wsRetry++; setTimeout(connectWS, Math.min(15000, 2000 * wsRetry)); };
      ws.onerror = function () { /* onclose reintenta */ };
    }).catch(function () { wsRetry++; setTimeout(connectWS, Math.min(15000, 2000 * wsRetry)); });
  }

  /* ---------------- arranque ---------------- */
  function init() {
    $("#btnRefresh").onclick = function () { load(true); };
    $$("#platforms button").forEach(function (b) { b.onclick = function () { platform = b.dataset.p; renderGuide($("#steps"), $("#guideFoot"), platform); }; });
    $$("#assignCard select").forEach(function (sel) { sel.addEventListener("change", saveAssign); });
    $("#btnAddEngine").onclick = addEngine;
    $("#cUrl").addEventListener("keydown", function (e) { if (e.key === "Enter") addEngine(); });
    $("#catalog").addEventListener("click", function (e) {
      var b = e.target.closest("[data-pull]"); if (!b) return;
      if (ollamaOnline()) pull(b.dataset.pull); else copy("ollama pull " + b.dataset.pull, "Comando copiado");
    });
    // probar
    var drop = $("#drop");
    $("#btnPick").onclick = function () { $("#filePick").click(); };
    $("#filePick").addEventListener("change", function () { if (this.files[0]) setTryFile(this.files[0]); });
    ["dragenter", "dragover"].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("over"); }); });
    drop.addEventListener("drop", function (e) { var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; if (f) setTryFile(f); });
    document.addEventListener("paste", function (e) {
      var items = e.clipboardData && e.clipboardData.items; if (!items) return;
      for (var i = 0; i < items.length; i++) if (items[i].kind === "file" && /^image\//.test(items[i].type)) { setTryFile(items[i].getAsFile()); e.preventDefault(); return; }
    });
    $("#tryImg").addEventListener("click", openLightbox);
    $("#btnCaption").onclick = function () { runTry("caption"); };
    $("#btnOcr").onclick = function () { runTry("ocr"); };
    $("#btnTryClear").onclick = clearTry;
    connectWS();
    load(false);
  }
  init();
})();
