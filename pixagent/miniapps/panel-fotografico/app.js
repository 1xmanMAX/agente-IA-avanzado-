/* Panel fotográfico — mini app de PixAgent.
   Todo el maquetado ocurre en el navegador (vista previa fiel al PDF que genera panel.py en el servidor).
   La IA solo entra si el usuario pulsa "Pies con IA" (una única llamada barata). ES2019 / Safari iOS 15. */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var CM = 28.3465;                                  // puntos por cm (igual que reportlab)
  var PAGES = { A4: [595.28, 841.89], A3: [841.89, 1190.55] };
  var LAYOUTS = ["1x1", "1x2", "2x2", "2x3", "3x3", "3x4"];
  var PRESETS = ["#1f4e79", "#5b5bf7", "#0f766e", "#b45309", "#8b1d2c", "#374151"];
  var STORE = "pixagent.panel.v1";
  var PDF_FONT = '"DejaVu Sans", Verdana, Helvetica, Arial, sans-serif';

  function today() {
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    return d.getFullYear() + "-" + p(d.getMonth() + 1) + "-" + p(d.getDate());
  }
  function todayES() { var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; }; return p(d.getDate()) + "/" + p(d.getMonth() + 1) + "/" + d.getFullYear(); }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function uid() { return Math.random().toString(36).slice(2, 9); }
  function slug(s) { return String(s || "panel").normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^\w]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase().slice(0, 40) || "panel"; }

  function defaults() {
    return {
      title: "Panel fotográfico", subtitle: "",
      fields: [["Proyecto", ""], ["Ubicación", ""], ["Fecha", today()], ["Responsable", ""]],
      logo: null, layout: "2x3", page: "A4", orientation: "portrait", fit: "cover", numbering: true,
      theme: "#1f4e79", photos: []
    };
  }
  var state = defaults();
  var lastResult = null;

  /* ---------------- borrador ---------------- */
  var saveTimer = null;
  function saveDraft() {
    clearTimeout(saveTimer);
    $("#saveState").textContent = "Guardando…";
    saveTimer = setTimeout(function () {
      try { localStorage.setItem(STORE, JSON.stringify(state)); $("#saveState").textContent = "Borrador guardado"; }
      catch (e) { $("#saveState").textContent = "Sin guardado local"; }
    }, 400);
  }
  function loadDraft() {
    try {
      var raw = localStorage.getItem(STORE);
      if (!raw) return;
      var d = JSON.parse(raw);
      if (d && typeof d === "object") {
        var base = defaults();
        Object.keys(base).forEach(function (k) { if (d[k] !== undefined) state[k] = d[k]; });
        if (!Array.isArray(state.photos)) state.photos = [];
        if (!Array.isArray(state.fields)) state.fields = base.fields;
        state.photos.forEach(function (p) { if (!p.id) p.id = uid(); });
      }
    } catch (e) { /* almacenamiento no disponible: seguimos sin borrador */ }
  }

  /* ---------------- avisos ---------------- */
  var toastTimer;
  function toast(msg) {
    var t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2600);
    if (window.PixAgent && PixAgent.embedded) PixAgent.toast(msg);
  }
  function notice(kind, title, body, actions) {
    var mobile = window.matchMedia("(max-width: 900px)").matches;
    var box = mobile ? $("#noticesM") : $("#notices");
    if (!mobile) { var sc = $(".work .scroll"); if (sc) sc.scrollTop = 0; }
    var el = document.createElement("div");
    el.className = "notice " + kind;
    var icon = kind === "ok" ? "i-check" : kind === "err" ? "i-alert" : "i-image";
    el.innerHTML = (kind === "busy" ? '<span class="spin"></span>' : '<svg class="i"><use href="#' + icon + '"/></svg>') +
      '<div class="body"><b>' + esc(title) + "</b>" + (body ? "<span>" + esc(body) + "</span>" : "") +
      (actions ? '<div class="acts"></div>' : "") + "</div>" +
      '<button class="close" type="button" aria-label="Cerrar"><svg class="i sm"><use href="#i-x"/></svg></button>';
    el.querySelector(".close").onclick = function () { el.remove(); };
    if (actions) actions.forEach(function (a) { el.querySelector(".acts").appendChild(a); });
    box.insertBefore(el, box.firstChild);
    while (box.children.length > (mobile ? 1 : 3)) box.removeChild(box.lastChild);
    return el;
  }
  function mkBtn(label, icon, cls, onClick, href) {
    var b = document.createElement(href ? "a" : "button");
    b.className = "btn sm " + (cls || "");
    if (href) { b.href = href; b.target = "_blank"; b.rel = "noopener"; } else b.type = "button";
    b.innerHTML = '<svg class="i sm"><use href="#' + icon + '"/></svg> ' + esc(label);
    if (onClick) b.addEventListener("click", onClick);
    return b;
  }
  function friendlyError(e) {
    var m = (e && e.message) || String(e);
    if (/api[_ ]?key|ANTHROPIC|autenticaci|401|credential/i.test(m)) return "No hay clave de API configurada en PixAgent. La maquetación y el PDF funcionan igual sin IA.";
    if (/Failed to fetch|NetworkError|network/i.test(m)) return "No hay conexión con el servidor de PixAgent.";
    return m.length > 220 ? m.slice(0, 220) + "…" : m;
  }

  /* ---------------- fotos ---------------- */
  function activeFields() {
    return state.fields.filter(function (f) { return f[0] && String(f[0]).trim() && f[1] && String(f[1]).trim(); })
      .map(function (f) { return [String(f[0]).trim(), String(f[1]).trim()]; });
  }
  function thumb(p, w) { return PixAgent.thumbUrl(p.path, w || 480); }

  function renderPhotos() {
    var grid = $("#photos");
    grid.innerHTML = "";
    $("#photoCount").textContent = state.photos.length + (state.photos.length === 1 ? " foto" : " fotos");
    $("#photosEmpty").hidden = state.photos.length > 0;
    state.photos.forEach(function (p, i) {
      var el = document.createElement("article");
      el.className = "ph"; el.dataset.idx = i; el.draggable = true;
      el.innerHTML =
        '<div class="img"><img alt="" loading="lazy" src="' + thumb(p, 480) + '">' +
        '<span class="num">' + (i + 1) + "</span>" +
        '<button class="del" type="button" aria-label="Quitar foto ' + (i + 1) + '"><svg class="i sm"><use href="#i-trash"/></svg></button></div>' +
        '<textarea class="cap" rows="2" placeholder="Pie de foto…" aria-label="Pie de la foto ' + (i + 1) + '">' + esc(p.caption) + "</textarea>" +
        '<div class="mv"><button type="button" aria-label="Mover a la izquierda"' + (i === 0 ? " disabled" : "") + '><svg class="i"><use href="#i-left"/></svg></button>' +
        '<button type="button" aria-label="Mover a la derecha"' + (i === state.photos.length - 1 ? " disabled" : "") + '><svg class="i"><use href="#i-right"/></svg></button></div>';
      var img = el.querySelector("img");
      img.onerror = function () { img.alt = "No disponible"; img.style.objectFit = "contain"; };
      el.querySelector(".del").onclick = function () { state.photos.splice(i, 1); changed(true); };
      var mv = el.querySelectorAll(".mv button");
      mv[0].onclick = function () { move(i, i - 1); };
      mv[1].onclick = function () { move(i, i + 1); };
      var cap = el.querySelector(".cap");
      cap.addEventListener("input", function () { p.caption = cap.value; schedulePreview(); saveDraft(); });
      // arrastrar en escritorio
      el.addEventListener("dragstart", function (ev) { dragFrom = i; el.classList.add("dragging"); try { ev.dataTransfer.setData("text/plain", String(i)); ev.dataTransfer.effectAllowed = "move"; } catch (e) { /* IE */ } });
      el.addEventListener("dragend", function () { dragFrom = -1; $$(".ph").forEach(function (x) { x.classList.remove("dragging", "over"); }); });
      el.addEventListener("dragover", function (ev) { if (dragFrom < 0) return; ev.preventDefault(); ev.dataTransfer.dropEffect = "move"; el.classList.add("over"); });
      el.addEventListener("dragleave", function () { el.classList.remove("over"); });
      el.addEventListener("drop", function (ev) { if (dragFrom < 0) return; ev.preventDefault(); ev.stopPropagation(); move(dragFrom, i); });
      grid.appendChild(el);
    });
  }
  var dragFrom = -1;
  function move(from, to) {
    if (to < 0 || to >= state.photos.length || from === to) return;
    var it = state.photos.splice(from, 1)[0];
    state.photos.splice(to, 0, it);
    changed(true);
  }
  function changed(rerenderPhotos) {
    if (rerenderPhotos) renderPhotos();
    schedulePreview(); saveDraft();
  }

  /* reducción en el cliente: máx. 2400 px, JPEG 0,88 */
  function shrink(file) {
    return new Promise(function (resolve, reject) {
      var url = URL.createObjectURL(file);
      var img = new Image();
      img.onload = function () {
        URL.revokeObjectURL(url);
        var w = img.naturalWidth, h = img.naturalHeight;
        if (!w || !h) return reject(new Error("Imagen vacía: " + file.name));
        var k = Math.min(1, 2400 / Math.max(w, h));
        if (k === 1 && /jpe?g$/i.test(file.type) && file.size < 2500000) return resolve(file);
        var cw = Math.max(1, Math.round(w * k)), ch = Math.max(1, Math.round(h * k));
        var c = document.createElement("canvas"); c.width = cw; c.height = ch;
        var ctx = c.getContext("2d");
        ctx.drawImage(img, 0, 0, cw, ch);
        c.toBlob(function (b) {
          c.width = 1; c.height = 1; c = null;               // liberar memoria del canvas
          if (!b) return reject(new Error("No se pudo procesar " + file.name));
          var name = (file.name || "foto").replace(/\.[^.]+$/, "") + ".jpg";
          try { b = new File([b], name, { type: "image/jpeg" }); } catch (e) { b.name = name; }
          resolve(b);
        }, "image/jpeg", 0.88);
      };
      img.onerror = function () { URL.revokeObjectURL(url); reject(new Error("Formato no compatible: " + file.name)); };
      img.src = url;
    });
  }
  var uploading = false;
  function setProgress(done, total, label) {
    var bar = $("#progress"), txt = $("#progressText");
    if (total <= 0) { bar.hidden = true; txt.hidden = true; return; }
    bar.hidden = false; txt.hidden = false;
    bar.firstElementChild.style.width = Math.round(100 * done / total) + "%";
    txt.textContent = label;
  }
  function addFiles(fileList) {
    var files = Array.prototype.slice.call(fileList || []).filter(function (f) { return /^image\//.test(f.type) || /\.(jpe?g|png|webp|gif|bmp|heic|heif)$/i.test(f.name || ""); });
    if (!files.length) { toast("No se han encontrado imágenes."); return Promise.resolve(); }
    if (uploading) { toast("Espera a que termine la subida actual."); return Promise.resolve(); }
    uploading = true;
    var total = files.length, done = 0, errors = [];
    setProgress(0, total, "Preparando 1 de " + total + "…");
    var queue = files.slice();
    function nextBatch() {
      if (!queue.length) return Promise.resolve();
      var batch = queue.splice(0, 3);
      return Promise.all(batch.map(function (f) { return shrink(f).catch(function (e) { errors.push(e.message); return null; }); }))
        .then(function (blobs) {
          blobs = blobs.filter(Boolean);
          if (!blobs.length) return;
          setProgress(done, total, "Subiendo " + (done + 1) + "–" + Math.min(total, done + blobs.length) + " de " + total + "…");
          return PixAgent.upload(blobs).then(function (paths) {
            paths.forEach(function (p) { state.photos.push({ id: uid(), path: p, caption: "" }); });
            done += batch.length;
            setProgress(done, total, done + " de " + total + " subidas");
            renderPhotos(); schedulePreview(); saveDraft();
          });
        })
        .then(nextBatch);
    }
    return nextBatch().catch(function (e) { errors.push(friendlyError(e)); }).then(function () {
      uploading = false;
      setTimeout(function () { setProgress(0, 0); }, 900);
      if (errors.length) notice("err", "Algunas fotos no se pudieron subir", errors.slice(0, 3).join(" · "));
      else toast(total + (total === 1 ? " foto añadida" : " fotos añadidas"));
    });
  }

  /* ---------------- ajustes ---------------- */
  function renderFields() {
    var list = $("#fields"); list.innerHTML = "";
    state.fields.forEach(function (f, i) {
      var row = document.createElement("div"); row.className = "kv";
      row.innerHTML = '<input class="inp" placeholder="Campo" aria-label="Nombre del campo ' + (i + 1) + '" value="' + esc(f[0]) + '">' +
        '<input class="inp" placeholder="Valor" aria-label="Valor del campo ' + (i + 1) + '" value="' + esc(f[1]) + '">' +
        '<button class="btn sm icon ghost" type="button" aria-label="Quitar campo"><svg class="i sm"><use href="#i-x"/></svg></button>';
      var ins = row.querySelectorAll("input");
      ins[0].addEventListener("input", function () { f[0] = ins[0].value; changed(); });
      ins[1].addEventListener("input", function () { f[1] = ins[1].value; changed(); });
      if (/^fecha$/i.test(f[0]) && !f[1]) { f[1] = today(); ins[1].value = f[1]; }
      row.querySelector("button").onclick = function () { state.fields.splice(i, 1); renderFields(); changed(); };
      list.appendChild(row);
    });
  }
  function renderLayouts() {
    var box = $("#layouts"); box.innerHTML = "";
    LAYOUTS.forEach(function (l) {
      var c = +l.split("x")[0], r = +l.split("x")[1];
      var b = document.createElement("button"); b.type = "button"; b.setAttribute("aria-pressed", String(state.layout === l));
      var mini = '<span class="mini" style="grid-template-columns:repeat(' + c + ',1fr);grid-template-rows:repeat(' + r + ',1fr)">' + new Array(c * r + 1).join("<i></i>") + "</span>";
      b.innerHTML = mini + "<span>" + l.replace("x", "×") + "</span>";
      b.onclick = function () { state.layout = l; renderLayouts(); changed(); };
      box.appendChild(b);
    });
  }
  function renderColors() {
    var box = $("#colors"); box.innerHTML = "";
    PRESETS.forEach(function (c) {
      var b = document.createElement("button"); b.type = "button"; b.className = "swatch"; b.style.background = c;
      b.setAttribute("aria-label", "Color " + c); b.setAttribute("aria-pressed", String(state.theme.toLowerCase() === c));
      b.onclick = function () { state.theme = c; renderColors(); changed(); };
      box.appendChild(b);
    });
    var pick = document.createElement("input"); pick.type = "color"; pick.className = "colorpick"; pick.value = state.theme; pick.setAttribute("aria-label", "Color personalizado");
    pick.addEventListener("input", function () { state.theme = pick.value; $$(".swatch").forEach(function (s) { s.setAttribute("aria-pressed", String(s.style.background === pick.value)); }); changed(); });
    box.appendChild(pick);
  }
  function renderLogo() {
    var prev = $("#logoPrev");
    prev.innerHTML = state.logo ? '<img alt="Logo" src="' + PixAgent.thumbUrl(state.logo, 200) + '">' : '<svg class="i"><use href="#i-image"/></svg>';
    $("#btnLogoDel").hidden = !state.logo;
    $("#btnLogo").textContent = state.logo ? "Cambiar logo" : "Elegir logo";
  }
  function seg(id, key) {
    var el = $(id);
    $$("button", el).forEach(function (b) {
      b.setAttribute("aria-pressed", String(state[key] === b.dataset.v));
      b.onclick = function () { state[key] = b.dataset.v; seg(id, key); changed(); };
    });
  }
  function renderSettings() {
    $("#title").value = state.title; $("#subtitle").value = state.subtitle; $("#numbering").checked = !!state.numbering;
    renderFields(); renderLayouts(); renderColors(); renderLogo();
    seg("#segPage", "page"); seg("#segOrient", "orientation"); seg("#segFit", "fit");
  }

  /* ---------------- vista previa (geometría idéntica a panel.py) ---------------- */
  var measureCtx = document.createElement("canvas").getContext("2d");
  function textW(s, fs, bold) { measureCtx.font = (bold ? "700 " : "") + fs + "px " + PDF_FONT; return measureCtx.measureText(s).width; }
  function fitCaption(label, maxW) {
    var fs = 8.5;
    while (textW(label, fs) > maxW && fs > 6) fs -= 0.5;
    if (textW(label, fs) > maxW) {
      while (label && textW(label + "…", fs) > maxW) label = label.slice(0, -1);
      label += "…";
    }
    return { text: label, fs: fs };
  }
  var previewTimer;
  function schedulePreview() { clearTimeout(previewTimer); previewTimer = setTimeout(renderPreview, 60); }
  function renderPreview() {
    var host = $("#pages"); host.innerHTML = "";
    var photos = state.photos;
    if (!photos.length) {
      host.innerHTML = '<div class="nothing"><div class="mark"><svg class="i" style="width:26px;height:26px"><use href="#i-image"/></svg></div><h3>La vista previa aparecerá aquí</h3><p>Añade fotos y verás las páginas tal como saldrán en el PDF: cabecera, rejilla, pies de foto y paginación.</p></div>';
      return;
    }
    var dims = PAGES[state.page] || PAGES.A4;
    var PW = dims[0], PH = dims[1];
    if (state.orientation === "landscape") { PW = dims[1]; PH = dims[0]; }
    var cols = +state.layout.split("x")[0], rows = +state.layout.split("x")[1];
    var fields = activeFields();
    var m = 1.2 * CM, headerH = 2.0 * CM + (fields.length ? 0.45 * CM * Math.ceil(fields.length / 2) : 0);
    var footerH = 0.8 * CM, gap = 0.35 * CM, capH = 0.75 * CM;
    var perPage = cols * rows, nPages = Math.ceil(photos.length / perPage);
    var top = headerH + 0.2 * CM, bottom = PH - (footerH + m * 0.5);
    var cellW = (PW - 2 * m - (cols - 1) * gap) / cols;
    var cellH = (bottom - top - (rows - 1) * gap) / rows;
    var imgH = cellH - capH;
    var avail = Math.max(240, host.clientWidth || 600);
    var scale = Math.min(avail / PW, 1.4);
    var thumbW = cellW * 2 > 900 ? 1200 : cellW * 2 > 500 ? 800 : 480;
    var title = state.title || "Panel fotográfico";
    var logoShift = state.logo ? 2.6 * CM : 0;
    var footer = "Generado con PixAgent · " + todayES();

    for (var pg = 0; pg < nPages; pg++) {
      var h = '<div class="band" style="height:' + (1.25 * CM) + 'px;background:' + esc(state.theme) + '"></div>';
      h += '<div class="title" style="left:' + m + "px;top:" + (0.85 * CM - 14 * 0.8) + "px;max-width:" + (PW - 2 * m - logoShift - 120) + 'px;line-height:1">' + esc(title.slice(0, 80)) + "</div>";
      if (state.subtitle) h += '<div class="subtitle" style="right:' + (m + logoShift) + "px;top:" + (0.82 * CM - 9.5 * 0.8) + 'px;line-height:1;max-width:50%">' + esc(state.subtitle.slice(0, 90)) + "</div>";
      if (state.logo) h += '<img class="logo" alt="" src="' + PixAgent.thumbUrl(state.logo, 200) + '" style="left:' + (PW - m - 2.3 * CM) + "px;top:" + (0.15 * CM) + "px;width:" + (2.2 * CM) + "px;height:" + (1.0 * CM) + 'px">';
      var colw = (PW - 2 * m) / 2;
      fields.forEach(function (f, i) {
        var xx = m + (i % 2) * colw, yy = 1.75 * CM + Math.floor(i / 2) * 0.45 * CM;
        h += '<div class="fld" style="left:' + xx + "px;top:" + (yy - 8.5 * 0.8) + "px;width:" + (colw - 6) + 'px;line-height:1"><b>' + esc(f[0]) + ":</b> " + esc(f[1].slice(0, 70)) + "</div>";
      });
      var slice = photos.slice(pg * perPage, (pg + 1) * perPage);
      slice.forEach(function (p, k) {
        var idx = pg * perPage + k, r = Math.floor(k / cols), c = k % cols;
        var x0 = m + c * (cellW + gap), yTop = top + r * (cellH + gap);
        var label = (state.numbering ? "Foto " + (idx + 1) + ". " : "") + (p.caption || "");
        var fit = fitCaption(label, cellW - 0.3 * CM);
        h += '<div class="cell" style="left:' + x0 + "px;top:" + yTop + "px;width:" + cellW + "px;height:" + cellH + 'px">' +
          '<img alt="" loading="lazy" src="' + thumb(p, thumbW) + '" style="height:' + imgH + "px;object-fit:" + (state.fit === "contain" ? "contain" : "cover") + '">' +
          '<div class="capbox" style="height:' + capH + 'px"></div>' +
          '<div class="captxt" style="top:' + (imgH + capH / 2 + fit.fs / 3 - fit.fs * 0.8) + "px;font-size:" + fit.fs + 'px">' + esc(fit.text) + "</div>" +
          (state.numbering ? '<div class="badge" style="left:' + (0.15 * CM) + "px;top:" + (0.15 * CM) + "px;width:" + (0.6 * CM) + "px;height:" + (0.6 * CM) + "px;background:" + esc(state.theme) + '">' + (idx + 1) + "</div>" : "") +
          "</div>";
      });
      h += '<div class="foot" style="left:' + m + "px;top:" + (PH - 0.6 * CM - 8 * 0.8) + 'px;line-height:1">' + esc(footer) + "</div>";
      h += '<div class="foot r" style="right:' + m + "px;top:" + (PH - 0.6 * CM - 8 * 0.8) + 'px;line-height:1">Página ' + (pg + 1) + " de " + nPages + "</div>";

      var wrap = document.createElement("div"); wrap.className = "sheet-wrap";
      wrap.style.width = Math.round(PW * scale) + "px"; wrap.style.height = Math.round(PH * scale) + "px";
      var sheet = document.createElement("div"); sheet.className = "sheet"; sheet.setAttribute("aria-label", "Página " + (pg + 1));
      sheet.style.width = PW + "px"; sheet.style.height = PH + "px"; sheet.style.transform = "scale(" + scale + ")";
      sheet.innerHTML = h;
      wrap.appendChild(sheet); host.appendChild(wrap);
      var lab = document.createElement("div"); lab.className = "pagelabel";
      lab.textContent = state.page + (state.orientation === "landscape" ? " apaisado" : " vertical") + " · " + state.layout.replace("x", "×") + " · página " + (pg + 1) + " de " + nPages;
      host.appendChild(lab);
    }
  }

  /* ---------------- acciones: PDF, IA, PixPin, compartir ---------------- */
  function buildSpec() {
    var fields = {};
    activeFields().forEach(function (f) { fields[f[0]] = f[1]; });
    var d = new Date(), p = function (n) { return (n < 10 ? "0" : "") + n; };
    var stamp = d.getFullYear() + p(d.getMonth() + 1) + p(d.getDate()) + "_" + p(d.getHours()) + p(d.getMinutes());
    var spec = {
      output: "outputs/paneles/" + slug(state.title) + "_" + stamp + ".pdf",
      title: state.title || "Panel fotográfico", subtitle: state.subtitle || "", fields: fields,
      layout: state.layout, page: state.page, orientation: state.orientation,
      photos: state.photos.map(function (ph) { return { path: ph.path, caption: ph.caption || "" }; }),
      numbering: !!state.numbering, theme_color: state.theme, fit: state.fit
    };
    if (state.logo) spec.logo = state.logo;
    return spec;
  }
  var busy = false;
  function setBusy(on) {
    busy = on;
    ["#btnPDF", "#btnPDFm", "#btnAI", "#btnAIm"].forEach(function (id) { var b = $(id); if (b) b.disabled = on; });
  }
  function generatePDF() {
    if (busy) return;
    if (!state.photos.length) { notice("err", "Añade al menos una foto", "El panel se maqueta a partir de las fotos subidas."); setTab("photos"); return; }
    setBusy(true);
    var n = notice("busy", "Generando el PDF…", state.photos.length + " fotos · " + state.layout.replace("x", "×") + " · " + state.page);
    PixAgent.photoPanel(buildSpec()).then(function (r) {
      n.remove();
      lastResult = r;
      var url = PixAgent.fileUrl(r.path);
      var acts = [mkBtn("Abrir PDF", "i-open", "primary", null, url),
        mkBtn("Fijar en PixPin", "i-pin", "", function () { pin(r.path, this); })];
      if (navigator.share) acts.push(mkBtn("Compartir", "i-share", "", function () { share(r.path, url); }));
      notice("ok", "PDF listo · " + r.pages + (r.pages === 1 ? " página" : " páginas"), r.path, acts);
      toast("Panel generado");
    }).catch(function (e) {
      n.remove(); notice("err", "No se pudo generar el PDF", friendlyError(e));
    }).then(function () { setBusy(false); });
  }
  function pin(path, btn) {
    if (btn) btn.disabled = true;
    PixAgent.pin([path]).then(function () { toast("Fijado en PixPin"); }).catch(function (e) { notice("err", "PixPin no respondió", friendlyError(e)); }).then(function () { if (btn) btn.disabled = false; });
  }
  function share(path, url) {
    var abs = location.origin + url, name = path.split("/").pop();
    var data = { title: state.title || "Panel fotográfico", text: "Panel fotográfico", url: abs };
    fetch(url).then(function (r) { return r.blob(); }).then(function (b) {
      var f = new File([b], name, { type: "application/pdf" });
      if (navigator.canShare && navigator.canShare({ files: [f] })) return navigator.share({ files: [f], title: data.title });
      return navigator.share(data);
    }).catch(function () { return navigator.share(data).catch(function () { }); });
  }
  function aiCaptions() {
    if (busy) return;
    if (!state.photos.length) { notice("err", "No hay fotos que describir", "Sube las fotos primero; la IA las verá en el orden del panel."); return; }
    setBusy(true);
    var photos = state.photos.slice();
    var ctx = [];
    if (state.title) ctx.push("Título: " + state.title);
    if (state.subtitle) ctx.push("Subtítulo: " + state.subtitle);
    activeFields().forEach(function (f) { if (f[1]) ctx.push(f[0] + ": " + f[1]); });
    var n = notice("busy", "Redactando pies de foto…", "Una sola llamada al modelo rápido con " + photos.length + (photos.length === 1 ? " imagen" : " imágenes") + ".");
    var chunks = []; for (var i = 0; i < photos.length; i += 20) chunks.push(photos.slice(i, i + 20));
    var done = Promise.resolve();
    chunks.forEach(function (chunk, ci) {
      done = done.then(function () {
        var prompt = "Estas " + chunk.length + " imágenes son fotos de obra o inspección técnica, en el orden del panel" +
          (chunks.length > 1 ? " (bloque " + (ci + 1) + " de " + chunks.length + ")" : "") + ".\n" +
          (ctx.length ? "Contexto del documento: " + ctx.join(" · ") + ".\n" : "") +
          "Escribe un pie de foto para cada imagen: breve (máximo 12 palabras), técnico y descriptivo, en español, sin numerar ni empezar por «Foto». Devuelve exactamente " + chunk.length + " pies en el mismo orden.";
        return PixAgent.ai(prompt, {
          images: chunk.map(function (p) { return p.path; }),
          system: "Eres un asistente de documentación de obra. Describes lo que se ve con vocabulario técnico de construcción (elementos, materiales, estado, actividad).",
          json: '{"captions": ["pie 1", "pie 2", ...]} con exactamente ' + chunk.length + " elementos",
          maxTokens: Math.min(4000, 60 * chunk.length + 120), quality: "fast"
        }).then(function (data) {
          var caps = data && (data.captions || data.pies || data.result);
          if (!Array.isArray(caps)) throw new Error("La IA no devolvió la lista de pies de foto esperada.");
          chunk.forEach(function (p, i) { if (caps[i]) p.caption = String(caps[i]).trim().replace(/^foto\s*\d+[.:\-\s]*/i, ""); });
        });
      });
    });
    done.then(function () {
      n.remove(); renderPhotos(); changed(); toast("Pies de foto redactados · revísalos y edita lo que quieras");
    }).catch(function (e) {
      n.remove(); notice("err", "La IA no está disponible", friendlyError(e) + " Puedes escribir los pies de foto a mano.");
    }).then(function () { setBusy(false); });
  }

  /* ---------------- pestañas (móvil) ---------------- */
  function setTab(t) {
    $("#app").dataset.tab = t;
    $$(".tabs [role=tab]").forEach(function (b) { b.setAttribute("aria-selected", String(b.dataset.tab === t)); });
    $("#panePhotos").hidden = t !== "photos";
    $("#paneSettings").hidden = t !== "settings";
    $("#paneLayout").hidden = t !== "settings";
    if (t === "preview") renderPreview();
  }

  /* ---------------- arranque ---------------- */
  function bind() {
    $("#btnPick").onclick = function () { $("#filePick").click(); };
    $("#btnShoot").onclick = function () { $("#fileShoot").click(); };
    $("#filePick").addEventListener("change", function () { addFiles(this.files); this.value = ""; });
    $("#fileShoot").addEventListener("change", function () { addFiles(this.files); this.value = ""; });
    var drop = $("#drop"), work = $(".work");
    ["dragenter", "dragover"].forEach(function (ev) { work.addEventListener(ev, function (e) { if (dragFrom >= 0) return; if (e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types, "Files") >= 0) { e.preventDefault(); drop.classList.add("over"); } }); });
    work.addEventListener("dragleave", function (e) { if (!work.contains(e.relatedTarget)) drop.classList.remove("over"); });
    work.addEventListener("drop", function (e) { if (dragFrom >= 0) return; if (e.dataTransfer && e.dataTransfer.files && e.dataTransfer.files.length) { e.preventDefault(); drop.classList.remove("over"); addFiles(e.dataTransfer.files); } });
    document.addEventListener("paste", function (e) { var fs = e.clipboardData && e.clipboardData.files; if (fs && fs.length) addFiles(fs); });

    $("#btnClearPhotos").onclick = function () {
      if (!state.photos.length) return;
      var el = notice("err", "¿Quitar las " + state.photos.length + " fotos del panel?", "Los archivos subidos siguen en el workspace.",
        [mkBtn("Sí, quitar todas", "i-trash", "", function () { state.photos = []; el.remove(); changed(true); })]);
    };
    $("#title").addEventListener("input", function () { state.title = this.value; changed(); });
    $("#subtitle").addEventListener("input", function () { state.subtitle = this.value; changed(); });
    $("#numbering").addEventListener("change", function () { state.numbering = this.checked; changed(); });
    $("#btnAddField").onclick = function () { state.fields.push(["", ""]); renderFields(); var ins = $$("#fields input"); if (ins.length) ins[ins.length - 2].focus(); changed(); };
    $("#btnLogo").onclick = function () { $("#fileLogo").click(); };
    $("#fileLogo").addEventListener("change", function () {
      var f = this.files && this.files[0]; this.value = "";
      if (!f) return;
      PixAgent.upload([f]).then(function (paths) { state.logo = paths[0]; renderLogo(); changed(); toast("Logo añadido"); })
        .catch(function (e) { notice("err", "No se pudo subir el logo", friendlyError(e)); });
    });
    $("#btnLogoDel").onclick = function () { state.logo = null; renderLogo(); changed(); };
    $("#btnReset").onclick = function () {
      var el = notice("err", "¿Restablecer el borrador?", "Se vacían ajustes y fotos del panel (los archivos siguen en el workspace).",
        [mkBtn("Restablecer", "i-reset", "", function () { state = defaults(); el.remove(); renderSettings(); changed(true); })]);
    };
    ["#btnPDF", "#btnPDFm"].forEach(function (id) { $(id).onclick = generatePDF; });
    ["#btnAI", "#btnAIm"].forEach(function (id) { $(id).onclick = aiCaptions; });
    $$(".tabs [role=tab]").forEach(function (b) { b.onclick = function () { setTab(b.dataset.tab); }; });
    var rt; window.addEventListener("resize", function () { clearTimeout(rt); rt = setTimeout(renderPreview, 120); });
    document.addEventListener("keydown", function (e) {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "s") { e.preventDefault(); generatePDF(); }
    });
  }

  if (!window.PixAgent) {
    window.PixAgent = { embedded: false, fileUrl: function (p) { return "/files/" + p; }, thumbUrl: function (p) { return "/files/" + p; },
      upload: function () { return Promise.reject(new Error("El SDK de PixAgent no se ha cargado. Abre la app desde PixAgent.")); },
      photoPanel: function () { return Promise.reject(new Error("El SDK de PixAgent no se ha cargado.")); },
      ai: function () { return Promise.reject(new Error("El SDK de PixAgent no se ha cargado.")); },
      pin: function () { return Promise.reject(new Error("El SDK de PixAgent no se ha cargado.")); }, toast: function () { } };
  }
  loadDraft();
  bind();
  renderSettings();
  renderPhotos();
  setTab("photos");
  renderPreview();
  $("#saveState").textContent = state.photos.length ? "Borrador recuperado" : "Borrador local";
})();
