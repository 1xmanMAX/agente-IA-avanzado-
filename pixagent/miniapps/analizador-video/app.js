/* Analizador de vídeo — mini app de PixAgent.
   Fuentes: archivo (subida con progreso), enlace (yt-dlp en el anfitrión) o en directo (cámara /
   pantalla: cada N segundos se envía un fotograma al modelo local, solo si la imagen cambió).
   Los resultados llegan en streaming (PixAgent.local.video + onUpdate) y se exportan a .md.
   ES2019 / Safari iOS 15. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  var hasZoom = !!(window.PixZoom && typeof window.PixZoom.attach === "function");

  var st = null;                                 // /api/local/status
  var src = "file";                              // file | url | live
  var every = "5";                               // 2 | 5 | 10 | scene
  var file = { path: null, name: "", size: 0 };  // vídeo subido
  var job = null;                                // {id, items, status, ...} del servidor
  var running = false, cancelled = false;
  var items = [];                                // entradas mostradas (servidor o directo)
  var rendered = 0;
  var lbIndex = -1, lbz = null;
  var live = { stream: null, timer: null, paused: false, inflight: false, sig: null, kind: "", t0: 0, n: 0, same: 0 };
  var elapsedTimer = null;

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
    if (href) { b.href = href; } else b.type = "button";
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
  function fmtT(t) { t = Math.max(0, Math.floor(t || 0)); var h = Math.floor(t / 3600), m = Math.floor(t % 3600 / 60), s = t % 60, p = function (n) { return (n < 10 ? "0" : "") + n; }; return (h ? p(h) + ":" : "") + p(m) + ":" + p(s); }
  function fmtSize(b) { return b > 1e9 ? (b / 1e9).toFixed(2).replace(".", ",") + " GB" : b > 1e6 ? (b / 1e6).toFixed(1).replace(".", ",") + " MB" : Math.round(b / 1e3) + " KB"; }
  function fmtSec(s) { return s == null ? "" : (s < 10 ? (Math.round(s * 10) / 10).toString().replace(".", ",") : Math.round(s)) + " s"; }
  /* Markdown mínimo y seguro para el resumen: viñetas y negritas */
  function miniMd(text) {
    var out = [], list = [];
    function flush() { if (list.length) { out.push("<ul>" + list.map(function (l) { return "<li>" + l + "</li>"; }).join("") + "</ul>"); list = []; } }
    String(text || "").split(/\r?\n/).forEach(function (line) {
      var h = esc(line.trim()).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
      var m = /^[-*•]\s+(.*)$/.exec(h);
      if (m) list.push(m[1]); else { flush(); if (h) out.push("<p>" + h + "</p>"); }
    });
    flush();
    return out.join("");
  }
  function cap1(s) { s = String(s || ""); return s.charAt(0).toUpperCase() + s.slice(1); }
  function setTab(t) { $("#app").dataset.tab = t; $$(".tabs [role=tab]").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.tab === t)); }); }
  function isMobile() { return window.matchMedia("(max-width: 900px)").matches; }

  /* ---------------- estado de la IA local ---------------- */
  function engines() { return (st && st.engines || []).filter(function (e) { return e.online; }); }
  function visionReady() { return !!(st && st.assigned && st.assigned.vision); }
  function loadStatus() {
    return PixAgent.local.status().then(function (s) { st = s; renderStatus(); }).catch(function (e) {
      setPill("err", "Sin conexión"); notice("err", "No se pudo consultar la IA local", friendlyError(e));
    });
  }
  function setPill(kind, text) { var p = $("#statusPill"); p.className = "pill " + kind; p.lastElementChild.textContent = text; }
  function renderStatus() {
    var on = engines();
    var v = st.assigned && st.assigned.vision;
    if (!on.length) setPill("err", "Sin IA local");
    else if (!v) setPill("warn", "Falta un modelo de visión");
    else setPill("ok", isMobile() ? v[1] : v[0] + " · " + v[1]);
    $("#ytWarn").hidden = !!(st.video && st.video.youtube);
    $("#asrHint").textContent = st.asr && st.asr.faster_whisper ? "Con Whisper local, alineada por tiempo" : "Requiere faster-whisper en el anfitrión (pip install faster-whisper)";
    var sel = $("#modelSel"); var cur = sel.value;
    sel.innerHTML = '<option value="">Automático' + (v ? " (" + esc(v[1]) + ")" : "") + "</option>" +
      (st.installed || []).filter(function (m) { return (m.caps || []).indexOf("vision") >= 0; }).map(function (m) { return '<option value="' + esc(m.id) + '">' + esc(m.id) + "</option>"; }).join("");
    sel.value = cur; if (sel.value !== cur) sel.value = "";
    if (!on.length) {
      notice("warn", "No hay ningún motor de IA local en marcha",
        "Instala Ollama (ollama.com) o arranca llama.cpp / LM Studio en el equipo anfitrión y descarga un modelo de visión. Puedes hacerlo desde la mini app IA local.",
        [mkBtn("Abrir IA local", "i-brain", "soft", null, "/apps/ia-local/")]);
    } else if (!v) {
      notice("warn", "Falta un modelo de visión", "Descarga uno (p. ej. qwen3.5:4b) desde la mini app IA local.", [mkBtn("Abrir IA local", "i-brain", "soft", null, "/apps/ia-local/")]);
    }
    if (st.video && !st.video.ffmpeg) notice("err", "Falta ffmpeg en el equipo anfitrión", "Se necesita para extraer fotogramas: pip install imageio-ffmpeg (o ffmpeg del sistema). El modo en directo sí funciona.");
    updateGo();
  }

  /* ---------------- fuente ---------------- */
  function setSrc(s) {
    src = s; $("#app").dataset.src = s;
    $$("#srcTabs button").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.src === s)); });
    $("#srcFile").hidden = s !== "file"; $("#srcUrl").hidden = s !== "url"; $("#srcLive").hidden = s !== "live";
    $("#optsBlock").hidden = s === "live"; $("#goBlock").hidden = s === "live";
    if (s === "live" && !$("#liveBox").hidden) updateLiveActs();
    updateGo();
  }
  function updateGo() {
    var b = $("#btnStart"), hint = $("#goHint");
    var ready = src === "file" ? !!file.path : src === "url" ? /^https?:\/\/\S+/i.test($("#urlInp").value.trim()) : false;
    b.disabled = running || !ready;
    hint.textContent = running ? "Analizando… puedes seguir el progreso en Resultados." : !ready ? (src === "file" ? "Sube un vídeo para empezar." : "Escribe la dirección del vídeo.") : "";
  }
  function uploadWithProgress(f) {
    return new Promise(function (resolve, reject) {
      var xhr = new XMLHttpRequest(); var fd = new FormData(); fd.append("files", f, f.name || "video.mp4");
      xhr.open("POST", "/api/upload");
      xhr.upload.onprogress = function (e) { if (e.lengthComputable) setUpload(e.loaded / e.total, "Subiendo " + fmtSize(e.loaded) + " de " + fmtSize(e.total) + "…"); };
      xhr.onload = function () {
        try { var d = JSON.parse(xhr.responseText); if (xhr.status >= 400 || !d.files) throw new Error(d.error || ("HTTP " + xhr.status)); resolve(d.files[0]); }
        catch (e) { reject(e); }
      };
      xhr.onerror = function () { reject(new Error("No hay conexión con el servidor de PixAgent.")); };
      xhr.send(fd);
    });
  }
  function setUpload(frac, text) {
    var bar = $("#upProgress"), txt = $("#upText");
    if (frac == null) { bar.hidden = true; txt.hidden = true; return; }
    bar.hidden = false; txt.hidden = false; bar.firstElementChild.style.width = Math.round(frac * 100) + "%"; txt.textContent = text;
  }
  function addVideo(f) {
    if (!f) return;
    if (!/^video\//.test(f.type) && !/\.(mp4|mov|m4v|webm|mkv|avi|3gp|mpg|mpeg|ts)$/i.test(f.name || "")) { toast("Elige un archivo de vídeo"); return; }
    $("#btnPick").disabled = true; setUpload(0, "Preparando…");
    uploadWithProgress(f).then(function (path) {
      file = { path: path, name: f.name || path.split("/").pop(), size: f.size };
      $("#fcName").textContent = file.name; $("#fcMeta").textContent = fmtSize(f.size) + " · " + path;
      $("#fileCard").hidden = false; $("#drop").hidden = true; setUpload(null);
      toast("Vídeo subido");
    }).catch(function (e) { setUpload(null); notice("err", "No se pudo subir el vídeo", friendlyError(e)); })
      .then(function () { $("#btnPick").disabled = false; updateGo(); });
  }
  function changeFile() { file = { path: null, name: "", size: 0 }; $("#fileCard").hidden = true; $("#drop").hidden = false; $("#filePick").value = ""; updateGo(); }

  /* ---------------- opciones ---------------- */
  function updateAdvSum() {
    var m = $("#modelSel").value, p = $("#promptInp").value.trim(), n = $("#maxFrames").value || 120;
    $("#advSum").textContent = "Máx. " + n + " fotogramas · " + (p ? "prompt propio" : "prompt estándar") + " · " + (m ? m : "modelo automático") + ($("#summary").checked ? "" : " · sin resumen");
  }
  function buildSpec() {
    var spec = { source: src === "file" ? file.path : $("#urlInp").value.trim(), max_frames: Math.max(1, Math.min(2000, parseInt($("#maxFrames").value, 10) || 120)),
      transcribe: $("#transcribe").checked, summary: $("#summary").checked };
    if (every === "scene") { spec.scene = 0.3; spec.every = 2; } else spec.every = parseInt(every, 10);
    var p = $("#promptInp").value.trim(); if (p) spec.prompt = p;
    var m = $("#modelSel").value; if (m) spec.model = m;
    return spec;
  }

  /* ---------------- análisis en el servidor ---------------- */
  function start() {
    if (running) return;
    var spec = buildSpec();
    resetRun(src === "file" ? file.name : spec.source, "Análisis de vídeo");
    running = true; cancelled = false; updateGo();
    if (isMobile()) setTab("results");
    PixAgent.local.video(spec, onUpdate).then(function (d) {
      onUpdate(d);
      finish(d.status === "done" ? "ok" : d.status === "cancelled" ? "cancelled" : "error", d.error);
    }).catch(function (e) {
      finish("error", friendlyError(e));
    });
  }
  function resetRun(sourceLabel, title) {
    items = []; rendered = 0; job = null;
    $("#emptyState").hidden = true; var run = $("#run"); run.hidden = false; run.classList.remove("done");
    $("#runTitle").textContent = title; $("#runSource").textContent = sourceLabel || "";
    $("#runStage").textContent = "Preparando…"; $("#runPill").className = "pill busy";
    $("#runProgress").firstElementChild.style.width = "0%"; $("#runProgress").classList.add("indet"); $("#runProgress").hidden = false;
    $("#runCount").textContent = ""; $("#runElapsed").textContent = "";
    $("#runError").hidden = true; $("#summaryCard").hidden = true; $("#transcriptBox").hidden = true; $("#exportBar").hidden = true;
    $("#timeline").innerHTML = ""; $("#btnCancel").hidden = false; $("#tabBadge").hidden = true;
    var t0 = Date.now(); clearInterval(elapsedTimer);
    elapsedTimer = setInterval(function () { $("#runElapsed").textContent = fmtT((Date.now() - t0) / 1000) + " transcurridos"; }, 1000);
  }
  function onUpdate(d) {
    job = d;
    $("#runStage").textContent = d.status === "running" ? cap1(d.stage || "Procesando") + "…" : d.status === "done" ? "Completado" : d.status === "cancelled" ? "Cancelado" : "Error";
    var bar = $("#runProgress");
    if (d.progress > 0) { bar.classList.remove("indet"); bar.firstElementChild.style.width = Math.round(d.progress * 100) + "%"; }
    var total = d.total_items || (d.items || []).length;
    $("#runCount").textContent = total ? total + " fotogramas · " + (d.items || []).filter(function (it) { return !it.same && !it.error; }).length + " descritos" : "";
    items = d.items || [];
    renderNewItems();
    if (d.summary) { $("#summaryCard").hidden = false; $("#summaryText").innerHTML = miniMd(d.summary); }
    if (d.transcript && d.transcript.length) renderTranscript(d.transcript);
  }
  function renderNewItems() {
    var ol = $("#timeline");
    for (; rendered < items.length; rendered++) {
      var it = items[rendered];
      if (it.same) {
        var last = ol.lastElementChild;
        if (last && last.classList.contains("same")) {
          var n = (+last.dataset.n || 1) + 1; last.dataset.n = n; last.dataset.end = it.time;
          last.querySelector(".tx").textContent = "Sin cambios · " + last.dataset.start + " – " + it.time + " · " + n + " fotogramas";
          continue;
        }
        var li = document.createElement("li"); li.className = "tl same"; li.dataset.n = 1; li.dataset.start = it.time; li.dataset.end = it.time;
        li.innerHTML = '<span class="t">' + esc(it.time) + '</span><span class="tx">Sin cambios</span>';
        ol.appendChild(li);
        continue;
      }
      var el = entry(it, rendered); el.classList.add("in"); ol.appendChild(el);
      setTimeout(function () { el.classList.remove("in"); }, 300);
    }
    if (isMobile() && $("#app").dataset.tab !== "results") { var b = $("#tabBadge"); b.hidden = false; b.textContent = items.length; }
  }
  function entry(it, idx) {
    var li = document.createElement("li"); li.className = "tl" + (it.error ? " err" : "") + (it.live ? " live" : ""); li.tabIndex = 0; li.dataset.idx = idx;
    li.setAttribute("role", "button"); li.setAttribute("aria-label", "Ver el fotograma de " + it.time + " en grande");
    var thumb = it.thumb || (it.frame ? PixAgent.thumbUrl(it.frame, 240) : "");
    li.innerHTML = '<span class="t">' + esc(it.time) + '</span><span class="th">' + (thumb ? '<img alt="" loading="lazy" src="' + esc(thumb) + '">' : "") + "</span>" +
      '<span class="tx"><span>' + esc(it.error ? "Error: " + it.error : it.text || "(sin descripción)") + "</span>" +
      (it.seconds ? '<small><svg class="i sm" style="width:12px;height:12px"><use href="#i-clock"/></svg> ' + esc(fmtSec(it.seconds)) + "</small>" : "") + "</span>";
    li.addEventListener("click", function () { openLightbox(idx); });
    li.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openLightbox(idx); } });
    return li;
  }
  function renderTranscript(segs) {
    $("#transcriptBox").hidden = false; $("#transcriptSum").textContent = segs.length + (segs.length === 1 ? " segmento" : " segmentos");
    $("#transcript").innerHTML = segs.map(function (s) { return "<li><b>" + esc(fmtT(s.start)) + "</b><span>" + esc(s.text) + "</span></li>"; }).join("");
  }
  function finish(kind, error) {
    running = false; clearInterval(elapsedTimer); updateGo();
    var run = $("#run"); run.classList.add("done"); $("#btnCancel").hidden = true;
    $("#runPill").className = "pill " + (kind === "ok" ? "ok" : kind === "cancelled" ? "warn" : "err");
    $("#runStage").textContent = kind === "ok" ? "Completado" : kind === "cancelled" ? "Cancelado" : "Error";
    if (kind === "error") { $("#runError").hidden = false; $("#runErrorText").textContent = error || "Error desconocido"; }
    if (items.length) {
      $("#exportBar").hidden = false;
      var md = $("#btnOpenMd");
      if (job && job.out_dir) { md.hidden = false; md.href = PixAgent.fileUrl(job.out_dir + "/analisis.md"); } else md.hidden = true;
    }
    if (kind === "ok") toast("Análisis completado");
  }
  function cancel() {
    if (job && job.id) PixAgent.local.cancel(job.id).catch(function () { /* se detiene igualmente al terminar el fotograma */ });
    cancelled = true; $("#runStage").textContent = "Cancelando…";
  }

  /* ---------------- exportar ---------------- */
  function asMarkdown() {
    var lines = ["# Análisis de vídeo", "", "Fuente: " + ($("#runSource").textContent || "en directo"), ""];
    if (job && job.summary) lines.push("## Resumen", "", job.summary, "");
    lines.push("## Fotograma a fotograma", "");
    var i = 0;
    while (i < items.length) {
      var it = items[i];
      if (it.same) { var j = i; while (j + 1 < items.length && items[j + 1].same) j++; lines.push("- **" + it.time + (j > i ? " – " + items[j].time : "") + "** — Sin cambios" + (j > i ? " (" + (j - i + 1) + " fotogramas)" : "")); i = j + 1; continue; }
      lines.push("- **" + it.time + "** — " + (it.text || (it.error ? "(error: " + it.error + ")" : ""))); i++;
    }
    if (job && job.transcript && job.transcript.length) { lines.push("", "## Transcripción", ""); job.transcript.forEach(function (s) { lines.push("- **" + fmtT(s.start) + "** " + s.text); }); }
    return lines.join("\n");
  }
  function download() {
    var blob = new Blob([asMarkdown()], { type: "text/markdown;charset=utf-8" });
    var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "analisis_video" + (job && job.id ? "_" + job.id : "") + ".md";
    document.body.appendChild(a); a.click(); setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
  }
  function save() {
    $("#btnSave").disabled = true;
    PixAgent.save("analisis_" + (job && job.id ? job.id : "directo_" + Date.now()) + ".md", asMarkdown(), { folder: "video" })
      .then(function (p) { toast("Guardado en " + p); }).catch(function (e) { notice("err", "No se pudo guardar", friendlyError(e)); })
      .then(function () { $("#btnSave").disabled = false; });
  }
  function sendToAgent() {
    var srcLabel = $("#runSource").textContent || "captura en directo";
    if (job && job.out_dir) {
      PixAgent.sendToAgent("Redacta un informe del vídeo «" + srcLabel + "» a partir del análisis adjunto (analisis.md): qué ocurre por tramos de tiempo, incidencias o puntos de atención y conclusiones. No inventes nada que no esté en el análisis.",
        [job.out_dir + "/analisis.md"]);
    } else {
      var md = asMarkdown(); if (md.length > 7000) md = md.slice(0, 7000) + "\n…(recortado)";
      PixAgent.sendToAgent("Redacta un informe breve a partir de esta descripción fotograma a fotograma (" + srcLabel + "). No inventes nada que no esté en el texto.\n\n" + md);
    }
    toast("Enviado al agente");
  }

  /* ---------------- imagen en grande ---------------- */
  function viewable() { return items.map(function (it, i) { return { it: it, i: i }; }).filter(function (x) { return !x.it.same && (x.it.frame || x.it.thumb); }); }
  function openLightbox(idx) {
    var list = viewable(); var pos = -1;
    for (var k = 0; k < list.length; k++) if (list[k].i === idx) pos = k;
    if (pos < 0) return;
    lbIndex = pos;
    var it = list[pos].it, lb = $("#lightbox"), img = $("#lbImg");
    lb.hidden = false; document.body.style.overflow = "hidden";
    img.alt = "Fotograma " + it.time; img.src = it.full || (it.frame ? PixAgent.fileUrl(it.frame) : it.thumb);
    $("#lbCap").textContent = it.time + " · " + (it.text || "");
    $("#lbPrev").disabled = pos === 0; $("#lbNext").disabled = pos === list.length - 1;
    if (hasZoom && !lbz) { try { lbz = PixZoom.attach($("#lbBox"), img, { wheel: "zoom" }); } catch (e) { lbz = null; } }
    if (lbz) { img.onload = function () { lbz.fit(); }; if (img.complete) lbz.fit(); }
    else { img.style.maxWidth = "100%"; img.style.maxHeight = "100%"; img.style.margin = "auto"; img.style.position = "absolute"; img.style.inset = "0"; img.style.objectFit = "contain"; img.style.width = "100%"; img.style.height = "100%"; }
    $("#lbClose").focus();
  }
  function lbStep(d) { var list = viewable(); var n = lbIndex + d; if (n < 0 || n >= list.length) return; openLightbox(list[n].i); }
  function closeLightbox() { $("#lightbox").hidden = true; document.body.style.overflow = ""; lbIndex = -1; }

  /* ---------------- en directo ---------------- */
  function startLive(kind) {
    var p = kind === "screen"
      ? (navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia ? navigator.mediaDevices.getDisplayMedia({ video: true, audio: false }) : Promise.reject(new Error("Este navegador no permite capturar la pantalla. Prueba en un ordenador con Chrome, Edge o Safari.")))
      : (navigator.mediaDevices && navigator.mediaDevices.getUserMedia ? navigator.mediaDevices.getUserMedia({ video: { facingMode: "environment", width: { ideal: 1280 } }, audio: false }) : Promise.reject(new Error("Este navegador no permite usar la cámara.")));
    $("#btnCam").disabled = true; $("#btnScreen").disabled = true;
    p.then(function (stream) {
      live.stream = stream; live.kind = kind; live.paused = false; live.sig = null; live.n = 0; live.same = 0; live.t0 = Date.now();
      var v = $("#liveVideo"); v.srcObject = stream; v.play().catch(function () { /* autoplay silenciado */ });
      stream.getVideoTracks()[0].addEventListener("ended", stopLive);
      $("#liveBox").hidden = false; $("#livePick").hidden = true; $("#liveOpts").hidden = false; $("#liveActs").hidden = false; $("#liveHint").hidden = true;
      resetRun(kind === "screen" ? "pantalla" : "cámara", "En directo");
      $("#btnCancel").hidden = true; $("#runProgress").hidden = true; $("#runStage").textContent = "Observando…";
      $("#liveLast").hidden = true;
      updateLiveActs(); scheduleTick();
    }).catch(function (e) {
      var m = friendlyError(e);
      if (/NotAllowed|Permission|denied/i.test(m)) m = "Permiso denegado. Permite el acceso a la " + (kind === "screen" ? "pantalla" : "cámara") + " en el navegador y vuelve a intentarlo.";
      else if (/NotFound|Requested device/i.test(m)) m = "No se ha encontrado ninguna cámara.";
      notice("err", kind === "screen" ? "No se pudo capturar la pantalla" : "No se pudo abrir la cámara", m);
    }).then(function () { $("#btnCam").disabled = false; $("#btnScreen").disabled = false; });
  }
  function scheduleTick() { clearTimeout(live.timer); if (!live.stream) return; live.timer = setTimeout(tick, parseInt($("#liveEvery").value, 10) * 1000); }
  function grab() {
    var v = $("#liveVideo"); if (!v.videoWidth) return null;
    var c = document.createElement("canvas"); var k = Math.min(1, 640 / v.videoWidth);
    c.width = Math.round(v.videoWidth * k); c.height = Math.round(v.videoHeight * k);
    c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
    var s = document.createElement("canvas"); s.width = 32; s.height = 32;
    var sctx = s.getContext("2d"); sctx.drawImage(c, 0, 0, 32, 32);
    var d = sctx.getImageData(0, 0, 32, 32).data, sig = new Array(1024);
    for (var i = 0; i < 1024; i++) sig[i] = (d[i * 4] * 299 + d[i * 4 + 1] * 587 + d[i * 4 + 2] * 114) / 1000;
    return { canvas: c, sig: sig };
  }
  function diff(a, b) { var s = 0; for (var i = 0; i < a.length; i++) s += Math.abs(a[i] - b[i]); return s / a.length; }
  function tick() {
    if (!live.stream || live.paused) return;
    if (live.inflight) { scheduleTick(); return; }       // una sola petición en vuelo
    var g = grab(); if (!g) { scheduleTick(); return; }
    var t = (Date.now() - live.t0) / 1000;
    if (live.sig && diff(g.sig, live.sig) < 6) {           // casi idéntico: no se gasta una inferencia
      live.same++;
      items.push({ t: t, time: fmtT(t), text: "Sin cambios.", same: true }); renderNewItems(); updateLiveCount();
      scheduleTick(); return;
    }
    live.sig = g.sig; live.inflight = true;
    var thumb = g.canvas.toDataURL("image/jpeg", 0.7);
    var item = { t: t, time: fmtT(t), text: "", thumb: thumb, full: thumb, live: true, pending: true };
    items.push(item); renderNewItems();
    var li = $("#timeline").lastElementChild; li.querySelector(".tx > span").innerHTML = '<span class="spin" style="display:inline-block;vertical-align:-4px;margin-right:6px"></span>Describiendo…';
    $("#runStage").textContent = "Describiendo…"; setLiveLast(item.time, "Describiendo…", true);
    var prompt = $("#livePrompt").value.trim();
    var t0 = Date.now();
    PixAgent.local.frame(g.canvas, prompt || "Describe en una o dos frases, en español, SOLO lo que se ve en esta imagen. No inventes personas, objetos ni acciones que no aparezcan. Si hay texto en pantalla, cítalo.")
      .then(function (r) { item.text = (r.text || "").replace(/^[:\s]+/, ""); item.seconds = (r.usage && r.usage.seconds) || (Date.now() - t0) / 1000; })
      .catch(function (e) { item.error = friendlyError(e); })
      .then(function () {
        item.pending = false; live.inflight = false; live.n++;
        var idx = items.indexOf(item);
        if (li && li.parentNode) li.parentNode.replaceChild(entry(item, idx), li);
        setLiveLast(item.time, item.error ? "Error: " + item.error : item.text, false);
        $("#runStage").textContent = live.paused ? "En pausa" : "Observando…"; updateLiveCount();
        if (!live.paused) scheduleTick();
      });
  }
  function setLiveLast(t, text, pending) {
    var box = $("#liveLast"); box.hidden = false; box.classList.toggle("pending", !!pending);
    $("#liveLastT").textContent = t; $("#liveLastTx").textContent = text || "(sin descripción)";
  }
  function updateLiveCount() { $("#runCount").textContent = live.n + " descritos · " + live.same + " sin cambios"; if (!$("#exportBar").hidden || items.length) { $("#exportBar").hidden = false; $("#btnOpenMd").hidden = true; } }
  function toggleLive() {
    live.paused = !live.paused;
    if (live.paused) { clearTimeout(live.timer); $("#runStage").textContent = "En pausa"; $("#runPill").className = "pill warn"; }
    else { $("#runStage").textContent = "Observando…"; $("#runPill").className = "pill busy"; scheduleTick(); }
    updateLiveActs();
  }
  function updateLiveActs() {
    var b = $("#btnLiveToggle"); b.innerHTML = live.paused ? '<svg class="i"><use href="#i-play"/></svg> Reanudar' : '<svg class="i"><use href="#i-pause"/></svg> Pausar';
    b.className = "btn " + (live.paused ? "primary" : ""); $("#liveTag").classList.toggle("paused", live.paused);
    $("#liveTag").lastChild.textContent = live.paused ? " En pausa" : " En directo";
  }
  function stopLive() {
    clearTimeout(live.timer);
    if (live.stream) { live.stream.getTracks().forEach(function (t) { t.stop(); }); live.stream = null; }
    $("#liveVideo").srcObject = null; $("#liveBox").hidden = true; $("#liveLast").hidden = true; $("#livePick").hidden = false; $("#liveOpts").hidden = true; $("#liveActs").hidden = true; $("#liveHint").hidden = false;
    clearInterval(elapsedTimer); live.paused = false;
    if (!$("#run").hidden) { $("#run").classList.add("done"); $("#runPill").className = "pill ok"; $("#runStage").textContent = "Terminado"; if (items.length) { $("#exportBar").hidden = false; $("#btnOpenMd").hidden = true; } }
  }

  /* ---------------- arranque ---------------- */
  function init() {
    $$(".tabs [role=tab]").forEach(function (b) { b.onclick = function () { setTab(b.dataset.tab); if (b.dataset.tab === "results") $("#tabBadge").hidden = true; }; });
    $$("#srcTabs button").forEach(function (b) { b.onclick = function () { setSrc(b.dataset.src); }; });
    $$("#segEvery button").forEach(function (b) { b.onclick = function () { every = b.dataset.v; $$("#segEvery button").forEach(function (x) { x.setAttribute("aria-pressed", String(x === b)); }); }; });
    ["#maxFrames", "#modelSel", "#promptInp", "#summary"].forEach(function (s) { $(s).addEventListener("change", updateAdvSum); $(s).addEventListener("input", updateAdvSum); });
    // archivo
    var drop = $("#drop");
    $("#btnPick").onclick = function () { $("#filePick").click(); };
    $("#filePick").addEventListener("change", function () { addVideo(this.files[0]); });
    ["dragenter", "dragover"].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("over"); }); });
    drop.addEventListener("drop", function (e) { var f = e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files[0]; addVideo(f); });
    $("#btnChangeFile").onclick = changeFile;
    $("#urlInp").addEventListener("input", updateGo);
    $("#urlInp").addEventListener("keydown", function (e) { if (e.key === "Enter" && !$("#btnStart").disabled) start(); });
    $("#btnStart").onclick = start;
    $("#btnCancel").onclick = cancel;
    // directo
    $("#btnCam").onclick = function () { startLive("camera"); };
    $("#btnScreen").onclick = function () { startLive("screen"); };
    $("#btnLiveToggle").onclick = toggleLive;
    $("#btnLiveStop").onclick = stopLive;
    $("#liveEvery").addEventListener("change", function () { if (live.stream && !live.paused && !live.inflight) scheduleTick(); });
    if (!(navigator.mediaDevices && navigator.mediaDevices.getDisplayMedia)) { $("#btnScreen").disabled = true; $("#btnScreen").title = "Capturar la pantalla no está disponible en este navegador"; }
    // exportar
    $("#btnCopy").onclick = function () { copy(asMarkdown(), "Texto copiado"); };
    $("#btnDownload").onclick = download;
    $("#btnSave").onclick = save;
    $("#btnAgent").onclick = sendToAgent;
    // imagen en grande
    $("#lbClose").onclick = closeLightbox; $("#lbPrev").onclick = function () { lbStep(-1); }; $("#lbNext").onclick = function () { lbStep(1); };
    document.addEventListener("keydown", function (e) {
      if ($("#lightbox").hidden) return;
      if (e.key === "Escape") closeLightbox(); else if (e.key === "ArrowLeft") lbStep(-1); else if (e.key === "ArrowRight") lbStep(1);
    });
    window.addEventListener("beforeunload", function () { if (live.stream) live.stream.getTracks().forEach(function (t) { t.stop(); }); });
    updateAdvSum(); setSrc("file");
    loadStatus();
  }
  init();
})();
