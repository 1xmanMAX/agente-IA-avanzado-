/* PixAgent — creador de informes (/reports).
   Sin frameworks; JS ES2019 compatible con Safari iOS 15 (sin lookbehind ni encadenamiento opcional).
   Rutas (hash): #/ · #/plantillas · #/nuevo[/<plantilla>] · #/informe/<id> · #/plantilla/nueva · #/plantilla/<id>[/copiar] */
(() => {
  "use strict";
  const $ = (s, root) => (root || document).querySelector(s);
  const $$ = (s, root) => Array.from((root || document).querySelectorAll(s));
  const isTouch = matchMedia("(pointer: coarse)").matches;
  const isMobile = () => matchMedia("(max-width: 820px)").matches;
  const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);

  const state = {
    ws: null, retry: 0, lastSeq: 0, everConnected: false, status: null, maxPx: 3200,
    reports: null, templates: null,
    rid: null, project: null, unit: null, sel: [], saveTimer: null, reloadTimer: null, dirty: false,
    progress: { total: 0, done: 0 }, running: false, pendingSection: null,
    wiz: { tpl: null, model: "claude-opus-5-5" },
    tpl: null, tplMode: "new", outline: null,
  };

  const MODELS = { "claude-opus-5-5": "Máxima", "claude-sonnet-5-5": "Económica" };
  const MODEL_HINT = {
    "claude-opus-5-5": "Redacción más cuidada y coherente; recomendada para informes que se entregan.",
    "claude-sonnet-5-5": "Más rápida y unas 2–3 veces más barata; buena para borradores y revisiones.",
  };
  const KINDS = {
    ai: { label: "Redacta la IA", short: "IA", icon: "sparkle", color: "var(--accent)", soft: "var(--accent-soft)",
      desc: "La IA escribe esta sección a partir de tus notas, los datos del informe y, si lo marcas, las fotos." },
    per_group: { label: "Un apartado por zona", short: "Por zona", icon: "folder", color: "var(--ok)", soft: "var(--ok-soft)",
      desc: "Crea un apartado por cada zona o grupo de fotos (fachada, cocina, eje 3…), redactado solo con las fotos de esa zona." },
    auto_outline: { label: "Índice automático", short: "Índice IA", icon: "book", color: "var(--warn)", soft: "var(--warn-soft)",
      desc: "Para informes extensos: la IA propone capítulos y apartados según la extensión objetivo y luego redacta cada uno por separado." },
    fields_table: { label: "Tabla de datos", short: "Tabla", icon: "table", color: "var(--text-2)", soft: "var(--surface-3)",
      desc: "Tabla con los campos del informe (obra, cliente, fecha…). No usa IA." },
    photo_grid: { label: "Panel fotográfico", short: "Panel", icon: "grid", color: "var(--text-2)", soft: "var(--surface-3)",
      desc: "Rejilla con todas las fotos numeradas y sus pies de foto. No usa IA." },
    static: { label: "Texto fijo", short: "Fijo", icon: "text", color: "var(--text-2)", soft: "var(--surface-3)",
      desc: "Texto idéntico en todos los informes (firma, aviso legal…). Admite {{campo}}. No usa IA." },
  };
  const FIELD_TYPES = { text: "Texto", textarea: "Texto largo", date: "Fecha", number: "Número" };

  // ---------------------------------------------------------------- utilidades
  function localGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function localSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = (rel) => rel.split("/").map(encodeURIComponent).join("/");
  const fileUrl = (rel) => "/files/" + enc(rel);
  const ico = (name, cls) => `<svg class="icon${cls ? " " + cls : ""}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
  const thumbUrl = (rel, cssW, page) => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    return `/thumb/${enc(rel)}?w=${Math.round(cssW * dpr)}${page != null ? "&page=" + page : ""}`;
  };
  const baseName = (p) => p.split("/").pop();
  const num = (n) => Number(n || 0).toLocaleString("es-ES");
  const usd = (n) => Number(n || 0).toLocaleString("es-ES", { style: "currency", currency: "USD", maximumFractionDigits: 2 });
  const fmtDate = (ts) => {
    if (!ts) return "";
    const d = new Date(ts * 1000), now = new Date();
    const sameDay = d.toDateString() === now.toDateString();
    return sameDay ? "hoy, " + d.toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" })
      : d.toLocaleDateString("es-ES", { day: "numeric", month: "short", year: d.getFullYear() === now.getFullYear() ? undefined : "numeric" });
  };
  const slug = (s) => String(s || "").normalize("NFKD").replace(/[̀-ͯ]/g, "").toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 40) || "x";
  const words = (t) => (String(t || "").trim().match(/\S+/g) || []).length;
  const go = (hash) => { if (location.hash === hash) route(); else location.hash = hash; };

  function toast(msg, ms, type) {
    const stack = $("#toasts");
    const t = document.createElement("div");
    t.className = "toast" + (type ? " toast-" + type : "");
    t.innerHTML = (type === "ok" ? ico("check") : type === "err" || type === "warn" ? ico("alert") : "") + `<span>${esc(msg)}</span>`;
    stack.appendChild(t);
    while (stack.children.length > 3) stack.removeChild(stack.firstChild);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 200); }, ms || 2600);
  }
  async function api(url, body, method) {
    const opts = body === undefined && !method ? {} : { method: method || "POST", headers: { "Content-Type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) };
    const r = await fetch(url, opts);
    let j = null;
    try { j = await r.json(); } catch (e) { j = {}; }
    if (!r.ok && j && j.error === undefined) j.error = j.detail || ("Error " + r.status);
    if (j && typeof j === "object" && !Array.isArray(j) && j.ok === undefined) j.ok = r.ok;
    return j;
  }
  const apiPut = (url, body) => api(url, body, "PUT");
  const apiDel = (url) => api(url, undefined, "DELETE");

  // Markdown mínimo y seguro (con tablas; sin lookbehind)
  function md(src) {
    const blocks = [];
    let s = esc(src || "").replace(/```(\w*)\n([\s\S]*?)```/g, (_, l, c) => { blocks.push("<pre><code>" + c + "</code></pre>"); return "\u0000" + (blocks.length - 1) + "\u0000"; });
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(^|[\s(])\*(\S(?:.*?\S)?)\*(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
      .replace(/(^|[\s(])_(\S(?:.*?\S)?)_(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    const out = []; let list = null; let listTag = "ul"; let table = null;
    const flushList = () => { if (list) { out.push("<" + listTag + ">" + list.join("") + "</" + listTag + ">"); list = null; } };
    const cells = (line) => line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
    const flushTable = () => {
      if (!table) return;
      const rows = table.filter((r) => !/^\s*\|?\s*:?-{2,}/.test(r)).map(cells);
      if (rows.length) {
        out.push("<table><thead><tr>" + rows[0].map((c) => "<th>" + c + "</th>").join("") + "</tr></thead><tbody>" +
          rows.slice(1).map((r) => "<tr>" + r.map((c) => "<td>" + c + "</td>").join("") + "</tr>").join("") + "</tbody></table>");
      }
      table = null;
    };
    s.split("\n").forEach((line) => {
      if (/^\s*\|/.test(line)) { flushList(); (table = table || []).push(line); return; }
      flushTable();
      const h = line.match(/^(#{1,4})\s+(.*)/);
      const li = line.match(/^\s*([-*]|\d+[.)])\s+(.*)/);
      if (li) { const tag = /\d/.test(li[1]) ? "ol" : "ul"; if (list && tag !== listTag) flushList(); listTag = tag; (list = list || []).push("<li>" + li[2] + "</li>"); return; }
      flushList();
      if (h) { const lvl = Math.min(5, h[1].length + 2); out.push(`<h${lvl}>${h[2]}</h${lvl}>`); }
      else if (/^\s*&gt;\s?/.test(line)) out.push("<blockquote>" + line.replace(/^\s*&gt;\s?/, "") + "</blockquote>");
      else if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) out.push("<hr>");
      else if (line.trim()) out.push("<p>" + line + "</p>");
    });
    flushList(); flushTable();
    return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[i]);
  }

  // ---------------------------------------------------------------- capas y botón «atrás» (Android, gesto atrás)
  // Modales, menú contextual y el editor de sección añaden una entrada al historial: «atrás» cierra la capa
  // superior en vez de abandonar la pantalla (las pantallas ya se enrutan por hash).
  const layers = [];
  function pushLayer(name, close) {
    layers.push({ name: name, close: close });
    try { history.pushState({ layer: layers.length, hash: location.hash }, "", location.hash || "#/"); } catch (e) { /* sin historial */ }
  }
  function dropLayer(name) {
    const i = layers.map((l) => l.name).lastIndexOf(name);
    if (i < 0) return false;
    const wasTop = i === layers.length - 1;
    layers.splice(i, 1);
    if (wasTop && history.state && history.state.layer === layers.length + 1) { try { history.back(); } catch (e) { /* nada */ } }
    return true;
  }
  window.addEventListener("popstate", (e) => {
    const depth = (e.state && e.state.layer) || 0;
    while (layers.length > depth) { const l = layers.pop(); try { l.close(); } catch (err) { /* ya cerrada */ } }
  });
  try { history.replaceState({ layer: 0, hash: location.hash }, ""); } catch (e) { /* nada */ }

  // Modales accesibles: foco atrapado y devuelto al cerrar; Esc y «atrás» cierran
  const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  function openModal(sel, onClose) {
    const m = typeof sel === "string" ? $(sel) : sel;
    if (!m.classList.contains("hidden")) return;
    m._prevFocus = document.activeElement; m._onClose = onClose || null;
    m.classList.remove("hidden");
    pushLayer("modal:" + m.id, () => finishModal(m, true));
    const f = $$(FOCUSABLE, m).filter((el) => el.offsetParent !== null);
    const first = m.querySelector("[autofocus]") || f.find((el) => el.tagName === "INPUT" || el.tagName === "TEXTAREA") || f[0];
    if (first && !isTouch) setTimeout(() => first.focus(), 30);
  }
  function finishModal(m, fromBack) {
    if (m.classList.contains("hidden")) return;
    m.classList.add("hidden");
    if (!fromBack) dropLayer("modal:" + m.id);
    const cb = m._onClose; m._onClose = null; if (cb) cb();
    const p = m._prevFocus; m._prevFocus = null;
    if (p && p.focus && document.contains(p) && !isTouch) setTimeout(() => p.focus(), 0);
  }
  const closeModal = (sel) => { const m = typeof sel === "string" ? $(sel) : sel; if (m) finishModal(m, false); };
  document.addEventListener("keydown", (e) => { // trampa de foco con Tab
    if (e.key !== "Tab") return;
    const m = $$(".modal:not(.hidden)").pop(); if (!m) return;
    const f = $$(FOCUSABLE, m).filter((el) => el.offsetParent !== null); if (!f.length) return;
    if (e.shiftKey && (document.activeElement === f[0] || !m.contains(document.activeElement))) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });
  function askConfirm(title, text, label, soft) {
    return new Promise((resolve) => {
      const m = $("#confirm");
      $("#confirmTitle").textContent = title; $("#confirmText").textContent = text || "";
      const yes = $("#confirmYes");
      yes.textContent = label || "Borrar";
      yes.className = "btn " + (soft ? "btn-primary" : "btn-danger");
      $(".modal-icon", m).className = "modal-icon" + (soft ? "" : " danger");
      let result = false;
      openModal(m, () => resolve(result));
      const close = (v) => { result = v; closeModal(m); };
      yes.onclick = () => close(true); $("#confirmNo").onclick = () => close(false);
      m.onclick = (e) => { if (e.target === m) close(false); };
    });
  }

  // ---------------------------------------------------------------- menú contextual (clic derecho · pulsación larga · botón ⋯)
  function showMenu(items, x, y) {
    hideMenu();
    const menu = document.createElement("div"); menu.className = "ctx-menu"; menu.id = "ctxMenu"; menu.setAttribute("role", "menu");
    menu.innerHTML = items.map((it, i) => it === "-" ? "<hr>" : `<button type="button" role="menuitem" data-i="${i}" class="${it.danger ? "danger" : ""}" ${it.disabled ? "disabled" : ""}>${it.icon ? ico(it.icon, "icon-sm") : ""}<span>${esc(it.label)}</span></button>`).join("");
    if (isMobile()) menu.classList.add("sheet");
    document.body.appendChild(menu);
    if (!isMobile()) {
      const r = menu.getBoundingClientRect();
      menu.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px";
      menu.style.top = Math.max(8, Math.min(y, innerHeight - r.height - 8)) + "px";
    }
    menu.addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (!b) return; const it = items[+b.dataset.i]; hideMenu(); if (it && it.onClick) it.onClick(); });
    menu.addEventListener("keydown", (e) => {
      const bs = $$("button:not([disabled])", menu), i = bs.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); (bs[i + 1] || bs[0]).focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); (bs[i - 1] || bs[bs.length - 1]).focus(); }
    });
    menu._prevFocus = document.activeElement;
    pushLayer("menu", () => hideMenu(true));
    setTimeout(() => { const b = menu.querySelector("button:not([disabled])"); if (b && !isTouch) b.focus(); }, 20);
    if (navigator.vibrate && isTouch) navigator.vibrate(12);
  }
  function hideMenu(fromBack) {
    const m = $("#ctxMenu"); if (!m) return;
    m.remove(); if (!fromBack) dropLayer("menu");
    const p = m._prevFocus; if (p && p.focus && document.contains(p) && !isTouch) p.focus();
  }
  document.addEventListener("pointerdown", (e) => { if ($("#ctxMenu") && !e.target.closest("#ctxMenu")) hideMenu(); }, true);
  window.addEventListener("resize", () => hideMenu());
  function contextFor(target) {
    const ph = target.closest("#photoGrid .ph");
    if (ph) {
      const i = +ph.dataset.idx, photos = state.project ? state.project.photos : [], sel = state.sel.indexOf(i) >= 0;
      const move = (d) => { const j = i + d; if (j < 0 || j >= photos.length) return; const x = photos.splice(i, 1)[0]; photos.splice(j, 0, x); state.sel = []; renderPhotos(); savePhotos(); };
      return [
        { label: sel ? "Quitar de la selección" : "Seleccionar", icon: "check", onClick: () => { const at = state.sel.indexOf(i); if (at >= 0) state.sel.splice(at, 1); else state.sel.push(i); renderPhotos(); } },
        { label: "Ver en grande", icon: "eye", onClick: () => window.open(fileUrl(photos[i].path), "_blank", "noopener") },
        "-",
        { label: "Mover antes", icon: "up", disabled: i === 0, onClick: () => move(-1) },
        { label: "Mover después", icon: "down", disabled: i >= photos.length - 1, onClick: () => move(1) },
        "-",
        { label: "Quitar del informe", icon: "trash", danger: true, onClick: async () => { if (!await askConfirm("¿Quitar esta foto del informe?", "El archivo se conserva en el workspace; solo se quita de este informe.", "Quitar")) return; photos.splice(i, 1); state.sel = []; renderPhotos(); savePhotos(); } },
      ];
    }
    const rc = target.closest("[data-open-report]");
    if (rc) {
      const r = (state.reports || []).find((x) => x.id === rc.dataset.openReport); if (!r) return null;
      const items = [{ label: "Abrir informe", icon: "edit", onClick: () => go("#/informe/" + encodeURIComponent(r.id)) }];
      if (r.pdf) items.push({ label: "Abrir PDF", icon: "pdf", onClick: () => window.open(fileUrl(r.pdf), "_blank", "noopener") });
      items.push("-", { label: "Borrar informe", icon: "trash", danger: true, onClick: async () => {
        if (await askConfirm("¿Borrar este informe?", "«" + r.title + "» y sus secciones redactadas se eliminarán de forma permanente.")) { await apiDel("/api/reports/" + encodeURIComponent(r.id)); toast("Informe borrado", 2000, "ok"); loadReports(); } } });
      return items;
    }
    const tc = target.closest(".tcard[data-pick-tpl], .tcard:not(.new)");
    if (tc && !target.closest("[data-pick-tpl]")) {
      const btn = tc.querySelector("[data-use-tpl], [data-dup-tpl], [data-edit-tpl]"); if (!btn) return null;
      const id = btn.dataset.useTpl || btn.dataset.dupTpl || btn.dataset.editTpl, t = tplById(id); if (!t) return null;
      const items = [{ label: "Usar para un informe nuevo", icon: "plus", onClick: () => go("#/nuevo/" + encodeURIComponent(id)) }];
      if (t.builtin) items.push({ label: "Duplicar y personalizar", icon: "copy", onClick: () => go("#/plantilla/" + encodeURIComponent(id) + "/copiar") });
      else items.push({ label: "Editar plantilla", icon: "edit", onClick: () => go("#/plantilla/" + encodeURIComponent(id)) }, "-",
        { label: "Borrar plantilla", icon: "trash", danger: true, onClick: async () => { if (await askConfirm("¿Borrar esta plantilla?", "«" + t.name + "» se eliminará. Los informes ya creados no se ven afectados.")) { await apiDel("/api/report-templates/" + encodeURIComponent(id)); toast("Plantilla borrada", 2000, "ok"); loadTemplates(true); } } });
      return items;
    }
    return null;
  }
  let lpTimer = null, lpStart = null, lpFired = 0;
  document.addEventListener("contextmenu", (e) => {
    if (Date.now() - lpFired < 1200) { e.preventDefault(); return; }
    if (e.target.closest("input, textarea")) return;
    const items = contextFor(e.target); if (!items) return;
    e.preventDefault(); showMenu(items, e.clientX, e.clientY);
  });
  document.addEventListener("pointerdown", (e) => { // pulsación larga en táctil/lápiz, sin pelear con el scroll
    if (e.pointerType === "mouse" || e.target.closest("input, textarea, button, label") || !contextFor(e.target)) return;
    clearTimeout(lpTimer); lpStart = { x: e.clientX, y: e.clientY, t: e.target };
    lpTimer = setTimeout(() => { lpFired = Date.now(); const items = contextFor(lpStart.t); if (items) showMenu(items, lpStart.x, lpStart.y); }, 480);
  }, { passive: true });
  document.addEventListener("pointermove", (e) => { if (lpStart && Math.hypot(e.clientX - lpStart.x, e.clientY - lpStart.y) > 10) { clearTimeout(lpTimer); lpStart = null; } }, { passive: true });
  ["pointerup", "pointercancel"].forEach((ev) => document.addEventListener(ev, () => { clearTimeout(lpTimer); lpStart = null; }, { passive: true }));
  document.addEventListener("click", (e) => { if (Date.now() - lpFired < 600 && !e.target.closest("#ctxMenu")) { e.stopPropagation(); e.preventDefault(); } }, true);

  // ---------------------------------------------------------------- tema (misma clave que la pantalla principal)
  function applyTheme(t) {
    if (t === "dark" || t === "light") document.documentElement.setAttribute("data-theme", t);
    else document.documentElement.removeAttribute("data-theme");
    localSet("theme", t);
    $$("#themeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.theme === t));
    $("#navTheme use").setAttribute("href", t === "dark" ? "#i-sun" : t === "light" ? "#i-moon" : "#i-monitor");
  }
  applyTheme(localGet("theme") || "system");

  // ---------------------------------------------------------------- conexión en tiempo real (con reanudación)
  function setConn(on) { $("#conn").classList.toggle("on", on); if (on) state.everConnected = true; }
  function connect() {
    if (state.ws && state.ws.readyState <= 1) return;
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    state.ws = ws;
    ws.onopen = () => { state.retry = 0; ws.send(JSON.stringify({ type: "hello", after: state.lastSeq })); setConn(true); };
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.seq) { if (ev.seq <= state.lastSeq) return; state.lastSeq = ev.seq; }
      handle(ev);
    };
    ws.onclose = (e) => {
      setConn(false);
      if (e.code === 4401) { location.reload(); return; }
      if (document.visibilityState === "visible") setTimeout(connect, Math.min(10000, 800 * Math.pow(1.6, state.retry++)));
    };
  }
  const send = (o) => { if (state.ws && state.ws.readyState === 1) { state.ws.send(JSON.stringify(o)); return true; } return false; };
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") { connect(); if (state.rid) scheduleReload(); } });
  window.addEventListener("online", connect);
  setInterval(() => { if (document.visibilityState === "visible") send({ type: "ping" }); }, 25000);

  function handle(ev) {
    if (ev.type !== "report_progress" && ev.type !== "report_done") return;
    if (!state.rid || ev.report !== state.rid) { if (ev.type === "report_done") loadReports(); return; }
    if (ev.type === "report_done") {
      state.running = false; state.progress.done = state.progress.total;
      renderGenState();
      setTimeout(() => { $("#genProgress").classList.add("hidden"); }, 1200);
      if (ev.cancelled) genMsg("warn", "Redacción cancelada. Las partes terminadas se conservan.");
      else if (state.outlineOnly && !ev.errors) genMsg("ok", "Índice propuesto. Revísalo o edítalo y después pulsa «Generar todo».");
      else if (ev.errors) genMsg("err", ev.errors + (ev.errors === 1 ? " parte terminó con error." : " partes terminaron con error.") + " Ábrelas en la estructura para ver el motivo y vuelve a intentarlo.");
      else genMsg("ok", "Redacción completada en " + Math.round(ev.seconds || 0) + " s. Revisa las secciones y construye el PDF.");
      scheduleReload(); loadReports();
      return;
    }
    // progreso por unidad
    state.running = true;
    if (ev.status === "started") { state.progress = { total: ev.total || 0, done: 0 }; $("#genLabel").textContent = ev.total ? "Redactando " + ev.total + (ev.total === 1 ? " parte…" : " partes en paralelo…") : "Preparando…"; renderGenState(); return; }
    if (ev.status === "outline") { $("#genLabel").textContent = ev.title || "Diseñando el índice…"; renderGenState(); return; }
    if (!ev.unit) return;
    const u = (state.project && state.project.units || []).find((x) => x.id === ev.unit);
    if (u) {
      u.status = ev.status; u.error = ev.error || null;
      if (ev.status === "done") u.edited = false;
    }
    if (ev.status === "running") $("#genLabel").textContent = "Redactando: " + (ev.title || ev.unit);
    if (ev.status === "done" || ev.status === "error") { state.progress.done++; }
    renderTree(); renderGenState();
    if (state.unit === ev.unit) {
      renderSectionHead(u);
      if (ev.status === "done") loadSectionText(ev.unit);
    }
    if (/__outline$/.test(ev.unit) && ev.status === "done") scheduleReload();
    if (ev.status === "done" || ev.status === "error") scheduleReload();
  }
  function scheduleReload() {
    clearTimeout(state.reloadTimer);
    state.reloadTimer = setTimeout(() => { if (state.rid) loadProject(state.rid, true); }, 500);
  }

  // ---------------------------------------------------------------- enrutado
  function route() {
    const h = location.hash.replace(/^#\/?/, "");
    const parts = h.split("/").map(decodeURIComponent);
    let screen = "home";
    if (parts[0] === "nuevo") { screen = "new"; openWizard(parts[1] || null); }
    else if (parts[0] === "informe" && parts[1]) { screen = "editor"; if (state.rid !== parts[1]) openEditor(parts[1]); }
    else if (parts[0] === "plantilla" && parts[1]) { screen = "template"; openTemplateEditor(parts[1] === "nueva" ? null : parts[1], parts[2] === "copiar"); }
    else { screen = "home"; loadHome(); }
    if (screen !== "editor") {
      state.rid = null; state.project = null; state.unit = null;
      const si = layers.map((l) => l.name).indexOf("section"); if (si >= 0) layers.splice(si, 1);
      $("#sectionPane").classList.add("hidden");
      if (state.zoom) { try { state.zoom.destroy(); } catch (e) { /* nada */ } state.zoom = null; }
    }
    document.body.dataset.screen = screen;
    $$(".sub-item").forEach((a) => a.classList.toggle("on", screen === "home" && ((a.dataset.sub === "templates") === (parts[0] === "plantillas"))));
    $$("#recentList a").forEach((a) => a.classList.toggle("on", a.getAttribute("href") === location.hash));
    if (screen === "home" && parts[0] === "plantillas") requestAnimationFrame(() => { $("#templatesHead").scrollIntoView({ block: "start", behavior: "smooth" }); });
    else if (screen !== "editor") { const sc = $("#screen-" + screen); if (sc) sc.scrollTop = 0; }
  }
  window.addEventListener("hashchange", route);

  // ---------------------------------------------------------------- inicio: informes y plantillas
  async function loadHome() {
    if (!state.reports) $("#reportsGrid").innerHTML = '<div class="loading"><span class="spinner spinner-lg"></span></div>';
    await Promise.all([loadReports(), loadTemplates()]);
  }
  async function loadReports() {
    let list;
    try { list = await api("/api/reports"); } catch (e) { list = state.reports || []; }
    if (!Array.isArray(list)) list = [];
    state.reports = list;
    renderReports(); renderRecent();
  }
  function renderReports() {
    const list = state.reports || [];
    const n = $("#reportsCount"); n.textContent = list.length; n.classList.toggle("hidden", !list.length);
    if (!list.length) {
      $("#reportsGrid").innerHTML = `<div class="empty"><span class="empty-icon">${ico("report")}</span><div class="empty-title">Todavía no hay informes</div>
        <div class="empty-text">Elige una plantilla, añade las fotos y tus notas, y la IA redactará el informe parte por parte.</div>
        <button type="button" class="btn btn-primary mt-3" data-go="#/nuevo">${ico("plus")}Crear el primero</button></div>`;
      return;
    }
    $("#reportsGrid").innerHTML = list.map((r) => `
      <div class="rcard" role="button" tabindex="0" data-open-report="${esc(r.id)}">
        <div class="rcard-top"><span class="rcard-ico">${ico(r.pdf ? "pdf" : "report")}</span>
          <div class="grow"><b>${esc(r.title)}</b><div class="tpl">${esc(r.template || "")}</div></div></div>
        <div class="rcard-foot">
          ${r.pdf ? `<span class="chip chip-ok">${ico("check")}PDF listo</span>` : `<span class="chip">${ico("edit")}Borrador</span>`}
          <span class="chip">${ico("image")}${r.photos} ${r.photos === 1 ? "foto" : "fotos"}</span>
          <span class="chip">${ico("clock")}${esc(fmtDate(r.updated))}</span>
          ${r.pdf ? `<a class="btn btn-sm btn-ghost" style="margin-left:auto" href="${fileUrl(r.pdf)}" target="_blank" rel="noopener" data-stop>${ico("external")}Abrir PDF</a>` : ""}
        </div>
        <button type="button" class="del" data-del-report="${esc(r.id)}" aria-label="Borrar informe">${ico("trash", "icon-sm")}</button>
      </div>`).join("");
  }
  function renderRecent() {
    const list = (state.reports || []).slice(0, 8);
    $("#recentList").innerHTML = list.map((r) => `<a href="#/informe/${esc(r.id)}" class="${"#/informe/" + r.id === location.hash ? "on" : ""}">${ico(r.pdf ? "pdf" : "report", "icon-sm")}<span class="nm">${esc(r.title)}</span></a>`).join("")
      || '<li class="none">Aún no hay informes.</li>';
  }
  async function loadTemplates(force) {
    if (state.templates && !force) { renderTemplates(); return state.templates; }
    let list;
    try { list = await api("/api/report-templates"); } catch (e) { list = state.templates || []; }
    state.templates = Array.isArray(list) ? list : [];
    renderTemplates();
    return state.templates;
  }
  const tplById = (id) => (state.templates || []).find((t) => t.id === id);
  function tplColorStyle(t) {
    const c = (t.style && t.style.theme_color) || "";
    return /^#[0-9a-f]{6}$/i.test(c) ? `style="--tpl-color:${c};--tpl-soft:color-mix(in srgb, ${c} 14%, var(--surface))"` : "";
  }
  function sectionChips(t) {
    return `<div class="seclist">${(t.sections || []).map((s) => { const k = KINDS[s.kind] || KINDS.ai; return `<span class="chip" title="${esc(k.label)}">${ico(k.icon)}${esc(s.title || k.label)}</span>`; }).join("")}</div>`;
  }
  function tplCard(t, mode, frequent) {
    const n = (t.sections || []).length, ai = (t.sections || []).filter((s) => ["ai", "per_group", "auto_outline"].indexOf(s.kind) >= 0).length;
    const foot = mode === "pick" ? "" : `<div class="tcard-foot">
        <button type="button" class="btn btn-sm btn-soft" data-use-tpl="${esc(t.id)}">${ico("plus")}Usar</button>
        ${t.builtin ? `<button type="button" class="btn btn-sm" data-dup-tpl="${esc(t.id)}">${ico("copy")}Duplicar</button>`
          : `<button type="button" class="btn btn-sm" data-edit-tpl="${esc(t.id)}">${ico("edit")}Editar</button><button type="button" class="btn btn-sm btn-ghost btn-icon" data-del-tpl="${esc(t.id)}" title="Borrar plantilla">${ico("trash")}</button>`}
      </div>`;
    return `<div class="tcard" ${tplColorStyle(t)} ${mode === "pick" ? `role="button" tabindex="0" data-pick-tpl="${esc(t.id)}"` : ""}>
      <div class="tcard-top"><span class="tpl-ico">${ico("layers")}</span><div class="grow"><b>${esc(t.name)}</b><div class="xs faint">${n} ${n === 1 ? "sección" : "secciones"} · ${ai} con IA</div></div>
        ${frequent ? `<span class="badge badge-accent" title="La has usado antes">${ico("star", "icon-sm")}Habitual</span>` : `<span class="badge ${t.builtin ? "" : "badge-accent"}">${t.builtin ? "Integrada" : "Mía"}</span>`}</div>
      <p>${esc(t.description || "Sin descripción.")}</p>
      ${sectionChips(t)}${foot}</div>`;
  }
  function renderTemplates() {
    const list = state.templates || [];
    $("#templatesGrid").innerHTML = list.filter((t) => !t.builtin).concat(list.filter((t) => t.builtin)).map((t) => tplCard(t)).join("") +
      `<div class="tcard new" role="button" tabindex="0" data-go="#/plantilla/nueva"><span class="tpl-ico">${ico("plus")}</span><b>Nueva plantilla</b><span class="small">Define tus propios campos y secciones</span></div>`;
  }

  // ---------------------------------------------------------------- asistente: nuevo informe
  async function openWizard(tid) {
    await loadTemplates();
    state.wiz.tpl = tid ? tplById(tid) || null : null;
    renderWizard();
  }
  const hasOutline = (t) => (t.sections || []).some((s) => s.kind === "auto_outline");
  function fieldInput(f, id, value) {
    const v = esc(value == null ? "" : value), ph = f.type === "number" ? "0" : "";
    const req = f.required ? " required" : "";
    if (f.type === "textarea") return `<textarea class="textarea" id="${id}" rows="3"${req}>${v}</textarea>`;
    if (f.type === "date") return `<input class="input" id="${id}" type="date" value="${v}"${req}>`;
    if (f.type === "number") return `<input class="input tabular" id="${id}" type="number" step="any" inputmode="decimal" value="${v}" placeholder="${ph}"${req}>`;
    return `<input class="input" id="${id}" value="${v}"${req}>`;
  }
  function fieldsForm(t, prefix, values, only) { // only: "req" | "opt" | undefined (todos)
    values = values || {};
    const list = (t.fields || []).map((f, i) => ({ f: f, i: i })).filter((x) => !only || (only === "req") === !!x.f.required);
    return list.map((x) => `<label class="field ${x.f.type === "textarea" ? "span2" : ""}"><span>${esc(x.f.label || x.f.key)}${x.f.required ? ' <span class="faint">*</span>' : ""}</span>${fieldInput(x.f, prefix + x.i, values[x.f.key])}</label>`).join("")
      || (only ? "" : '<div class="xs faint span2">Esta plantilla no pide datos adicionales.</div>');
  }
  // Contadores locales de uso (plantillas más usadas primero); fallan en silencio sin localStorage
  function counts(key) { try { return JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch (e) { return {}; } }
  function bump(key, id) { try { const c = counts(key); c[id] = (c[id] || 0) + 1; localStorage.setItem(key, JSON.stringify(c)); } catch (e) { /* modo privado */ } }
  function templatesByUse(list) {
    const used = counts("rt:count");
    return list.map((t, i) => ({ t: t, n: used[t.id] || 0, i: i })).sort((a, b) => b.n - a.n || (a.t.builtin ? 1 : 0) - (b.t.builtin ? 1 : 0) || a.i - b.i).map((x) => x.t);
  }
  function readFields(t, prefix) {
    const out = {};
    (t.fields || []).forEach((f, i) => { const el = $("#" + prefix + i); if (el) out[f.key] = f.type === "number" && el.value !== "" ? Number(el.value) : el.value; });
    return out;
  }
  function renderWizard() {
    const t = state.wiz.tpl;
    $$(".steps li").forEach((li) => { const n = +li.dataset.step; li.classList.toggle("on", n === (t ? 2 : 1)); li.classList.toggle("done", t && n === 1); });
    $("#wizStep1").classList.toggle("hidden", !!t); $("#wizStep2").classList.toggle("hidden", !t);
    if (!t) {
      const list = templatesByUse(state.templates || []), used = counts("rt:count");
      $("#wizTemplates").innerHTML = list.map((x) => tplCard(x, "pick", used[x.id] > 0)).join("") || `<div class="empty"><span class="empty-icon">${ico("layers")}</span><div class="empty-title">No hay plantillas</div></div>`;
      return;
    }
    $("#wizTplName").textContent = t.name;
    // visibles: título, campos obligatorios y notas; lo opcional, el modelo y la extensión en «Opciones avanzadas»
    $("#wizFields").innerHTML = fieldsForm(t, "wf", null, "req");
    const opt = fieldsForm(t, "wf", null, "opt");
    $("#wizFieldsOpt").innerHTML = opt; $("#wizFieldsOpt").classList.toggle("hidden", !opt);
    $("#wizPagesWrap").classList.toggle("hidden", !hasOutline(t));
    if (!$("#wizTitle").value) $("#wizTitle").value = "";
    $$("#wizModel button").forEach((b) => b.classList.toggle("on", b.dataset.model === state.wiz.model));
    $("#wizModelHint").textContent = MODEL_HINT[state.wiz.model] || "";
    renderWizAdvSum();
    if (!isTouch) setTimeout(() => $("#wizTitle").focus(), 50);
  }
  function renderWizAdvSum() {
    const t = state.wiz.tpl; if (!t) return;
    const nOpt = (t.fields || []).filter((f) => !f.required).length;
    const parts = ["Calidad " + (MODELS[state.wiz.model] || "").toLowerCase()];
    if (hasOutline(t)) parts.push(($("#wizPages").value || 20) + " págs.");
    if (nOpt) parts.push(nOpt + (nOpt === 1 ? " campo opcional" : " campos opcionales"));
    $("#wizAdvSum").textContent = parts.join(" · ");
  }
  $("#wizChange").onclick = () => { state.wiz.tpl = null; renderWizard(); };
  $("#wizBack").onclick = () => { state.wiz.tpl = null; renderWizard(); };
  $("#wizModel").addEventListener("click", (e) => { const b = e.target.closest("[data-model]"); if (b) { state.wiz.model = b.dataset.model; renderWizard(); } });
  $("#wizPages").addEventListener("input", (e) => { $("#wizPagesRange").value = Math.max(5, Math.min(200, +e.target.value || 5)); renderWizAdvSum(); });
  $("#wizPagesRange").addEventListener("input", (e) => { $("#wizPages").value = e.target.value; renderWizAdvSum(); });
  $("#wizStep2").addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = state.wiz.tpl; if (!t) return;
    const title = $("#wizTitle").value.trim(); if (!title) { $("#wizTitle").focus(); return; }
    const body = { template_id: t.id, title: title, fields: readFields(t, "wf"), notes: $("#wizNotes").value, photos: [], model: state.wiz.model };
    if (hasOutline(t)) body.target_pages = Math.max(5, Math.min(200, +$("#wizPages").value || 20));
    const btn = $("#wizCreate"); btn.disabled = true;
    const j = await api("/api/reports", body);
    btn.disabled = false;
    if (!j.ok) { toast(j.error || "No se pudo crear el informe", 5000, "err"); return; }
    bump("rt:count", t.id);
    $("#wizTitle").value = ""; $("#wizNotes").value = ""; state.wiz.tpl = null;
    state.reports = null;
    toast("Informe creado. Ahora añade las fotos.", 3200, "ok");
    document.body.dataset.etab = "photos";
    go("#/informe/" + encodeURIComponent(j.report.id));
  });

  // ---------------------------------------------------------------- editor del informe
  async function openEditor(rid) {
    state.rid = rid; state.project = null; state.unit = null; state.sel = []; state.running = false;
    state.progress = { total: 0, done: 0 };
    $("#sectionPane").classList.add("hidden"); $("#genProgress").classList.add("hidden"); $("#genMsg").classList.add("hidden");
    $("#edTitle").textContent = "Cargando…"; $("#edMeta").textContent = "";
    $("#tree").innerHTML = '<div class="loading"><span class="spinner spinner-lg"></span></div>';
    $("#photoGrid").innerHTML = ""; $("#previewBody").innerHTML = "";
    if (!isMobile()) document.body.dataset.etab = "photos";
    await loadProject(rid);
    if (state.project && !state.project.photos.length) document.body.dataset.etab = "photos";
    renderPreview();
  }
  async function loadProject(rid, quiet) {
    const p = await api("/api/reports/" + encodeURIComponent(rid));
    if (state.rid !== rid) return;
    if (!p || p.ok === false || !p.id) { toast("Informe no encontrado", 4000, "err"); go("#/"); return; }
    const first = !state.project;
    state.project = p;
    if (p.running) state.running = true;
    else if (!quiet) state.running = false;
    renderEditorHead(); renderTree(); renderGenState(); renderOutlineCard();
    if (first || !quiet) renderPhotos(); else updateGroupsDatalist();
    if (first) renderPreview();
    renderRecent();
  }
  function renderEditorHead() {
    const p = state.project;
    $("#edTitle").textContent = p.title;
    const tn = p.template && p.template.name || "";
    $("#edMeta").textContent = tn + " · " + p.photos.length + (p.photos.length === 1 ? " foto" : " fotos") + (p.target_pages ? " · objetivo " + p.target_pages + " págs." : "");
    $("#tabPhotosN").textContent = p.photos.length || "";
    const ai = p.units.filter((u) => u.uses_ai && u.kind !== "outline");
    $("#tabStructN").textContent = ai.length ? ai.filter((u) => u.status === "done").length + "/" + ai.length : "";
    document.title = p.title + " · Informes · PixAgent";
  }

  // ---- estructura (árbol de unidades)
  const STATUS = {
    pending: { lbl: "Pendiente", icon: '<span class="dot dot-muted"></span>' }, running: { lbl: "Redactando…", icon: '<span class="spinner"></span>' },
    done: { lbl: "Listo", icon: ico("check") }, edited: { lbl: "Editado a mano", icon: ico("edit") },
    error: { lbl: "Error", icon: ico("alert") }, auto: { lbl: "Automático al construir", icon: ico("zap") },
  };
  const unitState = (u) => u.status === "done" && u.edited ? "edited" : (u.status || "pending");
  function renderTree() {
    const p = state.project; if (!p) return;
    const units = p.units.filter((u) => u.kind !== "outline");
    const ai = units.filter((u) => u.uses_ai);
    $("#structSummary").textContent = ai.length ? ai.filter((u) => u.status === "done").length + " de " + ai.length + " partes listas" : "";
    $("#tabStructN").textContent = ai.length ? ai.filter((u) => u.status === "done").length + "/" + ai.length : "";
    if (!units.length) { $("#tree").innerHTML = '<div class="lbl">La estructura aparecerá cuando exista un índice.</div>'; return; }
    $("#tree").innerHTML = units.map((u) => {
      if (u.kind === "heading") return `<div class="ch">${esc(u.title)}</div>`;
      const st = unitState(u), S = STATUS[st] || STATUS.pending;
      const sub = st === "error" ? (u.error || "Error") : st === "auto" ? S.lbl : st === "done" || st === "edited" ? S.lbl + (u.words_written ? " · " + num(u.words_written) + " palabras" : "") : S.lbl + (u.words ? " · ~" + num(u.words) + " palabras" : "");
      const k = KINDS[u.kind === "auto_part" ? "ai" : u.kind];
      return `<button type="button" class="unit lvl${u.level} ${st} ${state.unit === u.id ? "on" : ""}" data-unit="${esc(u.id)}" title="${esc(u.title)}">
        <span class="st">${S.icon}</span>
        <span class="nm"><span>${esc(u.title || (k ? k.label : u.kind))}</span><small>${esc(sub)}</small></span>
        ${u.photos && u.photos.length ? `<span class="w" title="Fotos de esta parte">${ico("image", "icon-sm")} ${u.photos.length}</span>` : ""}
      </button>`;
    }).join("");
  }

  // ---- panel de generación
  function renderGenState() {
    const p = state.project; if (!p) return;
    const e = p.estimate || {};
    $("#genModel").textContent = MODELS[e.model] || e.model || "";
    $("#edRunning").classList.toggle("hidden", !state.running);
    const tokens = (e.input_tokens || 0) + (e.output_tokens || 0);
    const kTokens = tokens >= 1e6 ? (tokens / 1e6).toLocaleString("es-ES", { maximumFractionDigits: 1 }) + " M" : tokens >= 1000 ? Math.round(tokens / 1000).toLocaleString("es-ES") + " k" : num(tokens);
    const pages = Number(e.pages_estimate || 0).toLocaleString("es-ES", { maximumFractionDigits: 0 });
    // una línea visible; el detalle (llamadas, tokens, páginas) al desplegar
    $("#estLine").innerHTML = e.calls ? `<b>${usd(e.usd)}</b> · ${num(e.calls)} ${e.calls === 1 ? "llamada" : "llamadas"} · ≈ ${pages} págs.` : `<b>Todo redactado</b> · ≈ ${pages} págs.`;
    $("#estimate").innerHTML = `
      <div class="k"><b>${num(e.calls)}</b><small>Llamadas</small></div>
      <div class="k"><b>${kTokens}</b><small>Tokens</small></div>
      <div class="k usd"><b>${usd(e.usd)}</b><small>Coste aprox.</small></div>
      <div class="k"><b>≈ ${pages}</b><small>Páginas</small></div>
      <div class="est-note">${e.calls ? "Estimación orientativa de lo que falta por redactar; las partes ya listas no se repiten." : "Todas las partes están redactadas. Regenera una sección desde su editor o rehaz todo desde el menú ⋯."}</div>`;
    $("#genSub").textContent = state.running ? "Trabajando en segundo plano" : p.needs_outline ? "Primero hace falta el índice" : "Estimación antes de redactar";
    const prog = $("#genProgress");
    if (state.running) {
      prog.classList.remove("hidden");
      const pr = state.progress;
      $("#genCount").textContent = pr.total ? pr.done + "/" + pr.total : "";
      $("#genBar").style.width = pr.total ? Math.round(Math.min(1, pr.done / pr.total) * 100) + "%" : "8%";
    }
    renderPrimary();
  }
  // Acción principal única según el estado: Añadir fotos → Proponer índice → Redactar informe → Construir PDF → Ver PDF
  function primaryAction() {
    const p = state.project; if (!p) return null;
    const e = p.estimate || {};
    const pdf = p.outputs && p.outputs.pdf;
    const usesPhotos = p.units.some((u) => u.kind === "per_group" || u.kind === "heading" || u.kind === "photo_grid") || (p.template.sections || []).some((s) => s.photos);
    if (state.running) return { act: "running", label: "Redactando…", icon: "sparkle", disabled: true };
    if (!p.photos.length && usesPhotos && !pdf && e.calls) return { act: "photos", label: "Añadir fotos", icon: "plus" };
    if (p.needs_outline) return { act: "outline", label: "Proponer índice", icon: "book" };
    if (e.calls) return { act: "generate", label: "Redactar informe", icon: "sparkle" };
    const stale = pdf && p.updated && p.outputs.built && p.updated > p.outputs.built + 2;
    if (!pdf || stale) return { act: "build", label: stale ? "Reconstruir PDF" : "Construir PDF", icon: "pdf" };
    return { act: "view", label: "Ver PDF", icon: "eye" };
  }
  function renderPrimary() {
    const a = primaryAction(), b = $("#edPrimary"); if (!a) return;
    b.dataset.act = a.act; b.disabled = !!a.disabled;
    b.innerHTML = (a.act === "running" ? '<span class="spinner"></span>' : ico(a.icon)) + `<span>${esc(a.label)}</span>`;
    b.title = a.label;
  }
  $("#edPrimary").onclick = () => {
    const act = $("#edPrimary").dataset.act;
    if (act === "photos") { document.body.dataset.etab = "photos"; $("#fileInput").click(); }
    else if (act === "outline") generate({ sections: [] }, "Diseñando el índice…");
    else if (act === "generate") generateAll();
    else if (act === "build") buildPdf();
    else if (act === "view") document.body.dataset.etab = "preview";
  };
  // Menú «⋯»: acciones secundarias (datos, regenerar todo, cancelar, reconstruir, markdown, borrar)
  $("#edMore").onclick = (e) => {
    const p = state.project; if (!p) return;
    const e2 = p.estimate || {}, pdf = p.outputs && p.outputs.pdf;
    const items = [{ label: "Datos del informe…", icon: "sliders", onClick: openDataModal }];
    if (state.running) items.push({ label: "Cancelar la redacción", icon: "stop", onClick: cancelGeneration });
    else {
      items.push({ label: e2.calls ? "Redactar lo que falta" : "Rehacer todo el informe", icon: "sparkle", disabled: !!p.needs_outline, onClick: generateAll });
    }
    items.push("-");
    items.push({ label: pdf ? "Reconstruir PDF" : "Construir PDF", icon: "pdf", disabled: !!state.running && false, onClick: buildPdf });
    if (pdf) items.push({ label: "Abrir PDF en pestaña nueva", icon: "external", onClick: () => window.open(fileUrl(pdf), "_blank", "noopener") });
    if (p.outputs && p.outputs.md) items.push({ label: "Ver Markdown", icon: "text", onClick: () => window.open(fileUrl(p.outputs.md), "_blank", "noopener") });
    items.push("-", { label: "Borrar informe", icon: "trash", danger: true, onClick: deleteReport });
    const r = e.currentTarget.getBoundingClientRect();
    showMenu(items, r.right - 220, r.bottom + 6);
  };
  function genMsg(type, text) {
    const m = $("#genMsg");
    m.className = "gen-msg " + type; m.innerHTML = ico(type === "ok" ? "check" : "alert") + `<span>${esc(text)}</span>`;
  }
  async function generate(body, label) {
    if (!state.rid) return;
    $("#genMsg").classList.add("hidden");
    const j = await api("/api/reports/" + encodeURIComponent(state.rid) + "/generate", body || {});
    if (!j.ok) { toast(j.error || "No se pudo iniciar la redacción", 5000, "err"); return false; }
    state.running = true; state.progress = { total: 0, done: 0 };
    state.outlineOnly = !!(body && body.sections && body.sections.length === 0);
    $("#genLabel").textContent = label || "Preparando…";
    renderGenState();
    if (isMobile() && !body.sections) document.body.dataset.etab = "structure";
    return true;
  }
  async function generateAll() {
    const p = state.project; if (!p || state.running) return;
    const e = p.estimate || {};
    if (!p.photos.length && p.units.some((u) => u.kind === "per_group")) {
      if (!await askConfirm("¿Redactar sin fotos?", "La plantilla crea un apartado por zona de fotos y todavía no hay ninguna. Puedes añadirlas primero.", "Redactar igualmente", true)) return;
    }
    if (!e.calls) {
      if (!await askConfirm("¿Rehacer todo el informe?", "Se volverán a redactar todas las partes, incluidas las editadas a mano. Coste aproximado: " + usd(e.usd) + ".", "Rehacer todo")) return;
      const ids = p.units.filter((u) => u.uses_ai && u.kind !== "outline").map((u) => u.id);
      generate({ sections: ids, force: true, unlock: true }, "Rehaciendo todas las partes…");
      return;
    }
    if (!await askConfirm("¿Redactar el informe?", num(e.calls) + (e.calls === 1 ? " llamada a la IA" : " llamadas a la IA") + ", coste aproximado " + usd(e.usd) + ". Puedes cancelar en cualquier momento; las partes terminadas se conservan.", "Redactar", true)) return;
    generate({}, "Preparando " + e.calls + (e.calls === 1 ? " llamada…" : " llamadas…"));
  }
  async function cancelGeneration() {
    await api("/api/reports/" + encodeURIComponent(state.rid) + "/cancel", {});
    $("#genLabel").textContent = "Cancelando… (termina la parte en curso)";
  }

  // ---- índice automático
  function renderOutlineCard() {
    const p = state.project, card = $("#outlineCard");
    const hasAuto = p.units.some((u) => u.kind === "outline") || !!p.outline || (p.template.sections || []).some((s) => s.kind === "auto_outline");
    card.classList.toggle("hidden", !hasAuto);
    if (!hasAuto) return;
    if (p.needs_outline) {
      card.classList.remove("ready");
      card.innerHTML = `<div class="row gap-2">${ico("book")}<b class="grow">Esta plantilla necesita un índice</b></div>
        <div class="small muted">La IA propondrá capítulos y apartados para unas <b>${p.target_pages || 20} páginas</b> a partir de tus notas y fotos. Después podrás editar el índice antes de redactar.</div>
        <button type="button" class="btn btn-primary" id="outlinePropose" ${state.running ? "disabled" : ""}>${ico("sparkle")}Proponer índice con IA</button>`;
      $("#outlinePropose").onclick = () => generate({ sections: [] }, "Diseñando el índice…");
      return;
    }
    const o = p.outline || { chapters: [] };
    const nS = o.chapters.reduce((a, c) => a + (c.sections || []).length, 0), w = o.chapters.reduce((a, c) => a + (c.sections || []).reduce((b, s) => b + (+s.words || 0), 0), 0);
    card.classList.add("ready");
    card.innerHTML = `<div class="row gap-2">${ico("book")}<b class="grow">Índice</b><span class="xs faint tabular">${o.chapters.length} cap. · ${nS} apart. · ~${num(w)} palabras</span></div>
      <div class="row gap-2 wrap"><button type="button" class="btn btn-sm" id="outlineEdit">${ico("edit")}Editar índice</button>
      <button type="button" class="btn btn-sm btn-ghost" id="outlineRedo" ${state.running ? "disabled" : ""}>${ico("refresh")}Proponer otro</button></div>`;
    $("#outlineEdit").onclick = openOutlineEditor;
    $("#outlineRedo").onclick = async () => {
      if (await askConfirm("¿Proponer un índice nuevo?", "El índice actual se sustituirá. Las partes ya redactadas con el mismo número de apartado se conservan; el resto habrá que redactarlas de nuevo.", "Proponer otro", true))
        generate({ sections: [], force: true }, "Diseñando un índice nuevo…");
    };
  }
  function openOutlineEditor() {
    state.outline = JSON.parse(JSON.stringify(state.project.outline || { chapters: [] }));
    renderOutline(); openModal("#outlineModal");
  }
  function renderOutline() {
    const o = state.outline, nPhotos = state.project.photos.length;
    const nS = o.chapters.reduce((a, c) => a + (c.sections || []).length, 0), w = o.chapters.reduce((a, c) => a + (c.sections || []).reduce((b, s) => b + (+s.words || 0), 0), 0);
    $("#outlineSum").textContent = `${o.chapters.length} capítulos · ${nS} apartados · ~${num(w)} palabras ≈ ${Math.round(w / 450)} páginas` + (state.project.target_pages ? ` (objetivo ${state.project.target_pages})` : "");
    $("#outlineBody").innerHTML = o.chapters.map((c, ci) => `
      <div class="oc" data-ci="${ci}">
        <div class="oc-head"><span class="n">${ci + 1}</span><input class="input" data-ck="title" value="${esc(c.title)}" placeholder="Título del capítulo" aria-label="Capítulo ${ci + 1}">
          <span class="mv"><button type="button" class="btn btn-ghost" data-cmv="-1" title="Subir" ${ci === 0 ? "disabled" : ""}>${ico("up")}</button><button type="button" class="btn btn-ghost" data-cmv="1" title="Bajar" ${ci === o.chapters.length - 1 ? "disabled" : ""}>${ico("down")}</button><button type="button" class="btn btn-ghost" data-cdel title="Quitar capítulo">${ico("trash")}</button></span></div>
        ${(c.sections || []).map((s, si) => `
          <div class="os" data-si="${si}"><span class="n">${ci + 1}.${si + 1}</span>
            <div><input class="input" data-sk="title" value="${esc(s.title)}" placeholder="Título del apartado" aria-label="Apartado ${ci + 1}.${si + 1}"><textarea class="textarea" data-sk="brief" rows="1" placeholder="Qué debe cubrir (2–3 frases)">${esc(s.brief || "")}</textarea></div>
            <label class="w"><span class="lbl">Palabras</span><input class="input tabular" type="number" min="100" max="3000" step="50" inputmode="numeric" data-sk="words" value="${esc(s.words || 600)}"></label>
            <label class="p"><span class="lbl">Fotos (nº)</span><input class="input" data-sk="photos" value="${esc((s.photos || []).join(", "))}" placeholder="${nPhotos ? "1, 2…" : "—"}" inputmode="numeric"></label>
            <span class="mv"><button type="button" class="btn btn-ghost" data-smv="-1" title="Subir" ${si === 0 ? "disabled" : ""}>${ico("up")}</button><button type="button" class="btn btn-ghost" data-smv="1" title="Bajar" ${si === c.sections.length - 1 ? "disabled" : ""}>${ico("down")}</button><button type="button" class="btn btn-ghost" data-sdel title="Quitar apartado">${ico("trash")}</button></span>
          </div>`).join("")}
        <div class="oc-foot"><button type="button" class="btn btn-sm btn-ghost" data-sadd>${ico("plus")}Apartado</button></div>
      </div>`).join("") || '<div class="empty-inline">Sin capítulos. Añade uno o pide a la IA que proponga el índice.</div>';
  }
  $("#outlineBody").addEventListener("input", (e) => {
    const t = e.target, oc = t.closest(".oc"); if (!oc) return;
    const c = state.outline.chapters[+oc.dataset.ci];
    if (t.dataset.ck) { c[t.dataset.ck] = t.value; return; }
    const os = t.closest(".os"); if (!os) return;
    const s = c.sections[+os.dataset.si], k = t.dataset.sk;
    if (k === "words") s.words = Math.max(50, +t.value || 0);
    else if (k === "photos") s.photos = t.value.split(/[\s,;]+/).map((x) => parseInt(x, 10)).filter((n) => n > 0 && n <= state.project.photos.length);
    else s[k] = t.value;
  });
  $("#outlineBody").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const oc = b.closest(".oc"); if (!oc) return;
    const ci = +oc.dataset.ci, chs = state.outline.chapters, c = chs[ci];
    const move = (arr, i, d) => { const j = i + d; if (j < 0 || j >= arr.length) return; const x = arr.splice(i, 1)[0]; arr.splice(j, 0, x); };
    if (b.dataset.cmv) move(chs, ci, +b.dataset.cmv);
    else if (b.hasAttribute("data-cdel")) chs.splice(ci, 1);
    else if (b.hasAttribute("data-sadd")) (c.sections = c.sections || []).push({ title: "", brief: "", words: 600, photos: [] });
    else {
      const os = b.closest(".os"); if (!os) return;
      const si = +os.dataset.si;
      if (b.dataset.smv) move(c.sections, si, +b.dataset.smv);
      else if (b.hasAttribute("data-sdel")) c.sections.splice(si, 1);
    }
    renderOutline();
  });
  $("#outlineAddCh").onclick = () => { state.outline.chapters.push({ title: "", sections: [{ title: "", brief: "", words: 600, photos: [] }] }); renderOutline(); $("#outlineBody").scrollTop = 1e6; };
  $("#outlineSave").onclick = async () => {
    const o = state.outline;
    o.chapters = o.chapters.filter((c) => (c.title || "").trim() || (c.sections || []).some((s) => (s.title || "").trim()));
    o.chapters.forEach((c, i) => { c.title = (c.title || "").trim() || "Capítulo " + (i + 1); c.sections = (c.sections || []).filter((s) => (s.title || "").trim()); });
    if (!o.chapters.length) { toast("El índice necesita al menos un capítulo con un apartado", 3500, "warn"); return; }
    const j = await apiPut("/api/reports/" + encodeURIComponent(state.rid), { outline: o });
    if (!j.ok) { toast(j.error || "No se pudo guardar el índice", 4000, "err"); return; }
    closeModal("#outlineModal"); toast("Índice guardado", 2000, "ok");
    state.project = j.report; renderEditorHead(); renderTree(); renderGenState(); renderOutlineCard();
  };

  // ---- fotos
  const groups = () => { const g = []; (state.project.photos || []).forEach((ph) => { const v = (ph.group || "").trim(); if (v && g.indexOf(v) < 0) g.push(v); }); return g; };
  function updateGroupsDatalist() { $("#groupsList").innerHTML = groups().map((g) => `<option value="${esc(g)}">`).join(""); }
  function renderPhotos() {
    const p = state.project, photos = p.photos || [];
    $("#photosN").textContent = photos.length ? photos.length : "";
    updateGroupsDatalist();
    const perGroup = p.units.some((u) => u.kind === "per_group" || u.kind === "heading");
    $(".photos-top .small").textContent = perGroup ? "Pon un pie a cada foto y agrúpalas por zona: la plantilla redacta un apartado por zona."
      : "Pon un pie a cada foto. La IA las cita como «Foto N» y pueden asignarse a apartados del índice.";
    const cells = photos.map((ph, i) => `
      <div class="ph ${state.sel.indexOf(i) >= 0 ? "sel" : ""}" data-idx="${i}" ${isTouch ? "" : 'draggable="true"'}>
        <div class="ph-img"><img loading="lazy" decoding="async" src="${thumbUrl(ph.path, 320)}" alt="Foto ${i + 1}" width="320" height="240">
          <span class="ph-num">Foto ${i + 1}</span>
          <label class="ph-sel" title="Seleccionar"><input type="checkbox" data-sel="${i}" ${state.sel.indexOf(i) >= 0 ? "checked" : ""}>${ico("check")}</label>
          <span class="ph-tools">
            <button type="button" class="btn" data-mv="-1" title="Mover antes" ${i === 0 ? "disabled" : ""}>${ico("back")}</button>
            <button type="button" class="btn" data-mv="1" title="Mover después" ${i === photos.length - 1 ? "disabled" : ""}><svg class="icon" style="transform:rotate(180deg)"><use href="#i-back"/></svg></button>
            <button type="button" class="btn rm" data-rm title="Quitar foto">${ico("trash")}</button>
          </span></div>
        <div class="ph-fields">
          <input class="input" data-k="caption" value="${esc(ph.caption)}" placeholder="Pie de foto" aria-label="Pie de la foto ${i + 1}">
          <span class="ph-grp">${ico("tag")}<input class="input" data-k="group" list="groupsList" value="${esc(ph.group)}" placeholder="Zona (fachada, cocina…)" aria-label="Zona de la foto ${i + 1}"></span>
          <textarea class="textarea nt" data-k="notes" rows="1" placeholder="Notas para la IA…" aria-label="Notas de la foto ${i + 1}">${esc(ph.notes)}</textarea>
        </div>
      </div>`).join("");
    $("#photoGrid").innerHTML = cells + `<label class="ph-add" for="fileInput">${ico("plus")}<b>${photos.length ? "Añadir más fotos" : "Añadir fotos"}</b><small>${isTouch ? "Toca para elegir de la galería" : "Haz clic o arrastra aquí · JPG, PNG, HEIC"}</small></label>`;
    renderBulk();
  }
  function renderBulk() {
    const n = state.sel.length;
    $("#bulkBar").classList.toggle("hidden", !n);
    $("#bulkN").textContent = n + (n === 1 ? " foto seleccionada" : " fotos seleccionadas");
  }
  function savePhotos(now) {
    clearTimeout(state.saveTimer);
    const doSave = async () => {
      if (!state.rid) return;
      const rid = state.rid;
      const j = await apiPut("/api/reports/" + encodeURIComponent(rid), { photos: state.project.photos });
      if (state.rid !== rid) return;
      if (!j.ok) { toast(j.error || "No se pudieron guardar las fotos", 4000, "err"); return; }
      // la estructura (apartados por zona) y la estimación dependen de las fotos
      const keepPhotos = state.project.photos;
      state.project = j.report; state.project.photos = keepPhotos;
      renderEditorHead(); renderTree(); renderGenState(); renderOutlineCard(); updateGroupsDatalist(); renderRecent();
    };
    if (now) return doSave();
    state.saveTimer = setTimeout(doSave, 700);
  }
  $("#photoGrid").addEventListener("input", (e) => {
    const t = e.target, ph = t.closest(".ph"); if (!ph || !t.dataset.k) return;
    state.project.photos[+ph.dataset.idx][t.dataset.k] = t.value;
    if (t.dataset.k === "notes") { t.style.height = "auto"; t.style.height = Math.min(120, t.scrollHeight) + "px"; }
    savePhotos();
  });
  $("#photoGrid").addEventListener("change", (e) => {
    const t = e.target;
    if (t.dataset.sel !== undefined) {
      const i = +t.dataset.sel, at = state.sel.indexOf(i);
      if (t.checked && at < 0) state.sel.push(i); else if (!t.checked && at >= 0) state.sel.splice(at, 1);
      t.closest(".ph").classList.toggle("sel", t.checked); renderBulk();
    } else if (t.dataset.k === "group") updateGroupsDatalist();
  });
  $("#photoGrid").addEventListener("click", async (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const ph = b.closest(".ph"); if (!ph) return;
    const i = +ph.dataset.idx, photos = state.project.photos;
    if (b.dataset.mv) { const j = i + (+b.dataset.mv); if (j < 0 || j >= photos.length) return; const x = photos.splice(i, 1)[0]; photos.splice(j, 0, x); state.sel = []; renderPhotos(); savePhotos(); }
    else if (b.hasAttribute("data-rm")) {
      if (!await askConfirm("¿Quitar esta foto del informe?", "El archivo se conserva en el workspace; solo se quita de este informe.", "Quitar")) return;
      photos.splice(i, 1); state.sel = []; renderPhotos(); savePhotos();
    }
  });
  // arrastrar para reordenar (escritorio)
  let dragFrom = null;
  $("#photoGrid").addEventListener("dragstart", (e) => {
    const ph = e.target.closest(".ph"); if (!ph || e.target.closest("input, textarea, button")) { if (!ph) return; e.preventDefault(); return; }
    dragFrom = +ph.dataset.idx; ph.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(dragFrom));
  });
  $("#photoGrid").addEventListener("dragover", (e) => { if (dragFrom == null) return; e.preventDefault(); const ph = e.target.closest(".ph"); $$(".ph.over").forEach((x) => x.classList.remove("over")); if (ph) ph.classList.add("over"); });
  $("#photoGrid").addEventListener("dragend", () => { dragFrom = null; $$(".ph.dragging, .ph.over").forEach((x) => x.classList.remove("dragging", "over")); });
  $("#photoGrid").addEventListener("drop", (e) => {
    const ph = e.target.closest(".ph");
    if (dragFrom == null || !ph) return;
    e.preventDefault(); e.stopPropagation();
    const to = +ph.dataset.idx, photos = state.project.photos;
    if (to !== dragFrom) { const x = photos.splice(dragFrom, 1)[0]; photos.splice(to, 0, x); state.sel = []; renderPhotos(); savePhotos(); }
    dragFrom = null;
  });
  $("#bulkApply").onclick = () => {
    const g = $("#bulkGroup").value.trim();
    state.sel.forEach((i) => { if (state.project.photos[i]) state.project.photos[i].group = g; });
    state.sel = []; $("#bulkGroup").value = ""; renderPhotos(); savePhotos();
    toast(g ? "Zona «" + g + "» asignada" : "Zona quitada", 2000, "ok");
  };
  $("#bulkClear").onclick = () => { state.sel = []; renderPhotos(); };
  $("#bulkRemove").onclick = async () => {
    const n = state.sel.length;
    if (!await askConfirm("¿Quitar " + n + (n === 1 ? " foto?" : " fotos?"), "Los archivos se conservan en el workspace.", "Quitar")) return;
    state.project.photos = state.project.photos.filter((_, i) => state.sel.indexOf(i) < 0);
    state.sel = []; renderPhotos(); savePhotos();
  };

  // subida (fotos reducidas en el dispositivo, igual que en el chat)
  async function shrinkImage(file) {
    if (!/^image\/(jpeg|png|webp|heic|heif)$/i.test(file.type) && !/\.(heic|heif)$/i.test(file.name)) return file;
    const max = state.maxPx;
    let bmp;
    try { bmp = await createImageBitmap(file); } catch (e) {
      bmp = await new Promise((res, rej) => { const im = new Image(); im.onload = () => res(im); im.onerror = rej; im.src = URL.createObjectURL(file); }).catch(() => null);
    }
    if (!bmp) return file;
    const w = bmp.width, h = bmp.height, k = Math.min(1, max / Math.max(w, h));
    const isHeic = /hei[cf]/i.test(file.type + file.name);
    if (k === 1 && !isHeic && file.size < 3.5e6) { if (bmp.close) bmp.close(); return file; }
    const c = document.createElement("canvas"); c.width = Math.round(w * k); c.height = Math.round(h * k);
    const g = c.getContext("2d"); g.imageSmoothingQuality = "high"; g.drawImage(bmp, 0, 0, c.width, c.height);
    if (bmp.close) bmp.close();
    const keepPng = file.type === "image/png" && k === 1;
    const blob = await new Promise((r) => c.toBlob(r, keepPng ? "image/png" : "image/jpeg", 0.9));
    c.width = c.height = 0;
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.(heic|heif|png|webp)$/i, keepPng ? ".png" : ".jpg"), { type: blob.type });
  }
  async function uploadPhotos(list) {
    const files = Array.from(list || []).filter((f) => /^image\//i.test(f.type) || /\.(heic|heif|jpe?g|png|webp)$/i.test(f.name));
    if (!files.length || !state.project) { if (list && list.length) toast("Solo se admiten imágenes", 3000, "warn"); return; }
    const bar = $("#uploadBar"); bar.classList.remove("hidden");
    $("#uploadLbl").textContent = "Preparando " + files.length + (files.length === 1 ? " foto…" : " fotos…"); $("#uploadPct").textContent = ""; $("#uploadProg").style.width = "0%";
    const fd = new FormData();
    for (let i = 0; i < files.length; i++) { const f = await shrinkImage(files[i]); fd.append("files", f, f.name || ("foto_" + Date.now() + "_" + i + ".jpg")); }
    $("#uploadLbl").textContent = "Subiendo…";
    const rid = state.rid;
    await new Promise((resolve) => {
      const x = new XMLHttpRequest(); x.open("POST", "/api/upload");
      x.upload.onprogress = (e) => { if (!e.lengthComputable) return; const p = Math.round(e.loaded / e.total * 100); $("#uploadProg").style.width = p + "%"; $("#uploadPct").textContent = p + "%"; };
      x.onload = () => {
        try {
          const paths = JSON.parse(x.responseText).files || [];
          if (state.rid === rid && state.project) {
            paths.forEach((p) => state.project.photos.push({ path: p, caption: "", group: "", notes: "" }));
            renderPhotos(); savePhotos(true);
            toast(paths.length + (paths.length === 1 ? " foto añadida" : " fotos añadidas"), 2200, "ok");
          }
        } catch (e) { toast("Error al subir las fotos", 3500, "err"); }
        resolve();
      };
      x.onerror = () => { toast("Error de red al subir", 3500, "err"); resolve(); };
      x.send(fd);
    });
    bar.classList.add("hidden");
  }
  $("#fileInput").addEventListener("change", (e) => { uploadPhotos(e.target.files); e.target.value = ""; });
  $("#camInput").addEventListener("change", (e) => { uploadPhotos(e.target.files); e.target.value = ""; });
  const pp = $("#photosPane");
  pp.addEventListener("dragover", (e) => { if (dragFrom != null) return; e.preventDefault(); $("#dropHint").classList.remove("hidden"); });
  pp.addEventListener("dragleave", (e) => { if (!pp.contains(e.relatedTarget)) $("#dropHint").classList.add("hidden"); });
  pp.addEventListener("drop", (e) => { $("#dropHint").classList.add("hidden"); if (dragFrom != null) return; e.preventDefault(); uploadPhotos(e.dataTransfer.files); });
  document.addEventListener("paste", (e) => {
    if (document.body.dataset.screen !== "editor") return;
    const files = Array.from((e.clipboardData && e.clipboardData.files) || []);
    if (files.length) { e.preventDefault(); uploadPhotos(files); }
  });

  // ---- editor de sección
  function openSection(uid) {
    const u = state.project.units.find((x) => x.id === uid); if (!u) return;
    const wasOpen = !!state.unit;
    state.unit = uid; state.dirty = false;
    renderTree();
    const pane = $("#sectionPane"); pane.classList.remove("hidden");
    if (!wasOpen) pushLayer("section", () => closeSection(true)); // «atrás» cierra la sección
    renderSectionHead(u);
    const auto = !u.uses_ai;
    $(".sec-body", pane).classList.toggle("hidden", auto); $(".sec-tools", pane).classList.toggle("hidden", auto);
    $("#secAuto").classList.toggle("hidden", !auto);
    $("#secSave").disabled = true;
    if (auto) {
      const k = KINDS[u.kind] || { label: u.kind, icon: "zap", desc: "" };
      const sec = (state.project.template.sections || []).find((s) => s.id === u.section_id) || {};
      let extra = "";
      if (u.kind === "static") extra = `<div class="prose card card-pad">${md(sec.content || "")}</div>`;
      if (u.kind === "fields_table") extra = `<div class="prose card card-pad">${md("| Dato | Valor |\n|---|---|\n" + (state.project.template.fields || []).map((f) => `| ${f.label || f.key} | ${state.project.fields[f.key] || "—"} |`).join("\n"))}</div>`;
      if (u.kind === "photo_grid") extra = `<div class="small muted">${state.project.photos.length} ${state.project.photos.length === 1 ? "foto" : "fotos"} en rejilla ${esc(sec.layout || "2x3")} con sus pies.</div>`;
      $("#secAuto").innerHTML = `<span class="empty-icon">${ico(k.icon)}</span><div class="empty-title">${esc(k.label)}</div><div class="empty-text">Esta parte se genera sola al construir el PDF y no gasta tokens. ${esc(k.desc)}</div>${extra}`;
      return;
    }
    $("#secText").value = ""; $("#secPreview").innerHTML = ""; $("#secWords").textContent = "";
    setSecMode("edit");
    loadSectionText(uid);
  }
  async function loadSectionText(uid) {
    if (state.dirty) return;
    const j = await api("/api/reports/" + encodeURIComponent(state.rid) + "/sections/" + encodeURIComponent(uid));
    if (state.unit !== uid) return;
    $("#secText").value = j.markdown || "";
    $("#secPreview").innerHTML = md(j.markdown || "");
    $("#secWords").textContent = j.markdown ? num(words(j.markdown)) + " palabras" : "";
    $("#secSave").disabled = true; state.dirty = false;
  }
  function renderSectionHead(u) {
    if (!u) return;
    const st = unitState(u), S = STATUS[st] || STATUS.pending;
    $("#secChapter").textContent = u.chapter || (KINDS[u.kind === "auto_part" ? "ai" : u.kind] || {}).label || "";
    $("#secTitle").textContent = u.title;
    const cls = st === "done" ? "chip-ok" : st === "edited" ? "chip-accent" : st === "error" ? "chip-danger" : st === "running" ? "chip-accent" : "";
    $("#secStatus").innerHTML = `<span class="chip ${cls}">${S.icon}${S.lbl}</span>`;
    const err = $("#secError");
    err.classList.toggle("hidden", st !== "error");
    if (st === "error") err.innerHTML = ico("alert") + `<div><b>No se pudo redactar esta parte.</b><br>${esc(u.error || "Error desconocido")}<br><span class="xs">Comprueba la clave de API y la conexión, y pulsa «Regenerar con IA». También puedes escribir el texto a mano.</span></div>`;
    $("#secRegen").disabled = !!state.running || st === "running";
  }
  function setSecMode(m) {
    $(".sec-body").dataset.mode = m;
    $$("#secMode button").forEach((b) => b.classList.toggle("on", b.dataset.mode === m));
    if (m === "preview") $("#secPreview").innerHTML = md($("#secText").value);
  }
  $("#secMode").addEventListener("click", (e) => { const b = e.target.closest("[data-mode]"); if (b) setSecMode(b.dataset.mode); });
  let secRaf = false;
  $("#secText").addEventListener("input", () => {
    state.dirty = true; $("#secSave").disabled = false;
    if (secRaf) return; secRaf = true;
    requestAnimationFrame(() => { secRaf = false; const v = $("#secText").value; $("#secWords").textContent = num(words(v)) + " palabras"; if (!isMobile()) $("#secPreview").innerHTML = md(v); });
  });
  $("#secSave").onclick = async () => {
    const uid = state.unit; if (!uid) return;
    const text = $("#secText").value;
    const j = await apiPut("/api/reports/" + encodeURIComponent(state.rid) + "/sections/" + encodeURIComponent(uid), { markdown: text });
    if (!j.ok) { toast(j.error || "No se pudo guardar", 4000, "err"); return; }
    state.dirty = false; $("#secSave").disabled = true;
    const u = state.project.units.find((x) => x.id === uid);
    if (u) { u.status = "done"; u.edited = true; u.error = null; u.words_written = words(text); renderSectionHead(u); renderTree(); }
    toast("Sección guardada", 2000, "ok"); scheduleReload();
  };
  $("#secRegen").onclick = async () => {
    const uid = state.unit; if (!uid) return;
    const u = state.project.units.find((x) => x.id === uid);
    if (u && (u.status === "done") && !await askConfirm("¿Regenerar esta sección?", "El texto actual" + (u.edited ? " (editado a mano)" : "") + " se sustituirá por una redacción nueva de la IA.", "Regenerar", true)) return;
    state.dirty = false;
    if (await generate({ sections: [uid], force: true, unlock: true }, "Redactando: " + (u ? u.title : uid))) {
      if (u) { u.status = "running"; u.error = null; renderSectionHead(u); renderTree(); }
      toast("Redactando la sección…", 2000);
    }
  };
  function closeSection(fromBack) {
    if (!state.unit && $("#sectionPane").classList.contains("hidden")) return;
    state.unit = null; state.dirty = false; $("#sectionPane").classList.add("hidden"); renderTree();
    if (!fromBack) dropLayer("section");
    if (isMobile()) document.body.dataset.etab = "structure";
  }
  $("#secBack").onclick = () => closeSection();

  // ---- vista previa / PDF
  function renderPreview() {
    const p = state.project, body = $("#previewBody");
    const pdf = p && p.outputs && p.outputs.pdf;
    if (!pdf) {
      body.innerHTML = `<div class="empty"><span class="empty-icon">${ico("pdf")}</span><div class="empty-title">Todavía no hay PDF</div>
        <div class="empty-text">Cuando las secciones estén redactadas (o escritas a mano), construye el PDF con portada, índice, tablas y panel fotográfico.</div>
        <button type="button" class="btn btn-primary mt-3" id="pvBuild">${ico("pdf")}Construir PDF</button></div>`;
      $("#pvBuild").onclick = buildPdf;
      return;
    }
    const built = p.outputs.built ? fmtDate(p.outputs.built) : "";
    const warns = (p.outputs.warnings || []);
    const canPin = !!(state.status && state.status.pixpin);
    body.innerHTML = `<div class="pv-actions">
        <span class="nm">${ico("pdf")}<b>${esc(baseName(pdf))}</b>${built ? `<span class="xs faint">construido ${esc(built)}</span>` : ""}</span>
        <div class="pv-btns">
          ${canPin ? `<button type="button" class="btn btn-ghost btn-icon btn-sm" id="pvPin" title="Fijar en PixPin">${ico("pin")}</button>` : ""}
          ${navigator.share ? `<button type="button" class="btn btn-ghost btn-icon btn-sm" id="pvShare" title="Compartir">${ico("share")}</button>` : ""}
          <a class="btn btn-ghost btn-icon btn-sm" href="${fileUrl(pdf)}" download="${esc(baseName(pdf))}" title="Descargar">${ico("download")}</a>
          <a class="btn btn-ghost btn-icon btn-sm" href="${fileUrl(pdf)}" target="_blank" rel="noopener" title="Abrir en pestaña nueva">${ico("external")}</a>
        </div></div>
      ${warns.length ? `<div class="alert alert-warn pv-warn">${ico("alert")}<div>${warns.map(esc).join("<br>")}</div></div>` : ""}
      <div id="pvDoc" class="grow" style="display:flex;flex-direction:column;min-height:0"></div>`;
    if ($("#pvPin")) $("#pvPin").onclick = async () => { const j = await api("/api/pixpin/pin", { files: [pdf] }); toast(j.ok ? "Fijado en PixPin" : (j.error || "PixPin no disponible"), j.ok ? 2000 : 5000, j.ok ? "ok" : "err"); };
    if ($("#pvShare")) $("#pvShare").onclick = async () => {
      try {
        const blob = await (await fetch(fileUrl(pdf))).blob();
        const file = new File([blob], baseName(pdf), { type: "application/pdf" });
        if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file], title: p.title });
        else await navigator.share({ title: p.title, url: location.origin + fileUrl(pdf) });
      } catch (err) { if (err.name !== "AbortError") toast("No se pudo compartir", 3000, "err"); }
    };
    const doc = $("#pvDoc"), url = fileUrl(pdf) + "?t=" + Math.round(p.outputs.built || 0);
    if (state.zoom) { try { state.zoom.destroy(); } catch (e) { /* ya destruido */ } state.zoom = null; }
    if (isTouch || isIOS) { // iOS solo muestra la 1.ª página en iframes: páginas como imágenes, con zoom por pellizco (PixZoom)
      doc.innerHTML = '<div class="pdfpages"><div class="loading"><span class="spinner spinner-lg"></span></div></div>';
      const rid = state.rid;
      api("/api/pdfinfo/" + enc(pdf)).then((j) => {
        if (state.rid !== rid) return;
        const n = Math.min(j.pages || 0, 120), w = Math.min(900, doc.clientWidth || 600);
        if (!n) { doc.innerHTML = `<iframe src="${url}" title="PDF"></iframe>`; return; }
        doc.innerHTML = '<div class="zoombox" id="pvZoom"><div class="pdfpages">' + Array.from({ length: n }, (_, i) => `<img loading="lazy" decoding="async" src="${thumbUrl(pdf, w, i)}&t=${Math.round(p.outputs.built || 0)}" alt="Página ${i + 1}">`).join("") + "</div></div>";
        if (window.PixZoom) state.zoom = PixZoom.attach($("#pvZoom"), $("#pvZoom .pdfpages"), { wheel: "scroll" });
      });
    } else doc.innerHTML = `<iframe src="${url}" title="PDF"></iframe>`;
  }
  async function buildPdf() {
    const p = state.project; if (!p) return;
    const pend = p.units.filter((u) => u.uses_ai && u.kind !== "outline" && u.status !== "done");
    if (pend.length && !await askConfirm("Hay " + pend.length + (pend.length === 1 ? " parte sin redactar" : " partes sin redactar"), "El PDF marcará esas partes como pendientes. Puedes construirlo igualmente para revisar el formato.", "Construir igualmente", true)) return;
    const b = $("#edPrimary"); b.disabled = true;
    toast("Construyendo el PDF…", 2500);
    const j = await api("/api/reports/" + encodeURIComponent(state.rid) + "/build", {});
    b.disabled = false;
    if (!j.ok) { toast(j.error || "No se pudo construir el PDF", 6000, "err"); return; }
    toast("PDF listo: " + j.pages + (j.pages === 1 ? " página" : " páginas"), 3000, "ok");
    await loadProject(state.rid, true);
    renderPreview();
    document.body.dataset.etab = "preview";
    loadReports();
  }
  async function deleteReport() {
    const p = state.project; if (!p) return;
    if (!await askConfirm("¿Borrar este informe?", "«" + p.title + "» y sus secciones redactadas se eliminarán de forma permanente. Las fotos originales se conservan.")) return;
    await apiDel("/api/reports/" + encodeURIComponent(state.rid));
    closeModal("#dataModal"); toast("Informe borrado", 2000, "ok"); state.reports = null; go("#/");
  }

  // ---- datos del informe
  function openDataModal() {
    const p = state.project, t = p.template;
    $("#dTitle").value = p.title; $("#dNotes").value = p.notes || "";
    $("#dFields").innerHTML = fieldsForm(t, "df", p.fields);
    $("#dPagesWrap").classList.toggle("hidden", !hasOutline(t)); $("#dPages").value = p.target_pages || 20;
    $$("#dModel button").forEach((b) => b.classList.toggle("on", b.dataset.model === (p.model || "claude-opus-5-5")));
    openModal("#dataModal");
  }
  $("#dModel").addEventListener("click", (e) => { const b = e.target.closest("[data-model]"); if (b) $$("#dModel button").forEach((x) => x.classList.toggle("on", x === b)); });
  $("#dataForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const p = state.project, t = p.template;
    const on = $("#dModel .on");
    const body = { title: $("#dTitle").value.trim() || p.title, notes: $("#dNotes").value, fields: readFields(t, "df"), model: on ? on.dataset.model : p.model };
    if (hasOutline(t)) body.target_pages = Math.max(5, Math.min(200, +$("#dPages").value || 20));
    const j = await apiPut("/api/reports/" + encodeURIComponent(state.rid), body);
    if (!j.ok) { toast(j.error || "No se pudo guardar", 4000, "err"); return; }
    state.project = j.report; renderEditorHead(); renderGenState(); renderOutlineCard(); renderTree();
    closeModal("#dataModal"); toast("Datos guardados", 2000, "ok"); loadReports();
  });
  $("#dDelete").onclick = deleteReport;

  // ---------------------------------------------------------------- editor de plantillas
  const KIND_STYLE = (k) => { const K = KINDS[k] || KINDS.static; return `style="--kind-color:${K.color};--kind-soft:${K.soft}"`; };
  async function openTemplateEditor(tid, copy) {
    await loadTemplates();
    let t = tid ? tplById(tid) : null;
    if (tid && !t) { toast("Plantilla no encontrada", 3500, "err"); go("#/plantillas"); return; }
    if (!t) {
      t = { name: "", description: "", style: { theme_color: "#1f4e79", page_size: "A4", cover: true, toc: true, cover_photo: true }, fields: [{ key: "proyecto", label: "Proyecto", type: "text", required: true }, { key: "fecha", label: "Fecha", type: "date" }], sections: [] };
      state.tplMode = "new";
    } else {
      t = JSON.parse(JSON.stringify(t));
      if (copy || t.builtin) { delete t.id; t.name = t.name + " (copia)"; state.tplMode = "copy"; }
      else state.tplMode = "edit";
      delete t.builtin;
    }
    t.style = Object.assign({ theme_color: "#1f4e79", page_size: "A4", cover: true, toc: true, cover_photo: true }, t.style || {});
    t.fields = t.fields || []; t.sections = (t.sections || []).map((s) => Object.assign({ id: "", title: "", instructions: "", words: 400, depends_on: [], photos: s.kind === "per_group", layout: "2x3", content: "" }, s));
    state.tpl = t;
    $("#tplHeading").textContent = state.tplMode === "new" ? "Nueva plantilla" : state.tplMode === "copy" ? "Personalizar plantilla" : "Editar plantilla";
    $("#tplIntro").textContent = state.tplMode === "copy" ? "Se guardará como una plantilla tuya; la integrada no cambia." : "Define los campos que se piden al crear el informe y las secciones que lo componen, en orden.";
    $("#tplError").classList.add("hidden");
    $("#tplName").value = t.name; $("#tplDesc").value = t.description || "";
    $("#tplColor").value = /^#[0-9a-f]{6}$/i.test(t.style.theme_color) ? t.style.theme_color : "#1f4e79"; $("#tplColorHex").value = $("#tplColor").value;
    $("#tplPage").value = t.style.page_size === "Letter" ? "Letter" : "A4";
    $("#tplCover").checked = t.style.cover !== false; $("#tplToc").checked = t.style.toc !== false; $("#tplCoverPhoto").checked = t.style.cover_photo !== false;
    $("#tplLook").open = false; renderTplLookSum();
    renderTplFields(); renderTplSections();
  }
  function renderTplFields() {
    const t = state.tpl;
    $("#tplFields").innerHTML = t.fields.map((f, i) => `
      <div class="frow" data-i="${i}">
        <span class="grip" title="Arrastrar">${ico("grip")}</span>
        <input class="input" data-fk="label" value="${esc(f.label)}" placeholder="Etiqueta (ej.: Cliente)" aria-label="Etiqueta del campo ${i + 1}" title="${f.key ? "Clave para textos fijos: {{" + esc(f.key) + "}}" : ""}">
        <input class="input mono hidden" data-fk="key" value="${esc(f.key)}" aria-label="Clave del campo ${i + 1}">
        <span class="select"><select data-fk="type" aria-label="Tipo">${Object.keys(FIELD_TYPES).map((k) => `<option value="${k}" ${f.type === k ? "selected" : ""}>${FIELD_TYPES[k]}</option>`).join("")}</select></span>
        <label class="switch"><input type="checkbox" data-fk="required" ${f.required ? "checked" : ""}><i></i>Obligatorio</label>
        <span class="mv"><button type="button" class="btn btn-ghost" data-fmv="-1" title="Subir" ${i === 0 ? "disabled" : ""}>${ico("up")}</button><button type="button" class="btn btn-ghost" data-fmv="1" title="Bajar" ${i === t.fields.length - 1 ? "disabled" : ""}>${ico("down")}</button><button type="button" class="btn btn-ghost" data-fdel title="Quitar">${ico("trash")}</button></span>
      </div>`).join("") || '<div class="empty-inline">Sin campos. El informe solo pedirá título y notas.</div>';
  }
  $("#tplFields").addEventListener("input", (e) => {
    const t = e.target, row = t.closest(".frow"); if (!row || !t.dataset.fk) return;
    const f = state.tpl.fields[+row.dataset.i];
    if (t.dataset.fk === "required") f.required = t.checked;
    else if (t.dataset.fk === "key") f.key = t.value.toLowerCase().replace(/[^a-z0-9_]/g, "_");
    else f[t.dataset.fk] = t.value;
    if (t.dataset.fk === "label" && (!f.key || f._auto !== false)) { f.key = slug(t.value).replace(/-/g, "_"); f._auto = true; $("[data-fk=key]", row).value = f.key; t.title = f.key ? "Clave para textos fijos: {{" + f.key + "}}" : ""; }
    if (t.dataset.fk === "key") f._auto = false;
    if (t.dataset.fk === "type") f.type = t.value;
  });
  $("#tplFields").addEventListener("change", (e) => { const t = e.target; const row = t.closest(".frow"); if (row && t.dataset.fk === "type") { state.tpl.fields[+row.dataset.i].type = t.value; } });
  $("#tplFields").addEventListener("click", (e) => {
    const b = e.target.closest("button"); if (!b) return;
    const row = b.closest(".frow"); if (!row) return;
    const i = +row.dataset.i, arr = state.tpl.fields;
    if (b.dataset.fmv) { const j = i + (+b.dataset.fmv); if (j < 0 || j >= arr.length) return; const x = arr.splice(i, 1)[0]; arr.splice(j, 0, x); }
    else if (b.hasAttribute("data-fdel")) arr.splice(i, 1);
    renderTplFields(); renderTplSections();
  });
  $("#tplAddField").onclick = () => { state.tpl.fields.push({ key: "", label: "", type: "text", required: false, _auto: true }); renderTplFields(); const last = $$("#tplFields [data-fk=label]").pop(); if (last && !isTouch) last.focus(); };

  function renderTplSections() {
    const t = state.tpl;
    const ids = t.sections.map((s) => s.id).filter(Boolean);
    $("#tplSections").innerHTML = t.sections.map((s, i) => {
      const K = KINDS[s.kind] || KINDS.static, usesAI = ["ai", "per_group", "auto_outline"].indexOf(s.kind) >= 0;
      // visible: tipo, título e instrucciones; lo demás (palabras, fotos, dependencias, disposición, texto fijo) en «Más opciones»
      let body = "";
      if (usesAI) body += `<label class="field span2">Instrucciones para la IA<textarea class="textarea" data-sk="instructions" placeholder="${s.kind === "auto_outline" ? "Cómo debe ser el índice (enfoque, capítulos imprescindibles…)" : "Qué debe cubrir, tono, tablas, cómo citar las fotos…"}">${esc(s.instructions || "")}</textarea></label>`;
      let more = "", sum = [];
      if (s.kind === "ai" || s.kind === "per_group") {
        more += `<label class="field">Extensión (palabras)<input class="input tabular" type="number" min="50" max="5000" step="50" inputmode="numeric" data-sk="words" value="${esc(s.words || 400)}"></label>`;
        more += `<div class="field">Fotos<label class="switch" style="min-height:38px"><input type="checkbox" data-sk="photos" ${s.photos ? "checked" : ""}><i></i>${s.kind === "per_group" ? "Incluir las fotos de cada zona" : "Enviar todas las fotos a la IA"}</label></div>`;
        sum.push("~" + num(s.words || 400) + " palabras", s.photos ? "con fotos" : "sin fotos");
      }
      if (s.kind === "ai") {
        const others = ids.filter((x) => x !== s.id), deps = s.depends_on || [];
        more += `<div class="field span2">Depende de (se redacta después, con sus resúmenes)<div class="deps">
          <span class="chip chip-btn ${deps.indexOf("*") >= 0 ? "on" : ""}" data-dep="*">${ico("layers")}Todas las demás</span>
          ${others.map((id) => { const o = t.sections.find((x) => x.id === id); return `<span class="chip chip-btn ${deps.indexOf(id) >= 0 ? "on" : ""}" data-dep="${esc(id)}">${esc(o && o.title || id)}</span>`; }).join("")}
          ${others.length ? "" : '<span class="xs faint">Añade otras secciones con título para poder elegirlas.</span>'}</div></div>`;
        if (deps.length) sum.push(deps.indexOf("*") >= 0 ? "tras todas" : "depende de " + deps.length);
      }
      if (s.kind === "photo_grid") { more += `<label class="field">Disposición (columnas × filas)<span class="select"><select data-sk="layout">${["1x2", "2x2", "2x3", "3x3", "3x4"].map((l) => `<option ${(s.layout || "2x3") === l ? "selected" : ""}>${l}</option>`).join("")}</select></span></label>`; sum.push("rejilla " + (s.layout || "2x3")); }
      if (s.kind === "static") {
        more += `<label class="field span2">Texto fijo (Markdown)<textarea class="textarea" data-sk="content" placeholder="Ej.: ______________________&#10;**{{inspector}}**&#10;{{registro}}">${esc(s.content || "")}</textarea>
          <span class="inserts">${t.fields.filter((f) => f.key).map((f) => `<span class="chip chip-btn" data-ins="{{${esc(f.key)}}}" title="Insertar ${esc(f.label || f.key)}">{{${esc(f.key)}}}</span>`).join("")}</span></label>`;
        const n = (s.content || "").trim().split("\n").filter(Boolean).length; sum.push(n ? n + (n === 1 ? " línea de texto" : " líneas de texto") : "sin texto todavía");
      }
      if (more) body += `<details class="sopts span2" ${s._open ? "open" : ""} data-sopts><summary><span class="grow">Más opciones</span><span class="xs faint truncate">${esc(sum.join(" · "))}</span>${ico("chevron", "icon-sm fold-chev")}</summary><div class="sopts-body">${more}</div></details>`;
      body += `<div class="hint">${ico("info")}<span>${esc(K.desc)}</span></div>`;
      return `<div class="srow" data-i="${i}" draggable="false">
        <div class="srow-head"><span class="grip" title="Arrastrar para reordenar">${ico("grip")}</span>
          <span class="kind" ${KIND_STYLE(s.kind)}>${ico(K.icon)}${esc(K.label)}</span>
          <input class="input" data-sk="title" value="${esc(s.title)}" placeholder="${s.kind === "auto_outline" ? "Sin título (los capítulos vienen del índice)" : "Título de la sección"}" aria-label="Título de la sección ${i + 1}">
          <span class="mv"><button type="button" class="btn btn-ghost" data-smv="-1" title="Subir" ${i === 0 ? "disabled" : ""}>${ico("up")}</button><button type="button" class="btn btn-ghost" data-smv="1" title="Bajar" ${i === t.sections.length - 1 ? "disabled" : ""}>${ico("down")}</button><button type="button" class="btn btn-ghost" data-sdel title="Quitar sección">${ico("trash")}</button></span></div>
        <div class="srow-body">${body}</div></div>`;
    }).join("") || '<div class="empty-inline">Sin secciones todavía. Pulsa «Sección» para añadir la primera.</div>';
  }
  function ensureSectionId(s) {
    if (s.id || !(s.title || "").trim()) return;
    let base = slug(s.title), id = base, n = 2;
    while (state.tpl.sections.some((x) => x !== s && x.id === id)) id = base + "-" + n++;
    s.id = id;
  }
  $("#tplSections").addEventListener("input", (e) => {
    const t = e.target, row = t.closest(".srow"); if (!row || !t.dataset.sk) return;
    const s = state.tpl.sections[+row.dataset.i], k = t.dataset.sk;
    if (k === "photos") s.photos = t.checked;
    else if (k === "words") s.words = Math.max(50, +t.value || 0);
    else s[k] = t.value;
  });
  $("#tplSections").addEventListener("toggle", (e) => { // recordar qué «Más opciones» están abiertas al repintar
    const d = e.target, row = d.closest && d.closest(".srow"); if (!row || !d.hasAttribute("data-sopts")) return;
    state.tpl.sections[+row.dataset.i]._open = d.open;
  }, true);
  function renderTplLookSum() {
    const parts = [$("#tplPage").value, $("#tplColorHex").value];
    if ($("#tplCover").checked) parts.push("portada" + ($("#tplCoverPhoto").checked ? " con foto" : ""));
    if ($("#tplToc").checked) parts.push("índice");
    $("#tplLookSum").textContent = parts.join(" · ");
  }
  $("#tplLook").addEventListener("input", renderTplLookSum); $("#tplLook").addEventListener("change", renderTplLookSum);
  $("#tplSections").addEventListener("change", (e) => {
    const t = e.target, row = t.closest(".srow"); if (!row || !t.dataset.sk) return;
    const s = state.tpl.sections[+row.dataset.i];
    if (t.dataset.sk === "title") { ensureSectionId(s); renderTplSections(); }
    if (t.dataset.sk === "layout") s.layout = t.value;
  });
  $("#tplSections").addEventListener("click", (e) => {
    const row = e.target.closest(".srow"); if (!row) return;
    const i = +row.dataset.i, arr = state.tpl.sections, s = arr[i];
    const dep = e.target.closest("[data-dep]");
    if (dep) {
      const d = dep.dataset.dep, list = s.depends_on = s.depends_on || [], at = list.indexOf(d);
      if (at >= 0) list.splice(at, 1); else { if (d === "*") list.length = 0; else { const star = list.indexOf("*"); if (star >= 0) list.splice(star, 1); } list.push(d); }
      renderTplSections(); return;
    }
    const ins = e.target.closest("[data-ins]");
    if (ins) {
      const ta = $("[data-sk=content]", row); const st = ta.selectionStart || ta.value.length;
      ta.value = ta.value.slice(0, st) + ins.dataset.ins + ta.value.slice(ta.selectionEnd || st); s.content = ta.value; ta.focus(); return;
    }
    const b = e.target.closest("button"); if (!b) return;
    if (b.dataset.smv) { const j = i + (+b.dataset.smv); if (j < 0 || j >= arr.length) return; const x = arr.splice(i, 1)[0]; arr.splice(j, 0, x); }
    else if (b.hasAttribute("data-sdel")) arr.splice(i, 1);
    renderTplSections();
  });
  // arrastre por el asa (escritorio)
  let gripArmed = null, sDrag = null;
  $("#tplSections").addEventListener("mousedown", (e) => { const g = e.target.closest(".grip"); const row = g && g.closest(".srow"); if (row) { row.setAttribute("draggable", "true"); gripArmed = row; } });
  document.addEventListener("mouseup", () => { if (gripArmed) { gripArmed.setAttribute("draggable", "false"); gripArmed = null; } });
  $("#tplSections").addEventListener("dragstart", (e) => { const row = e.target.closest(".srow"); if (!row || row !== gripArmed) { e.preventDefault(); return; } sDrag = +row.dataset.i; row.classList.add("dragging"); e.dataTransfer.effectAllowed = "move"; e.dataTransfer.setData("text/plain", String(sDrag)); });
  $("#tplSections").addEventListener("dragover", (e) => { if (sDrag == null) return; e.preventDefault(); const row = e.target.closest(".srow"); $$(".srow.over").forEach((x) => x.classList.remove("over")); if (row) row.classList.add("over"); });
  $("#tplSections").addEventListener("dragend", () => { sDrag = null; $$(".srow.dragging, .srow.over").forEach((x) => x.classList.remove("dragging", "over")); });
  $("#tplSections").addEventListener("drop", (e) => {
    const row = e.target.closest(".srow"); if (sDrag == null || !row) return;
    e.preventDefault(); const to = +row.dataset.i, arr = state.tpl.sections;
    if (to !== sDrag) { const x = arr.splice(sDrag, 1)[0]; arr.splice(to, 0, x); renderTplSections(); }
    sDrag = null;
  });
  $("#tplAddSection").onclick = () => {
    $("#kindList").innerHTML = Object.keys(KINDS).map((k) => `<button type="button" class="kind-opt" data-kind="${k}" ${KIND_STYLE(k)}><span class="ki">${ico(KINDS[k].icon)}</span><span><b>${esc(KINDS[k].label)}</b><small>${esc(KINDS[k].desc)}</small></span></button>`).join("");
    openModal("#kindModal");
  };
  $("#kindList").addEventListener("click", (e) => {
    const b = e.target.closest("[data-kind]"); if (!b) return;
    const k = b.dataset.kind;
    const defaults = { ai: { title: "", words: 400 }, per_group: { title: "Hallazgos por zona", words: 400, photos: true }, auto_outline: { title: "", words: 600 },
      fields_table: { title: "Datos generales" }, photo_grid: { title: "Anexo fotográfico", layout: "2x3" }, static: { title: "Firma", content: "" } };
    const s = Object.assign({ id: "", kind: k, title: "", instructions: "", words: 400, depends_on: [], photos: false, layout: "2x3", content: "" }, defaults[k]);
    ensureSectionId(s);
    if (k === "static" || k === "photo_grid") s._open = true; // su contenido principal vive en «Más opciones»
    state.tpl.sections.push(s); closeModal("#kindModal"); renderTplSections();
    const rows = $$("#tplSections .srow"), last = rows[rows.length - 1];
    if (last) { last.scrollIntoView({ block: "center", behavior: "smooth" }); const inp = $("[data-sk=title]", last); if (inp && !isTouch) inp.focus(); }
  });
  $("#tplColor").addEventListener("input", (e) => { $("#tplColorHex").value = e.target.value; });
  $("#tplColorHex").addEventListener("input", (e) => { if (/^#[0-9a-f]{6}$/i.test(e.target.value)) $("#tplColor").value = e.target.value; });
  $("#tplForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const t = state.tpl; if (!t) return;
    t.sections.forEach(ensureSectionId);
    const body = {
      name: $("#tplName").value.trim(), description: $("#tplDesc").value.trim(),
      style: { theme_color: /^#[0-9a-f]{6}$/i.test($("#tplColorHex").value) ? $("#tplColorHex").value : "#1f4e79", page_size: $("#tplPage").value, cover: $("#tplCover").checked, toc: $("#tplToc").checked, cover_photo: $("#tplCoverPhoto").checked },
      fields: t.fields.filter((f) => f.key || f.label).map((f) => ({ key: f.key || slug(f.label).replace(/-/g, "_"), label: f.label || f.key, type: f.type || "text", required: !!f.required })),
      sections: t.sections.map((s) => {
        const o = { id: s.id || undefined, title: s.title || "", kind: s.kind };
        if (["ai", "per_group", "auto_outline"].indexOf(s.kind) >= 0) o.instructions = s.instructions || "";
        if (s.kind === "ai" || s.kind === "per_group") { o.words = +s.words || 400; o.photos = !!s.photos; }
        if (s.kind === "ai") o.depends_on = s.depends_on || [];
        if (s.kind === "photo_grid") o.layout = s.layout || "2x3";
        if (s.kind === "static") o.content = s.content || "";
        return o;
      }),
    };
    if (t.id) body.id = t.id;
    const err = $("#tplError");
    const problems = [];
    if (!body.name) problems.push("La plantilla necesita un nombre.");
    if (!body.sections.length) problems.push("Añade al menos una sección.");
    const keys = body.fields.map((f) => f.key); if (new Set(keys).size !== keys.length) problems.push("Hay claves de campo repetidas.");
    if (body.sections.some((s) => s.kind !== "auto_outline" && !s.title)) problems.push("Todas las secciones (salvo el índice automático) necesitan título.");
    if (problems.length) { err.innerHTML = ico("alert") + "<div>" + problems.map(esc).join("<br>") + "</div>"; err.classList.remove("hidden"); err.scrollIntoView({ block: "center", behavior: "smooth" }); return; }
    $("#tplSave").disabled = true;
    const j = await api("/api/report-templates", body);
    $("#tplSave").disabled = false;
    if (!j.ok) { err.innerHTML = ico("alert") + `<div><b>No se pudo guardar.</b> ${esc(j.error || "Error desconocido")}</div>`; err.classList.remove("hidden"); err.scrollIntoView({ block: "center", behavior: "smooth" }); toast("Revisa los errores de la plantilla", 3000, "err"); return; }
    err.classList.add("hidden");
    toast("Plantilla guardada", 2200, "ok");
    await loadTemplates(true);
    go("#/plantillas");
  });

  // ---------------------------------------------------------------- eventos globales
  document.addEventListener("click", async (e) => {
    const t = e.target;
    if (t.closest("[data-stop]")) { e.stopPropagation(); return; }
    const close = t.closest("[data-close]"); if (close) { closeModal(close.dataset.close); return; }
    const goEl = t.closest("[data-go]"); if (goEl) { go(goEl.dataset.go); return; }
    const th = t.closest("#themeSeg [data-theme]"); if (th) { applyTheme(th.dataset.theme); return; }
    const delR = t.closest("[data-del-report]");
    if (delR) {
      e.stopPropagation();
      const r = (state.reports || []).find((x) => x.id === delR.dataset.delReport);
      if (await askConfirm("¿Borrar este informe?", "«" + (r ? r.title : "") + "» y sus secciones redactadas se eliminarán de forma permanente.")) {
        await apiDel("/api/reports/" + encodeURIComponent(delR.dataset.delReport)); toast("Informe borrado", 2000, "ok"); loadReports();
      }
      return;
    }
    const openR = t.closest("[data-open-report]"); if (openR) { go("#/informe/" + encodeURIComponent(openR.dataset.openReport)); return; }
    const use = t.closest("[data-use-tpl]"); if (use) { go("#/nuevo/" + encodeURIComponent(use.dataset.useTpl)); return; }
    const dup = t.closest("[data-dup-tpl]"); if (dup) { go("#/plantilla/" + encodeURIComponent(dup.dataset.dupTpl) + "/copiar"); return; }
    const ed = t.closest("[data-edit-tpl]"); if (ed) { go("#/plantilla/" + encodeURIComponent(ed.dataset.editTpl)); return; }
    const delT = t.closest("[data-del-tpl]");
    if (delT) {
      const tp = tplById(delT.dataset.delTpl);
      if (await askConfirm("¿Borrar esta plantilla?", "«" + (tp ? tp.name : "") + "» se eliminará. Los informes ya creados con ella no se ven afectados.")) {
        await apiDel("/api/report-templates/" + encodeURIComponent(delT.dataset.delTpl)); toast("Plantilla borrada", 2000, "ok"); loadTemplates(true);
      }
      return;
    }
    const pick = t.closest("[data-pick-tpl]"); if (pick) { state.wiz.tpl = tplById(pick.dataset.pickTpl); renderWizard(); return; }
    const unit = t.closest("[data-unit]"); if (unit) { openSection(unit.dataset.unit); return; }
    const etab = t.closest("[data-etab]"); if (etab) { document.body.dataset.etab = etab.dataset.etab; $$(".ed-tabs [data-etab]").forEach((b) => b.classList.toggle("on", b.dataset.etab === etab.dataset.etab)); return; }
    const modal = t.classList.contains("modal") ? t : null; if (modal && modal.id !== "confirm") closeModal(modal);
  });
  document.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    if (e.key === "Enter" && e.target.matches("[role=button]")) { e.preventDefault(); e.target.click(); }
    if (e.key === "Escape") {
      if ($("#ctxMenu")) { hideMenu(); return; }
      const m = $$(".modal:not(.hidden)").pop();
      if (m) { if (m.id === "confirm") $("#confirmNo").click(); else closeModal(m); return; }
      if (state.unit) { closeSection(); return; }
      if (e.target.matches("input, textarea")) e.target.blur();
      return;
    }
    const mod = (isMac ? e.metaKey : e.ctrlKey) && !e.altKey;
    if (mod && e.key === "s" && state.unit && !$("#secSave").disabled) { e.preventDefault(); $("#secSave").click(); return; }
    if ((mod || e.altKey) && !e.shiftKey && (e.key === "n" || e.key === "N")) { e.preventDefault(); go("#/nuevo"); return; }
    if (mod && e.key === "Enter" && document.body.dataset.screen === "new" && !$("#wizStep2").classList.contains("hidden")) { e.preventDefault(); $("#wizStep2").requestSubmit(); return; }
    if (e.altKey && !mod && /^[1-4]$/.test(e.key)) {
      e.preventDefault();
      if (e.key === "1") location.href = "/"; else if (e.key === "2") location.href = "/?view=apps"; else if (e.key === "3") go("#/"); else go("#/plantillas");
    }
  });
  const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform) || /Mac/.test(navigator.userAgent);
  $$(".mod-key").forEach((el) => { el.textContent = isMac ? "⌘" : "Ctrl"; });
  $("#newReportBtn").onclick = () => go("#/nuevo");
  $("#navTheme").onclick = () => { const cur = localGet("theme") || "system"; applyTheme(cur === "system" ? "dark" : cur === "dark" ? "light" : "system"); toast("Tema: " + ({ system: "sistema", dark: "oscuro", light: "claro" }[localGet("theme") || "system"]), 1500); };
  $$(".ed-tabs [data-etab]").forEach((b) => b.classList.toggle("on", b.dataset.etab === document.body.dataset.etab));
  new MutationObserver(() => { const cur = document.body.dataset.etab; $$(".ed-tabs [data-etab]").forEach((b) => b.classList.toggle("on", b.dataset.etab === cur)); })
    .observe(document.body, { attributes: true, attributeFilter: ["data-etab"] });

  // ---------------------------------------------------------------- inicio
  (async () => {
    try {
      const st = await api("/api/status");
      state.status = st; state.lastSeq = st.seq || 0; state.maxPx = st.upload_max_px || 3200;
      $("#wsInfo").textContent = st.workspace + " · v" + st.version; $("#wsInfo").title = "Workspace: " + st.workspace;
    } catch (e) { toast("No se pudo contactar con el servidor", 5000, "err"); }
    connect();
    loadReports(); loadTemplates();
    route();
  })();
})();
