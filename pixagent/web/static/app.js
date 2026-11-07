/* PixAgent — cliente web (Windows, macOS, Android, iOS, iPadOS).
   Sin frameworks ni dependencias: ~20 KB, arranca rápido incluso en móviles modestos. */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const isTouch = matchMedia("(pointer: coarse)").matches;
  const isMobile = () => matchMedia("(max-width: 820px)").matches;
  const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const state = {
    session: null, pending: [], ws: null, running: false, current: null, lastSeq: 0,
    streamEl: null, streamText: "", rafPending: false, retry: 0, maxPx: 3200,
    saveData: (navigator.connection && navigator.connection.saveData) || localGet("saveData") === "1",
  };

  const TEMPLATES = {
    plan: "Te adjunto un plano y varias fotos. Ubica cada foto en el punto del plano donde se tomó, con flechas, números y conos de visión; añade leyenda y cajetín. Título: ",
    diagram: "Crea un diagrama de flujo de este proceso: ",
    report: "Genera un informe PDF profesional con portada e índice sobre: ",
    app: "Crea una mini app (HTML) que sirva para: ",
    python: "Escribe y ejecuta un script de Python que: ",
  };

  // ---------------------------------------------------------------- utilidades
  function localGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function localSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = (rel) => rel.split("/").map(encodeURIComponent).join("/");
  const fileUrl = (rel) => "/files/" + enc(rel);
  const thumbUrl = (rel, cssW, page) => {
    const dpr = Math.min(window.devicePixelRatio || 1, state.saveData ? 1 : 2);
    return `/thumb/${enc(rel)}?w=${Math.round(cssW * dpr)}${page != null ? "&page=" + page : ""}`;
  };
  const kindOf = (p) => {
    const e = p.toLowerCase().split(".").pop();
    if (["png", "jpg", "jpeg", "webp", "gif", "bmp", "svg", "heic", "heif"].indexOf(e) >= 0) return "image";
    if (e === "pdf") return "pdf";
    if (e === "html" || e === "htm") return "html";
    return "text";
  };
  const icon = (k) => ({ image: "🖼️", pdf: "📄", html: "🧩", text: "📝" }[k] || "📁");
  const imgTag = (rel, w, extra) => kindOf(rel) === "image" && !/\.svg$/i.test(rel)
    ? `<img loading="lazy" decoding="async" src="${thumbUrl(rel, w)}" data-open="${esc(rel)}" ${extra || ""}>`
    : `<img loading="lazy" decoding="async" src="${fileUrl(rel)}" data-open="${esc(rel)}" ${extra || ""}>`;
  function toast(msg, ms) {
    const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), ms || 2600);
  }
  const api = (url, body) => fetch(url, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  }).then((r) => r.json());

  // Markdown mínimo y seguro (sin lookbehind: compatible con iOS antiguos)
  const FILE_RX = /(^|[\s(>"'«“])((?:plans|diagrams|reports|apps|outputs|uploads|inbox)\/[\w\-./() ]+?\.(?:png|jpe?g|pdf|html|svg|py|json|md|csv|xlsx|docx))(?=$|[\s)<,.;:"'»”])/g;
  function md(src) {
    const blocks = [];
    let s = esc(src).replace(/```(\w*)\n([\s\S]*?)```/g, (_, l, c) => { blocks.push("<pre><code>" + c + "</code></pre>"); return "\u0000" + (blocks.length - 1) + "\u0000"; });
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(^|[\s(])\*(\S(?:.*?\S)?)\*(?=[\s).,;:!?]|$)/g, "$1<i>$2</i>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    const out = []; let list = null;
    s.split("\n").forEach((line) => {
      const h = line.match(/^(#{1,4})\s+(.*)/);
      const li = line.match(/^\s*(?:[-*]|\d+[.)])\s+(.*)/);
      if (li) { (list = list || []).push("<li>" + li[1] + "</li>"); return; }
      if (list) { out.push("<ul>" + list.join("") + "</ul>"); list = null; }
      if (h) out.push("<p><b>" + h[2] + "</b></p>");
      else if (line.trim()) out.push("<p>" + line + "</p>");
    });
    if (list) out.push("<ul>" + list.join("") + "</ul>");
    return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[i])
      .replace(FILE_RX, (m, pre, f) => pre + `<button class="filechip" data-open="${f}">${icon(kindOf(f))} ${f}</button>`);
  }

  // ---------------------------------------------------------------- conexión (con reanudación)
  function connect() {
    if (state.ws && state.ws.readyState <= 1) return;
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    state.ws = ws;
    ws.onopen = () => { state.retry = 0; ws.send(JSON.stringify({ type: "hello", after: state.lastSeq })); $("#conn").classList.add("on"); };
    ws.onmessage = (m) => {
      const ev = JSON.parse(m.data);
      if (ev.seq) { if (ev.seq <= state.lastSeq) return; state.lastSeq = ev.seq; }
      handle(ev);
    };
    ws.onclose = (e) => {
      $("#conn").classList.remove("on");
      if (e.code === 4401) { location.reload(); return; }
      if (document.visibilityState === "visible") setTimeout(connect, Math.min(10000, 800 * Math.pow(1.6, state.retry++)));
    };
  }
  const send = (o) => { if (state.ws && state.ws.readyState === 1) { state.ws.send(JSON.stringify(o)); return true; } return false; };
  // iOS/Android suspenden las pestañas en segundo plano: al volver, reconectar y recuperar eventos
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") connect(); });
  window.addEventListener("online", connect);
  setInterval(() => { if (document.visibilityState === "visible") send({ type: "ping" }); }, 25000);

  function handle(ev) {
    switch (ev.type) {
      case "inbox": ev.files.forEach(addPending); toast("📥 Recibido: " + ev.files.length + " archivo(s)"); refreshLibrary(); return;
      case "approval_request": askApproval(ev); return;
      case "approval_resolved": if ($("#approval").dataset.id === ev.id) $("#approval").classList.add("hidden"); return;
      case "pong": case "hello_ok": return;
    }
    if (ev.session && state.session && ev.session !== state.session) return;
    switch (ev.type) {
      case "session":
        if (!state.session && ev.client === clientId) { state.session = ev.session; loadSessions(); }
        break;
      case "turn_start": setStatus("Pensando…"); state.streamEl = null; state.streamText = ""; break;
      case "text_delta":
        if (!state.streamEl) state.streamEl = addMsg("assistant", "");
        state.streamText += ev.text; scheduleRender(); break;
      case "thinking_delta": setStatus("💭 " + ev.text.slice(-160)); break;
      case "assistant": renderStream(); state.streamEl = null; state.streamText = ""; break;
      case "status": setStatus(ev.text); break;
      case "tool_preparing": setStatus("Preparando " + ev.name + "…"); break;
      case "tool_start": addTool(ev); setStatus("Ejecutando " + ev.name + "…"); break;
      case "tool_end": finishTool(ev, true); break;
      case "todos": renderTodos(ev.todos); break;
      case "error": addMsg("error", esc(ev.text)); break;
      case "done":
        renderStream(); setRunning(false); loadSessions(); refreshLibrary();
        if (ev.usage) $("#usage").textContent = "Tokens: " + ev.usage.input.toLocaleString() + " entrada (" + ev.usage.cache_read.toLocaleString() + " caché) · " + ev.usage.output.toLocaleString() + " salida";
        break;
    }
  }
  // Repintar como mucho una vez por fotograma (los móviles modestos lo agradecen)
  function scheduleRender() {
    if (state.rafPending) return;
    state.rafPending = true;
    requestAnimationFrame(() => { state.rafPending = false; renderStream(); });
  }
  function renderStream() { if (state.streamEl) { state.streamEl.innerHTML = md(state.streamText); scroll(); } }

  // ---------------------------------------------------------------- mensajes
  function clearWelcome() { const w = $(".welcome"); if (w) w.remove(); }
  function scroll() {
    const m = $("#messages");
    if (m.scrollHeight - m.scrollTop - m.clientHeight < 400) m.scrollTop = m.scrollHeight;
  }
  function trimDom() { // limitar nodos en sesiones largas
    const m = $("#messages");
    while (m.children.length > 260) m.removeChild(m.firstChild);
  }
  function addMsg(role, html) {
    clearWelcome();
    const d = document.createElement("div"); d.className = "msg " + role; d.innerHTML = html;
    $("#messages").appendChild(d); trimDom(); scroll(); return d;
  }
  function addUser(text, atts) {
    const d = addMsg("user", md(text || ""));
    if (atts && atts.length) {
      const a = document.createElement("div"); a.className = "atts";
      a.innerHTML = atts.map((f) => kindOf(f) === "image" ? imgTag(f, 64) : `<button class="filechip" data-open="${esc(f)}">${icon(kindOf(f))} ${esc(f.split("/").pop())}</button>`).join("");
      d.appendChild(a);
    }
    $("#messages").scrollTop = $("#messages").scrollHeight;
  }
  const tools = {};
  function addTool(ev) {
    clearWelcome();
    const d = document.createElement("details"); d.className = "tool";
    const i = ev.input || {};
    const hint = i.output || i.path || i.target || i.name || i.command || i.action || "";
    d.innerHTML = `<summary><span class="spinner"></span><span class="name">${esc(ev.name)}</span><span class="muted small hint">${esc(hint)}</span><span class="badge">en curso</span></summary><div class="body"></div>`;
    d._input = ev.input;
    d.addEventListener("toggle", () => { // contenido pesado solo al abrir
      if (d.open && !d._filled) {
        d._filled = true;
        d.querySelector(".body").insertAdjacentHTML("afterbegin", d._input && Object.keys(d._input).length ? `<div class="small muted">Entrada</div><pre>${esc(JSON.stringify(d._input, null, 2))}</pre>` : "");
      }
    });
    $("#messages").appendChild(d); tools[ev.id] = d; trimDom(); scroll();
  }
  const SHOW_TOOLS = ["compose_plan", "render_diagram", "create_pdf", "create_miniapp", "html_to_pdf", "image_tools"];
  function finishTool(ev, live) {
    let d = tools[ev.id];
    if (!d) { addTool({ id: ev.id, name: ev.name, input: {} }); d = tools[ev.id]; }
    const sp = d.querySelector(".spinner"); if (sp) sp.remove();
    d.classList.toggle("err", !!ev.is_error);
    d.querySelector(".badge").textContent = (ev.is_error ? "error · " : "✓ ") + (ev.seconds != null ? ev.seconds + "s" : "");
    const imgs = ev.images || [];
    const files = (ev.files || []).filter((f) => f.indexOf(".tmp/") !== 0);
    d.querySelector(".body").insertAdjacentHTML("beforeend", `<div class="small muted">Resultado</div><pre>${esc(ev.text)}</pre>` +
      (files.length ? `<div class="atts">${files.map((f) => `<button class="filechip" data-open="${esc(f)}">${icon(kindOf(f))} ${esc(f)}</button>`).join("")}</div>` : ""));
    if (imgs.length) { // miniaturas visibles aunque la tarjeta esté cerrada
      d.insertAdjacentHTML("afterend", `<div class="thumbs tool-thumbs">${imgs.slice(0, 4).map((f) => imgTag(f, 160)).join("")}</div>`);
    }
    const main = ev.name === "create_miniapp" ? files.find((f) => /index\.html$/.test(f)) || files[0]
      : files.find((f) => /\.(png|jpe?g|pdf|html)$/i.test(f) && !/\.preview\.png$/.test(f));
    if (!live && main && !ev.is_error && SHOW_TOOLS.indexOf(ev.name) >= 0) state.lastDeliverable = main;
    if (live && main && !ev.is_error && SHOW_TOOLS.indexOf(ev.name) >= 0) {
      if (isMobile()) { state.current = main; $("#viewBadge").classList.remove("hidden"); openFile(main, true); }
      else openFile(main);
    }
    scroll();
  }
  function renderTodos(todos) {
    const t = $("#todos");
    if (!todos || !todos.length) { t.classList.add("hidden"); return; }
    t.classList.remove("hidden");
    t.innerHTML = "<b>Plan</b>" + todos.map((x) => `<div class="${x.status === "completed" ? "done" : x.status === "in_progress" ? "prog" : ""}">${x.status === "completed" ? "☑" : x.status === "in_progress" ? "▶" : "☐"} ${esc(x.content)}</div>`).join("");
  }
  function setStatus(text) { $("#statusText").textContent = text; }
  function setRunning(on) { state.running = on; $("#statusLine").classList.toggle("hidden", !on); $("#sendBtn").disabled = on; }

  // ---------------------------------------------------------------- adjuntos (reducidos en el dispositivo)
  function addPending(rel) { if (state.pending.indexOf(rel) < 0) { state.pending.push(rel); renderPending(); } }
  function renderPending(extra) {
    $("#pending").innerHTML = state.pending.map((f, i) => `<div class="pend">${kindOf(f) === "image" ? imgTag(f, 44) : icon(kindOf(f))}<span title="${esc(f)}">${esc(f.split("/").pop())}</span><button type="button" data-rm="${i}" aria-label="Quitar">✕</button></div>`).join("") + (extra || "");
  }
  async function shrinkImage(file) {
    // Fotos de móviles (12–48 MP, HEIC): se reducen y convierten a JPEG antes de subir.
    if (!/^image\/(jpeg|png|webp|heic|heif)$/i.test(file.type) && !/\.(heic|heif)$/i.test(file.name)) return file;
    const max = state.saveData ? Math.min(2000, state.maxPx) : state.maxPx;
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
    c.width = c.height = 0; // liberar memoria del canvas (importante en iOS)
    if (!blob || blob.size >= file.size) return file;
    return new File([blob], file.name.replace(/\.(heic|heif|png|webp)$/i, keepPng ? ".png" : ".jpg"), { type: blob.type });
  }
  async function uploadFiles(list) {
    const files = Array.from(list || []);
    if (!files.length) return;
    renderPending(`<div class="pend"><span class="prog" id="upProg">Preparando ${files.length}…</span></div>`);
    const fd = new FormData();
    for (let i = 0; i < files.length; i++) {
      const f = await shrinkImage(files[i]);
      fd.append("files", f, f.name || ("pegado_" + Date.now() + "_" + i + ".png"));
    }
    await new Promise((resolve) => {
      const x = new XMLHttpRequest(); x.open("POST", "/api/upload");
      x.upload.onprogress = (e) => { const p = $("#upProg"); if (p && e.lengthComputable) p.textContent = "Subiendo " + Math.round(e.loaded / e.total * 100) + "%"; };
      x.onload = () => { try { JSON.parse(x.responseText).files.forEach(addPending); } catch (e) { toast("Error al subir"); } renderPending(); resolve(); };
      x.onerror = () => { toast("Error de red al subir"); renderPending(); resolve(); };
      x.send(fd);
    });
  }

  // ---------------------------------------------------------------- visor
  function openFile(rel, quiet) {
    state.current = rel;
    const k = kindOf(rel), url = fileUrl(rel), body = $("#viewerBody");
    body.className = "";
    $("#viewerActions").classList.remove("hidden");
    $("#viewerName").textContent = rel;
    $("#openBtn").href = url;
    if (k === "image") {
      body.innerHTML = `<img id="viewImg" decoding="async" src="${thumbUrl(rel, Math.min(1600, body.clientWidth || 800))}" data-full="${url}">`;
    } else if (k === "pdf") {
      if (isTouch || isIOS) { // iOS/iPadOS solo muestran la 1.ª página en iframes: páginas como imágenes
        body.innerHTML = '<div class="pdfpages">Cargando…</div>';
        api("/api/pdfinfo/" + enc(rel)).then((j) => {
          const n = Math.min(j.pages || 0, 60);
          body.innerHTML = n ? '<div class="pdfpages">' + Array.from({ length: n }, (_, i) => `<img loading="lazy" decoding="async" src="${thumbUrl(rel, Math.min(900, body.clientWidth || 600), i)}" alt="Página ${i + 1}">`).join("") + "</div>"
            : `<iframe src="${url}"></iframe>`;
        });
      } else body.innerHTML = `<iframe src="${url}"></iframe>`;
    } else if (k === "html") body.innerHTML = `<iframe src="${url}" sandbox="allow-scripts allow-forms allow-modals allow-downloads allow-popups"></iframe>`;
    else fetch(url).then((r) => r.text()).then((t) => { body.innerHTML = `<pre>${esc(t.slice(0, 200000))}</pre>`; });
    if (!quiet) { switchTab("view"); if (isMobile()) setPane("viewer"); }
  }
  function switchTab(name) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $("#tab-view").classList.toggle("hidden", name !== "view");
    $("#tab-library").classList.toggle("hidden", name !== "library");
    if (name === "library") refreshLibrary();
  }
  function setPane(p) {
    document.body.dataset.pane = p;
    $$("#bottomNav button").forEach((b) => b.classList.toggle("active", b.dataset.pane === p));
    if (p === "viewer") $("#viewBadge").classList.add("hidden");
    if (p === "library") refreshLibrary();
  }
  let libTimer = null;
  function refreshLibrary() { // con antirrebote: una sola petición aunque lleguen varios eventos
    clearTimeout(libTimer);
    libTimer = setTimeout(async () => {
      if (isMobile() && document.body.dataset.pane !== "library") return;
      const items = await api("/api/library?limit=" + (state.saveData ? 80 : 200));
      const groups = {};
      items.forEach((it) => { (groups[it.folder] = groups[it.folder] || []).push(it); });
      const names = { plans: "Planos", diagrams: "Diagramas", reports: "Informes", apps: "Mini apps", outputs: "Otros", inbox: "Recibidos (PixPin / compartir)", uploads: "Subidos" };
      $("#library").innerHTML = Object.keys(names).filter((g) => groups[g]).map((g) =>
        `<div class="libgroup">${names[g]}</div>` + groups[g].slice(0, 60).map((it) =>
          `<div class="libitem" data-open="${esc(it.path)}"><div class="th">${it.kind === "image" ? imgTag(it.path, 140) : it.kind === "pdf" ? `<img loading="lazy" decoding="async" src="${thumbUrl(it.path, 140, 0)}" onerror="this.replaceWith('📄')">` : icon(it.kind)}</div><div class="nm" title="${esc(it.path)}">${esc(it.path.split("/").slice(-2).join("/"))}</div></div>`).join("")).join("")
        || '<div class="muted">Aún no hay archivos.</div>';
    }, 250);
  }

  // ---------------------------------------------------------------- sesiones
  async function loadSessions() {
    const list = await api("/api/sessions");
    $("#sessions").innerHTML = list.map((s) => `<li data-sid="${esc(s.id)}" class="${s.id === state.session ? "active" : ""}"><span>${esc(s.title)}</span><span class="del" data-del="${esc(s.id)}" aria-label="Borrar">✕</span></li>`).join("");
    const cur = list.find((s) => s.id === state.session);
    $("#sessionTitle").textContent = cur ? cur.title : "Nueva sesión";
  }
  async function openSession(sid) {
    const d = await api("/api/sessions/" + sid + "?limit=" + (state.saveData ? 60 : 160));
    state.session = sid; state.lastDeliverable = null; $("#messages").innerHTML = d.truncated ? '<div class="msg status muted small">… mensajes anteriores ocultos</div>' : "";
    d.transcript.forEach((ev) => {
      if (ev.type === "user") addUser(ev.text, ev.attachments);
      else if (ev.type === "assistant") addMsg("assistant", md(ev.text));
      else if (ev.type === "tool_end") { addTool({ id: ev.id, name: ev.name, input: {} }); finishTool(ev, false); }
      else if (ev.type === "error") addMsg("error", esc(ev.text));
    });
    renderTodos(d.todos); setRunning(!!d.running); loadSessions();
    if (state.lastDeliverable) openFile(state.lastDeliverable, true); // último resultado en el visor
    if (isMobile()) setPane("chat");
  }
  function newSession() {
    state.session = null;
    $("#messages").innerHTML = '<div class="welcome"><h2>Nueva sesión</h2><p>Adjunta archivos o describe la tarea.</p></div>';
    renderTodos([]); loadSessions(); if (isMobile()) setPane("chat");
  }

  // ---------------------------------------------------------------- aprobación
  function askApproval(ev) {
    const m = $("#approval"); m.dataset.id = ev.id;
    $("#approvalName").textContent = "Herramienta: " + ev.name;
    $("#approvalBody").textContent = ev.summary;
    m.classList.remove("hidden");
    const done = (ok) => { send({ type: "approve", id: ev.id, ok: ok }); m.classList.add("hidden"); };
    $("#allowBtn").onclick = () => done(true); $("#denyBtn").onclick = () => done(false);
    if (navigator.vibrate) navigator.vibrate(60);
  }

  // ---------------------------------------------------------------- eventos de la interfaz
  const clientId = Math.random().toString(36).slice(2);
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#input").value.trim();
    if (!text && !state.pending.length) return;
    if (state.running) { toast("El agente está trabajando…"); return; }
    if (!send({ type: "chat", session: state.session, text: text, attachments: state.pending, client: clientId })) { toast("Sin conexión; reintentando…"); connect(); return; }
    addUser(text, state.pending);
    state.pending = []; renderPending(); $("#input").value = ""; $("#input").style.height = ""; setRunning(true); setStatus("Enviando…");
    if (isTouch) $("#input").blur(); // cerrar el teclado para ver la respuesta
  });
  $("#input").addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey && !isTouch && !e.isComposing) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  $("#input").addEventListener("input", (e) => { e.target.style.height = "auto"; e.target.style.height = Math.min(180, e.target.scrollHeight) + "px"; });
  $("#fileInput").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });
  $("#camInput").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });
  document.addEventListener("paste", (e) => {
    const files = Array.from((e.clipboardData && e.clipboardData.files) || []);
    if (files.length) { e.preventDefault(); uploadFiles(files); toast("Imagen pegada"); }
  });
  const chat = $("#chat");
  chat.addEventListener("dragover", (e) => { e.preventDefault(); $("#dropHint").classList.remove("hidden"); });
  chat.addEventListener("dragleave", (e) => { if (!chat.contains(e.relatedTarget)) $("#dropHint").classList.add("hidden"); });
  chat.addEventListener("drop", (e) => { e.preventDefault(); $("#dropHint").classList.add("hidden"); uploadFiles(e.dataTransfer.files); });

  document.addEventListener("click", async (e) => {
    const t = e.target;
    const o = t.closest("[data-open]"); if (o && !t.closest("#viewerBody")) { openFile(o.dataset.open); return; }
    const rm = t.closest("[data-rm]"); if (rm) { state.pending.splice(+rm.dataset.rm, 1); renderPending(); return; }
    const del = t.closest("[data-del]");
    if (del) { e.stopPropagation(); if (confirm("¿Borrar esta sesión?")) { await fetch("/api/sessions/" + del.dataset.del, { method: "DELETE" }); if (state.session === del.dataset.del) newSession(); loadSessions(); } return; }
    const li = t.closest("[data-sid]"); if (li) { openSession(li.dataset.sid); return; }
    const tpl = t.closest("[data-tpl]"); if (tpl) { $("#input").value = TEMPLATES[tpl.dataset.tpl]; $("#input").focus(); return; }
    const nav = t.closest("#bottomNav button"); if (nav) { setPane(nav.dataset.pane); return; }
    const cap = t.closest("[data-capture]");
    if (cap) {
      toast("Pidiendo captura a PixPin…");
      const j = await api("/api/pixpin/capture", { region: cap.dataset.capture });
      if (j.ok) { addPending(j.file); toast("Captura añadida"); if (isMobile()) setPane("chat"); } else toast(j.error, 5000);
      return;
    }
    const tab = t.closest(".tab"); if (tab) switchTab(tab.dataset.tab);
  });
  $("#viewerBody").addEventListener("click", (e) => {
    const im = e.target;
    if (im.id !== "viewImg") return;
    if (!im.classList.contains("zoom") && im.dataset.full && im.src.indexOf("/thumb/") >= 0) im.src = im.dataset.full; // original solo al ampliar
    im.classList.toggle("zoom");
  });
  $("#newSession").onclick = newSession;
  $("#cancelBtn").onclick = () => send({ type: "cancel", session: state.session });
  $("#attachBtn").onclick = () => { if (state.current) { addPending(state.current); toast("Añadido como adjunto"); if (isMobile()) setPane("chat"); } };
  $("#pinBtn").onclick = async () => {
    if (!state.current) return;
    const j = await api("/api/pixpin/pin", { files: [state.current], session: state.session });
    toast(j.ok ? "📌 Fijado en PixPin" : j.error, j.ok ? 2000 : 6000);
  };
  // Compartir con la hoja nativa (iOS, iPadOS, Android, macOS Safari, Windows Edge)
  if (navigator.share) {
    $("#shareBtn").classList.remove("hidden");
    $("#shareBtn").onclick = async () => {
      if (!state.current) return;
      try {
        const blob = await (await fetch(fileUrl(state.current))).blob();
        const file = new File([blob], state.current.split("/").pop(), { type: blob.type });
        if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file], title: file.name });
        else await navigator.share({ title: file.name, url: location.origin + fileUrl(state.current) });
      } catch (err) { if (err.name !== "AbortError") toast("No se pudo compartir"); }
    };
  }
  $("#installScripts").onclick = async () => { await api("/api/pixpin/install", {}); toast("Scripts generados en pixpin_scripts/ (ver LEEME.txt)", 5000); refreshLibrary(); };
  $("#effort").onchange = (e) => api("/api/settings", { effort: e.target.value });
  $("#perm").onchange = (e) => api("/api/settings", { permission_mode: e.target.value });
  $("#saveData").checked = state.saveData;
  $("#saveData").onchange = (e) => { state.saveData = e.target.checked; localSet("saveData", e.target.checked ? "1" : "0"); refreshLibrary(); };

  // Instalación como app (PWA)
  let deferredInstall = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredInstall = e; $("#installApp").classList.remove("hidden"); });
  $("#installApp").onclick = async () => {
    if (deferredInstall) { deferredInstall.prompt(); deferredInstall = null; $("#installApp").classList.add("hidden"); }
    else if (isIOS) toast("En Safari: Compartir ⬆️ → «Añadir a pantalla de inicio»", 6000);
  };
  if (isIOS && !navigator.standalone) $("#installApp").classList.remove("hidden");
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});

  // ---------------------------------------------------------------- inicio
  (async () => {
    const st = await api("/api/status");
    state.lastSeq = st.seq; state.maxPx = st.upload_max_px || 3200;
    $("#effort").value = st.effort; $("#perm").value = st.permission_mode;
    $("#pixpinStatus").innerHTML = st.pixpin ? '<span class="ok">● PixPin conectado' + (st.is_host ? "" : " (en el equipo anfitrión)") + "</span>"
      : '<span class="bad">● PixPin no disponible</span>' + (st.is_host ? " (configura pixpin_path)" : " en el anfitrión");
    if (!st.pixpin) { $("#pixpinButtons").querySelectorAll("[data-capture]").forEach((b) => b.classList.add("hidden")); $("#pinBtn").classList.add("hidden"); }
    $("#wsInfo").textContent = "Workspace: " + st.workspace + " · v" + st.version;
    connect(); loadSessions(); if (!isMobile()) refreshLibrary();
    if (/[?&]shared=1/.test(location.search)) { history.replaceState(null, "", "/"); toast("📥 Archivos compartidos recibidos"); }
  })();
})();
