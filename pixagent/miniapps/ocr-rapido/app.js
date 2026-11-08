/* OCR rápido — mini app de PixAgent.
   Varias imágenes o capturas → texto con el modelo de OCR local, una tras otra (cola visible).
   Cada resultado se puede corregir; copiar todo, descargar .txt/.md, guardar en outputs/ocr y
   enviar al agente. ES2019 / Safari iOS 15. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  var hasZoom = !!(window.PixZoom && typeof window.PixZoom.attach === "function");
  var MAX_PX = 2000;   // el servidor reduce a 1280 px para el OCR; subir más no aporta

  var st = null, items = [], processing = false, lbz = null, seq = 0;

  /* ---------------- utilidades ---------------- */
  var toastTimer;
  function toast(msg) {
    var t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2600);
  }
  function notice(kind, title, body, actions) {
    var box = $("#notices");
    var el = document.createElement("div");
    el.className = "notice " + kind;
    var icon = kind === "ok" ? "i-check" : kind === "info" ? "i-info" : "i-alert";
    el.innerHTML = '<svg class="i"><use href="#' + icon + '"/></svg>' +
      '<div class="body"><b>' + esc(title) + "</b>" + (body ? "<span>" + esc(body) + "</span>" : "") + (actions ? '<div class="acts"></div>' : "") + "</div>" +
      '<button class="close" type="button" aria-label="Cerrar"><svg class="i sm"><use href="#i-x"/></svg></button>';
    el.querySelector(".close").onclick = function () { el.remove(); };
    if (actions) actions.forEach(function (a) { el.querySelector(".acts").appendChild(a); });
    box.insertBefore(el, box.firstChild);
    while (box.children.length > 2) box.removeChild(box.lastChild);
    return el;
  }
  function mkBtn(label, icon, cls, onClick, href) {
    var b = document.createElement(href ? "a" : "button");
    b.className = "btn sm " + (cls || "");
    if (href) b.href = href; else b.type = "button";
    b.innerHTML = '<svg class="i sm"><use href="#' + icon + '"/></svg> ' + esc(label);
    if (onClick) b.addEventListener("click", onClick);
    return b;
  }
  function friendlyError(e) {
    var m = (e && e.message) || String(e);
    if (/Failed to fetch|NetworkError|network/i.test(m)) return "No hay conexión con el servidor de PixAgent.";
    return m.length > 400 ? m.slice(0, 400) + "…" : m;
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
  function fmtSec(s) { return s == null ? "" : (s < 10 ? (Math.round(s * 10) / 10).toString().replace(".", ",") : Math.round(s)) + " s"; }
  function stamp() { var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; }; return d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "_" + p(d.getHours()) + p(d.getMinutes()); }
  function downloadFile(name, text, type) {
    var a = document.createElement("a"); a.href = URL.createObjectURL(new Blob([text], { type: type || "text/plain;charset=utf-8" })); a.download = name;
    document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }

  /* ---------------- estado de la IA local ---------------- */
  function setPill(kind, text) { var p = $("#statusPill"); p.className = "pill " + kind; p.lastElementChild.textContent = text; }
  function loadStatus() {
    return PixAgent.local.status().then(function (s) {
      st = s;
      var on = (s.engines || []).filter(function (e) { return e.online; });
      var ocr = s.assigned && s.assigned.ocr;
      if (!on.length) {
        setPill("err", "Sin IA local");
        notice("warn", "No hay ningún motor de IA local en marcha", "Instala Ollama (ollama.com) o arranca llama.cpp / LM Studio en el equipo anfitrión y descarga un modelo de OCR (p. ej. glm-ocr o qwen3.5:4b).",
          [mkBtn("Abrir IA local", "i-brain", "soft", null, "/apps/ia-local/")]);
      } else if (!ocr) {
        setPill("warn", "Falta un modelo de OCR");
        notice("warn", "Falta un modelo que lea texto", "Descarga glm-ocr o qwen3.5:4b desde la mini app IA local.", [mkBtn("Abrir IA local", "i-brain", "soft", null, "/apps/ia-local/")]);
      } else setPill("ok", window.matchMedia("(max-width: 900px)").matches ? ocr[1] : ocr[0] + " · " + ocr[1]);
      var sel = $("#modelSel"); var cur = sel.value;
      sel.innerHTML = '<option value="">Automático' + (ocr ? " (" + esc(ocr[1]) + ")" : "") + "</option>" +
        (s.installed || []).filter(function (m) { return (m.caps || []).indexOf("ocr") >= 0 || (m.caps || []).indexOf("vision") >= 0; })
          .map(function (m) { return '<option value="' + esc(m.id) + '">' + esc(m.id) + "</option>"; }).join("");
      sel.value = cur; if (sel.value !== cur) sel.value = "";
    }).catch(function (e) { setPill("err", "Sin conexión"); notice("err", "No se pudo consultar la IA local", friendlyError(e)); });
  }
  function updateAdvSum() { $("#advSum").textContent = ($("#modelSel").value || "Modelo automático") + ($("#fmtSel").value === "plain" ? " · texto plano" : " · tablas en Markdown"); }

  /* ---------------- cola ---------------- */
  function shrink(file) {
    return new Promise(function (resolve) {
      var url = URL.createObjectURL(file); var img = new Image();
      img.onload = function () {
        var w = img.naturalWidth, h = img.naturalHeight, k = Math.min(1, MAX_PX / Math.max(w, h));
        if (k === 1 && /jpe?g|png/i.test(file.type) && file.size < 4000000) { URL.revokeObjectURL(url); return resolve(file); }
        var c = document.createElement("canvas"); c.width = Math.max(1, Math.round(w * k)); c.height = Math.max(1, Math.round(h * k));
        c.getContext("2d").drawImage(img, 0, 0, c.width, c.height);
        c.toBlob(function (b) {
          URL.revokeObjectURL(url);
          if (!b) return resolve(file);
          var name = (file.name || "imagen").replace(/\.[^.]+$/, "") + ".jpg";
          try { b = new File([b], name, { type: "image/jpeg" }); } catch (e) { b.name = name; }
          resolve(b);
        }, "image/jpeg", 0.92);
      };
      img.onerror = function () { URL.revokeObjectURL(url); resolve(file); };
      img.src = url;
    });
  }
  function addFiles(list, label) {
    var files = Array.prototype.slice.call(list || []).filter(function (f) { return /^image\//.test(f.type) || /\.(jpe?g|png|webp|gif|bmp|heic|heif|tiff?)$/i.test(f.name || ""); });
    if (!files.length) { toast("No se han encontrado imágenes"); return; }
    files.forEach(function (f, i) {
      var it = { id: "i" + (++seq), file: f, name: f.name || (label || "captura") + "_" + stamp() + (files.length > 1 ? "_" + (i + 1) : "") + ".png", url: URL.createObjectURL(f), path: null, status: "queued", text: "", seconds: null, model: "", error: "" };
      items.push(it); $("#queue").appendChild(renderItem(it));
    });
    updateToolbar(); processQueue();
  }
  function renderItem(it) {
    var li = document.createElement("li"); li.className = "item"; li.id = it.id;
    li.innerHTML = '<div class="pic" role="button" tabindex="0" aria-label="Ver la imagen en grande"><img alt="" src="' + esc(it.url) + '"><span class="num"></span>' +
      '<button class="del" type="button" aria-label="Quitar" title="Quitar"><svg class="i sm"><use href="#i-trash"/></svg></button></div>' +
      '<div class="body"><div class="head"><span class="name" title="' + esc(it.name) + '">' + esc(it.name) + '</span><span class="state"></span><span class="time"></span>' +
      '<button class="btn sm icon ghost copy1" type="button" aria-label="Copiar este texto" title="Copiar"><svg class="i sm"><use href="#i-copy"/></svg></button></div><div class="content"></div></div>';
    li.querySelector(".del").onclick = function (e) { e.stopPropagation(); removeItem(it); };
    var pic = li.querySelector(".pic");
    pic.addEventListener("click", function (e) { if (e.target.closest("button")) return; openLightbox(it); });
    pic.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openLightbox(it); } });
    li.querySelector(".copy1").onclick = function () { copy(it.text || "", "Texto copiado"); };
    updateItem(it, li);
    return li;
  }
  function updateItem(it, li) {
    li = li || $("#" + it.id); if (!li) return;
    li.className = "item " + it.status;
    li.querySelector(".num").textContent = items.indexOf(it) + 1;
    var state = li.querySelector(".state"), time = li.querySelector(".time"), content = li.querySelector(".content");
    li.querySelector(".copy1").hidden = it.status !== "done";
    time.innerHTML = it.seconds != null ? '<svg class="i sm" style="width:12px;height:12px"><use href="#i-clock"/></svg> ' + esc(fmtSec(it.seconds)) : "";
    time.title = it.model ? "Modelo: " + it.model : "";
    if (it.status === "queued") { state.className = "state"; state.textContent = "En cola"; content.innerHTML = '<div class="wait">Esperando su turno…</div>'; }
    else if (it.status === "uploading" || it.status === "running") {
      state.className = "state run"; state.innerHTML = '<span class="spin" style="width:12px;height:12px"></span> ' + (it.status === "uploading" ? "Subiendo…" : "Leyendo…");
      content.innerHTML = '<div class="wait"><span class="spin"></span> ' + (it.status === "uploading" ? "Subiendo la imagen al anfitrión…" : "El modelo local está leyendo el texto…") + "</div>";
    } else if (it.status === "error") {
      state.className = "state err"; state.innerHTML = '<svg class="i sm"><use href="#i-alert"/></svg> Error';
      content.innerHTML = '<div class="errmsg"><span>' + esc(it.error) + "</span></div>";
      content.querySelector(".errmsg").appendChild(mkBtn("Reintentar", "i-refresh", "", function () { it.status = "queued"; it.error = ""; updateItem(it); updateToolbar(); processQueue(); }));
    } else {
      state.className = "state ok"; state.innerHTML = '<svg class="i sm"><use href="#i-check"/></svg> Leído';
      if (!content.querySelector("textarea")) {
        content.innerHTML = '<textarea spellcheck="false" aria-label="Texto leído (editable)" placeholder="(sin texto)"></textarea>';
        var ta = content.querySelector("textarea"); ta.value = it.text;
        ta.addEventListener("input", function () { it.text = ta.value; });
        autosize(ta);
      }
    }
  }
  function autosize(ta) { ta.style.height = "auto"; ta.style.height = Math.min(520, Math.max(120, ta.scrollHeight + 4)) + "px"; }
  function removeItem(it) {
    var i = items.indexOf(it); if (i < 0) return;
    items.splice(i, 1); var li = $("#" + it.id); if (li) li.remove(); URL.revokeObjectURL(it.url);
    items.forEach(function (x) { updateItem(x); }); updateToolbar();
  }
  function clearAll() { items.slice().forEach(removeItem); }
  function updateToolbar() {
    var n = items.length, done = items.filter(function (x) { return x.status === "done"; }).length, err = items.filter(function (x) { return x.status === "error"; }).length;
    var pending = n - done - err;
    $("#toolbar").hidden = !n; $("#drop").classList.toggle("compact", n > 0);
    var pill = $("#queuePill");
    pill.className = "pill " + (pending ? "busy" : err ? "warn" : "ok");
    $("#queueText").textContent = pending ? ("Leyendo " + (done + err + 1) + " de " + n) : (done + " de " + n + " leídas" + (err ? " · " + err + " con error" : ""));
    var pr = $("#queueProgress"); pr.hidden = !pending; pr.firstElementChild.style.width = Math.round(100 * (done + err) / Math.max(1, n)) + "%";
    var any = done > 0; ["#btnCopyAll", "#btnTxt", "#btnMd", "#btnSave", "#btnAgent"].forEach(function (s) { $(s).disabled = !any; });
  }
  function processQueue() {
    if (processing) return;
    var it = items.filter(function (x) { return x.status === "queued"; })[0];
    if (!it) { updateToolbar(); return; }
    processing = true;
    var p = it.path ? Promise.resolve(it.path) : (function () { it.status = "uploading"; updateItem(it); return shrink(it.file).then(function (b) { return PixAgent.upload([b]); }).then(function (paths) { it.path = paths[0]; return it.path; }); })();
    p.then(function (path) {
      it.status = "running"; updateItem(it); updateToolbar();
      var opts = { images: [path] };
      if ($("#modelSel").value) opts.model = $("#modelSel").value;
      if ($("#fmtSel").value === "plain") opts.prompt = "Devuelve solo texto plano, sin formato Markdown.";
      return PixAgent.local.run("ocr", opts);
    }).then(function (r) {
      it.text = (r.text || "").trim(); it.seconds = r.usage && r.usage.seconds; it.model = r.model || ""; it.status = "done";
    }).catch(function (e) {
      it.error = friendlyError(e); it.status = "error";
    }).then(function () {
      updateItem(it); processing = false; updateToolbar();
      if (items.indexOf(it) >= 0) setTimeout(processQueue, 50); else processQueue();
    });
  }

  /* ---------------- exportar ---------------- */
  function doneItems() { return items.filter(function (x) { return x.status === "done"; }); }
  function asPlain() { return doneItems().map(function (x) { return x.text; }).join("\n\n——————————\n\n"); }
  function asMarkdown() {
    return "# Texto leído (OCR local)\n\n" + doneItems().map(function (x, i) { return "## " + (i + 1) + ". " + x.name + "\n\n" + x.text; }).join("\n\n") + "\n";
  }
  function save() {
    $("#btnSave").disabled = true;
    return PixAgent.save("ocr_" + stamp() + ".md", asMarkdown(), { folder: "ocr" })
      .then(function (p) { toast("Guardado en " + p); return p; })
      .catch(function (e) { notice("err", "No se pudo guardar", friendlyError(e)); return null; })
      .then(function (p) { $("#btnSave").disabled = false; return p; });
  }
  function sendToAgent() {
    var imgs = doneItems().map(function (x) { return x.path; }).filter(Boolean).slice(0, 8);
    var md = asMarkdown(); var inline = md.length > 6000 ? "" : "\n\n" + md;
    save().then(function (p) {
      var atts = (p ? [p] : []).concat(imgs);
      PixAgent.sendToAgent("Revisa este texto leído por OCR con el modelo local (corrige errores evidentes comparando con las imágenes adjuntas, respeta cifras y unidades) y devuélvelo limpio y bien estructurado." + (p && !inline ? " El texto completo está en el archivo adjunto." : inline), atts);
      toast("Enviado al agente");
    });
  }

  /* ---------------- imagen en grande ---------------- */
  function openLightbox(it) {
    var lb = $("#lightbox"), img = $("#lbImg");
    lb.hidden = false; document.body.style.overflow = "hidden";
    img.alt = it.name; img.src = it.url; $("#lbCap").textContent = it.name;
    if (hasZoom && !lbz) { try { lbz = PixZoom.attach($("#lbBox"), img, { wheel: "zoom" }); } catch (e) { lbz = null; } }
    if (lbz) { img.onload = function () { lbz.fit(); }; if (img.complete) lbz.fit(); }
    else { img.style.maxWidth = "100%"; img.style.maxHeight = "100%"; img.style.margin = "auto"; img.style.position = "absolute"; img.style.inset = "0"; img.style.objectFit = "contain"; img.style.width = "100%"; img.style.height = "100%"; }
    $("#lbClose").focus();
  }
  function closeLightbox() { $("#lightbox").hidden = true; document.body.style.overflow = ""; }

  /* ---------------- arranque ---------------- */
  function init() {
    var drop = $("#drop");
    $("#btnPick").onclick = function () { $("#filePick").click(); };
    $("#btnShoot").onclick = function () { $("#fileShoot").click(); };
    $("#filePick").addEventListener("change", function () { addFiles(this.files); this.value = ""; });
    $("#fileShoot").addEventListener("change", function () { addFiles(this.files, "foto"); this.value = ""; });
    ["dragenter", "dragover"].forEach(function (ev) { document.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { document.addEventListener(ev, function (e) { e.preventDefault(); if (ev === "drop" || e.target === document.documentElement || !e.relatedTarget) drop.classList.remove("over"); }); });
    document.addEventListener("drop", function (e) { if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) addFiles(e.dataTransfer.files); });
    document.addEventListener("paste", function (e) {
      var its = e.clipboardData && e.clipboardData.items; if (!its) return; var files = [];
      for (var i = 0; i < its.length; i++) if (its[i].kind === "file" && /^image\//.test(its[i].type)) files.push(its[i].getAsFile());
      if (files.length) { e.preventDefault(); addFiles(files, "captura"); }
    });
    $("#btnCopyAll").onclick = function () { copy(asPlain(), "Texto de " + doneItems().length + " imágenes copiado"); };
    $("#btnTxt").onclick = function () { downloadFile("ocr_" + stamp() + ".txt", asPlain()); };
    $("#btnMd").onclick = function () { downloadFile("ocr_" + stamp() + ".md", asMarkdown(), "text/markdown;charset=utf-8"); };
    $("#btnSave").onclick = save;
    $("#btnAgent").onclick = sendToAgent;
    $("#btnClear").onclick = clearAll;
    $("#modelSel").addEventListener("change", updateAdvSum); $("#fmtSel").addEventListener("change", updateAdvSum);
    $("#lbClose").onclick = closeLightbox;
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !$("#lightbox").hidden) closeLightbox(); });
    updateAdvSum(); updateToolbar();
    loadStatus().then(updateAdvSum);
  }
  init();
})();
