/* PixAgent — interfaz web */
(() => {
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => [...document.querySelectorAll(s)];
  const state = { session: null, pending: [], ws: null, running: false, current: null, streamEl: null, streamText: "" };

  const TEMPLATES = {
    plan: "Te adjunto un plano y varias fotos. Ubica cada foto en el punto del plano donde se tomó, con flechas, números y conos de visión; añade leyenda y cajetín. Título: ",
    diagram: "Crea un diagrama de flujo de este proceso: ",
    report: "Genera un informe PDF profesional con portada e índice sobre: ",
    app: "Crea una mini app (HTML) que sirva para: ",
    python: "Escribe y ejecuta un script de Python que: ",
  };

  // ---------------------------------------------------------------- utilidades
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const fileUrl = (rel) => "/files/" + rel.split("/").map(encodeURIComponent).join("/");
  const kindOf = (p) => {
    const e = p.toLowerCase().split(".").pop();
    if (["png", "jpg", "jpeg", "webp", "gif", "bmp", "svg"].includes(e)) return "image";
    if (e === "pdf") return "pdf";
    if (["html", "htm"].includes(e)) return "html";
    return "text";
  };
  const icon = (k) => ({ image: "🖼️", pdf: "📄", html: "🧩", text: "📝" }[k] || "📁");
  function toast(msg, ms = 2600) {
    const t = $("#toast"); t.textContent = msg; t.classList.remove("hidden");
    clearTimeout(t._h); t._h = setTimeout(() => t.classList.add("hidden"), ms);
  }

  function md(src) {
    // Markdown mínimo y seguro
    const blocks = [];
    let s = esc(src).replace(/```(\w*)\n([\s\S]*?)```/g, (_, l, c) => { blocks.push(`<pre><code>${c}</code></pre>`); return `\u0000${blocks.length - 1}\u0000`; });
    s = s.replace(/`([^`]+)`/g, "<code>$1</code>")
      .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
      .replace(/(^|\W)\*(\S.*?\S|\S)\*(?=\W|$)/g, "$1<i>$2</i>")
      .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
    const out = []; let list = null;
    for (const line of s.split("\n")) {
      const h = line.match(/^(#{1,4})\s+(.*)/);
      const li = line.match(/^\s*(?:[-*]|\d+[.)])\s+(.*)/);
      if (li) { if (!list) { list = []; } list.push(`<li>${li[1]}</li>`); continue; }
      if (list) { out.push(`<ul>${list.join("")}</ul>`); list = null; }
      if (h) out.push(`<p><b>${h[2]}</b></p>`);
      else if (line.trim()) out.push(`<p>${line}</p>`);
    }
    if (list) out.push(`<ul>${list.join("")}</ul>`);
    // rutas de archivos del workspace -> chips clicables
    let html = out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[i]);
    html = html.replace(/(?<![\w/">])((?:plans|diagrams|reports|apps|outputs|uploads|inbox)\/[\w\-./() ]+\.(?:png|jpg|jpeg|pdf|html|svg|py|json|md|csv|xlsx|docx))/g,
      (m) => `<button class="filechip" data-open="${m}">${icon(kindOf(m))} ${m}</button>`);
    return html;
  }

  // ---------------------------------------------------------------- WebSocket
  function connect() {
    const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
    state.ws = ws;
    ws.onmessage = (m) => handle(JSON.parse(m.data));
    ws.onclose = () => { setTimeout(connect, 1500); };
  }
  const send = (o) => state.ws && state.ws.readyState === 1 && state.ws.send(JSON.stringify(o));

  function handle(ev) {
    if (ev.type === "inbox") { ev.files.forEach((f) => addPending(f)); toast("📥 Captura recibida de PixPin"); refreshLibrary(); return; }
    if (ev.type === "approval_request") { askApproval(ev); return; }
    if (ev.type === "pong") return;
    if (ev.session && state.session && ev.session !== state.session && ev.type !== "session") return;
    switch (ev.type) {
      case "session":
        if (!state.session) { state.session = ev.session; loadSessions(); }
        break;
      case "turn_start": setStatus("Pensando…"); state.streamEl = null; state.streamText = ""; break;
      case "text_delta":
        if (!state.streamEl) { state.streamEl = addMsg("assistant", ""); }
        state.streamText += ev.text; state.streamEl.innerHTML = md(state.streamText); scroll(); break;
      case "thinking_delta": setStatus("💭 " + ev.text.slice(-160)); break;
      case "assistant": state.streamEl = null; state.streamText = ""; break;
      case "status": setStatus(ev.text); break;
      case "tool_preparing": setStatus(`Preparando ${ev.name}…`); break;
      case "tool_start": addTool(ev); setStatus(`Ejecutando ${ev.name}…`); break;
      case "tool_end": finishTool(ev); break;
      case "todos": renderTodos(ev.todos); break;
      case "error": addMsg("error", esc(ev.text), true); break;
      case "done":
        setRunning(false); loadSessions(); refreshLibrary();
        if (ev.usage) $("#wsInfo").textContent = `Tokens: ${ev.usage.input.toLocaleString()} entrada (${ev.usage.cache_read.toLocaleString()} caché) · ${ev.usage.output.toLocaleString()} salida`;
        break;
    }
  }

  // ---------------------------------------------------------------- mensajes
  function clearWelcome() { const w = $(".welcome"); if (w) w.remove(); }
  function scroll() { const m = $("#messages"); m.scrollTop = m.scrollHeight; }
  function addMsg(role, html, raw = false) {
    clearWelcome();
    const d = document.createElement("div"); d.className = "msg " + role;
    d.innerHTML = raw ? html : html; $("#messages").appendChild(d); scroll(); return d;
  }
  function addUser(text, atts) {
    const d = addMsg("user", md(text || ""));
    if (atts && atts.length) {
      const a = document.createElement("div"); a.className = "atts";
      a.innerHTML = atts.map((f) => kindOf(f) === "image" ? `<img src="${fileUrl(f)}" data-open="${esc(f)}">` : `<button class="filechip" data-open="${esc(f)}">${icon(kindOf(f))} ${esc(f.split("/").pop())}</button>`).join("");
      d.appendChild(a);
    }
  }
  const tools = {};
  function addTool(ev) {
    clearWelcome();
    const d = document.createElement("details"); d.className = "tool";
    d.innerHTML = `<summary><span class="spinner"></span><span class="name">${esc(ev.name)}</span><span class="muted small">${esc(toolHint(ev))}</span><span class="badge">en curso</span></summary>
      <div class="body"><div class="small muted">Entrada</div><pre>${esc(JSON.stringify(ev.input, null, 2))}</pre><div class="result"></div></div>`;
    $("#messages").appendChild(d); tools[ev.id] = d; scroll();
  }
  function toolHint(ev) {
    const i = ev.input || {};
    return i.output || i.path || i.target || i.name || i.command || i.action || "";
  }
  function finishTool(ev) {
    let d = tools[ev.id];
    if (!d) { addTool({ id: ev.id, name: ev.name, input: {} }); d = tools[ev.id]; }
    d.querySelector(".spinner")?.remove();
    d.classList.toggle("err", !!ev.is_error);
    d.querySelector(".badge").textContent = (ev.is_error ? "error · " : "✓ ") + (ev.seconds ?? "") + "s";
    const shown = (ev.images || []).filter((f) => !f.startsWith(".tmp/") || true);
    const files = (ev.files || []).filter((f) => !f.startsWith(".tmp/"));
    d.querySelector(".result").innerHTML = `<div class="small muted">Resultado</div><pre>${esc(ev.text)}</pre>` +
      (shown.length ? `<div class="thumbs">${shown.map((f) => `<img src="${fileUrl(f)}?t=${Date.now()}" data-open="${esc(f)}">`).join("")}</div>` : "") +
      (files.length ? `<div class="atts">${files.map((f) => `<button class="filechip" data-open="${esc(f)}">${icon(kindOf(f))} ${esc(f)}</button>`).join("")}</div>` : "");
    // mostrar automáticamente el entregable principal en el visor
    const main = files.find((f) => /\.(png|jpg|jpeg|pdf|html)$/i.test(f) && !/\.preview\.png$|\.scene\.json$/.test(f));
    if (main && !ev.is_error && ["compose_plan", "render_diagram", "create_pdf", "create_miniapp", "html_to_pdf", "image_tools"].includes(ev.name)) {
      openFile(ev.name === "create_miniapp" ? (files.find((f) => f.endsWith("index.html")) || main) : main);
    }
    scroll();
  }
  function renderTodos(todos) {
    const t = $("#todos");
    if (!todos || !todos.length) { t.classList.add("hidden"); return; }
    t.classList.remove("hidden");
    t.innerHTML = "<b>Plan</b>" + todos.map((x) => `<div class="t ${x.status === "completed" ? "done" : x.status === "in_progress" ? "prog" : ""}">${x.status === "completed" ? "☑" : x.status === "in_progress" ? "▶" : "☐"} ${esc(x.content)}</div>`).join("");
  }
  function setStatus(text) { $("#statusText").textContent = text; }
  function setRunning(on) {
    state.running = on; $("#statusLine").classList.toggle("hidden", !on); $("#sendBtn").disabled = on;
  }

  // ---------------------------------------------------------------- adjuntos
  function addPending(rel) {
    if (state.pending.includes(rel)) return;
    state.pending.push(rel); renderPending();
  }
  function renderPending() {
    $("#pending").innerHTML = state.pending.map((f, i) => `<div class="pend">${kindOf(f) === "image" ? `<img src="${fileUrl(f)}">` : icon(kindOf(f))}<span title="${esc(f)}">${esc(f.split("/").pop())}</span><button data-rm="${i}" title="Quitar">✕</button></div>`).join("");
  }
  async function uploadFiles(fileList) {
    if (!fileList || !fileList.length) return;
    const fd = new FormData();
    [...fileList].forEach((f, i) => fd.append("files", f, f.name || `pegado_${Date.now()}_${i}.png`));
    const r = await fetch("/api/upload", { method: "POST", body: fd });
    const j = await r.json(); j.files.forEach(addPending); refreshLibrary();
  }

  // ---------------------------------------------------------------- visor
  function openFile(rel) {
    state.current = rel;
    const k = kindOf(rel), url = fileUrl(rel) + "?t=" + Date.now(), body = $("#viewerBody");
    body.className = "";
    $("#viewerActions").classList.remove("hidden");
    $("#viewerName").textContent = rel;
    $("#openBtn").href = url; $("#dlBtn").href = url;
    if (k === "image") body.innerHTML = `<img src="${url}" id="viewImg">`;
    else if (k === "pdf" || k === "html") body.innerHTML = `<iframe src="${url}"></iframe>`;
    else fetch(url).then((r) => r.text()).then((t) => (body.innerHTML = `<pre>${esc(t)}</pre>`));
    switchTab("view");
  }
  function switchTab(name) {
    $$(".tab").forEach((t) => t.classList.toggle("active", t.dataset.tab === name));
    $("#tab-view").classList.toggle("hidden", name !== "view");
    $("#tab-library").classList.toggle("hidden", name !== "library");
    if (name === "library") refreshLibrary();
  }
  async function refreshLibrary() {
    const items = await (await fetch("/api/library")).json();
    const groups = {};
    items.forEach((it) => (groups[it.folder] = groups[it.folder] || []).push(it));
    const names = { plans: "Planos", diagrams: "Diagramas", reports: "Informes", apps: "Mini apps", outputs: "Otros", inbox: "Desde PixPin", uploads: "Subidos" };
    $("#library").innerHTML = Object.keys(names).filter((g) => groups[g]).map((g) =>
      `<div class="libgroup">${names[g]}</div>` + groups[g].slice(0, 60).map((it) =>
        `<div class="libitem" data-open="${esc(it.path)}"><div class="th">${it.kind === "image" ? `<img loading="lazy" src="${fileUrl(it.path)}">` : icon(it.kind)}</div><div class="nm" title="${esc(it.path)}">${esc(it.path.split("/").slice(-2).join("/"))}</div></div>`).join("")).join("")
      || '<div class="muted">Aún no hay archivos.</div>';
  }

  // ---------------------------------------------------------------- sesiones
  async function loadSessions() {
    const list = await (await fetch("/api/sessions")).json();
    $("#sessions").innerHTML = list.map((s) => `<li data-sid="${esc(s.id)}" class="${s.id === state.session ? "active" : ""}"><span>${esc(s.title)}</span><span class="del" data-del="${esc(s.id)}">✕</span></li>`).join("");
    const cur = list.find((s) => s.id === state.session);
    $("#sessionTitle").textContent = cur ? cur.title : "Nueva sesión";
  }
  async function openSession(sid) {
    const d = await (await fetch("/api/sessions/" + sid)).json();
    state.session = sid; $("#messages").innerHTML = "";
    for (const ev of d.transcript) {
      if (ev.type === "user") addUser(ev.text, ev.attachments);
      else if (ev.type === "assistant") addMsg("assistant", md(ev.text));
      else if (ev.type === "tool_end") { addTool({ id: ev.id, name: ev.name, input: {} }); finishToolQuiet(ev); }
      else if (ev.type === "error") addMsg("error", esc(ev.text));
    }
    renderTodos(d.todos); setRunning(!!d.running); loadSessions();
  }
  function finishToolQuiet(ev) { const cur = state.current; finishTool(ev); if (cur) openFile(cur); }
  function newSession() {
    state.session = null; $("#messages").innerHTML = `<div class="welcome"><h2>Nueva sesión</h2><p>Adjunta archivos o describe la tarea.</p></div>`;
    renderTodos([]); loadSessions();
  }

  // ---------------------------------------------------------------- aprobación
  function askApproval(ev) {
    $("#approvalName").textContent = `Herramienta: ${ev.name}`;
    $("#approvalBody").textContent = ev.summary;
    $("#approval").classList.remove("hidden");
    const done = (ok) => { send({ type: "approve", id: ev.id, ok }); $("#approval").classList.add("hidden"); };
    $("#allowBtn").onclick = () => done(true); $("#denyBtn").onclick = () => done(false);
  }

  // ---------------------------------------------------------------- eventos UI
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#input").value.trim();
    if (!text && !state.pending.length) return;
    if (state.running) return toast("El agente está trabajando…");
    addUser(text, state.pending);
    send({ type: "chat", session: state.session, text, attachments: state.pending });
    state.pending = []; renderPending(); $("#input").value = ""; setRunning(true); setStatus("Enviando…");
  });
  $("#input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); $("#composer").requestSubmit(); } });
  $("#input").addEventListener("input", (e) => { e.target.style.height = "auto"; e.target.style.height = Math.min(220, e.target.scrollHeight) + "px"; });
  $("#fileInput").addEventListener("change", (e) => uploadFiles(e.target.files));
  document.addEventListener("paste", (e) => {
    const files = [...(e.clipboardData?.files || [])];
    if (files.length) { e.preventDefault(); uploadFiles(files); toast("Imagen pegada"); }
  });
  const chat = $("#chat");
  chat.addEventListener("dragover", (e) => { e.preventDefault(); $("#dropHint").classList.remove("hidden"); });
  chat.addEventListener("dragleave", (e) => { if (e.target === chat || !chat.contains(e.relatedTarget)) $("#dropHint").classList.add("hidden"); });
  chat.addEventListener("drop", (e) => { e.preventDefault(); $("#dropHint").classList.add("hidden"); uploadFiles(e.dataTransfer.files); });
  document.addEventListener("click", async (e) => {
    const o = e.target.closest("[data-open]"); if (o) { openFile(o.dataset.open); return; }
    const rm = e.target.closest("[data-rm]"); if (rm) { state.pending.splice(+rm.dataset.rm, 1); renderPending(); return; }
    const del = e.target.closest("[data-del]");
    if (del) { e.stopPropagation(); if (confirm("¿Borrar esta sesión?")) { await fetch("/api/sessions/" + del.dataset.del, { method: "DELETE" }); if (state.session === del.dataset.del) newSession(); loadSessions(); } return; }
    const li = e.target.closest("[data-sid]"); if (li) { openSession(li.dataset.sid); return; }
    const tpl = e.target.closest("[data-tpl]"); if (tpl) { $("#input").value = TEMPLATES[tpl.dataset.tpl]; $("#input").focus(); return; }
    const cap = e.target.closest("[data-capture]");
    if (cap) {
      const r = await fetch("/api/pixpin/capture", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ region: cap.dataset.capture }) });
      const j = await r.json(); if (j.ok) { addPending(j.file); toast("Captura añadida"); } else toast(j.error, 5000);
      return;
    }
    const tab = e.target.closest(".tab"); if (tab) switchTab(tab.dataset.tab);
  });
  $("#viewerBody").addEventListener("click", (e) => { if (e.target.id === "viewImg") e.target.classList.toggle("zoom"); });
  $("#newSession").onclick = newSession;
  $("#cancelBtn").onclick = () => send({ type: "cancel", session: state.session });
  $("#attachBtn").onclick = () => { if (state.current) { addPending(state.current); toast("Añadido como adjunto"); } };
  $("#pinBtn").onclick = async () => {
    if (!state.current) return;
    const r = await fetch("/api/pixpin/pin", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ files: [state.current], session: state.session }) });
    const j = await r.json(); toast(j.ok ? "📌 Fijado en PixPin" : j.error, j.ok ? 2000 : 6000);
  };
  $("#installScripts").onclick = async () => { const j = await (await fetch("/api/pixpin/install", { method: "POST" })).json(); toast("Scripts generados en pixpin_scripts/ (ver LEEME.txt)", 5000); refreshLibrary(); };
  const saveSetting = (k, v) => fetch("/api/settings", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ [k]: v }) });
  $("#effort").onchange = (e) => saveSetting("effort", e.target.value);
  $("#perm").onchange = (e) => saveSetting("permission_mode", e.target.value);

  // ---------------------------------------------------------------- inicio
  (async () => {
    const st = await (await fetch("/api/status")).json();
    $("#effort").value = st.effort; $("#perm").value = st.permission_mode;
    $("#pixpinStatus").innerHTML = st.pixpin ? `<span class="ok">● PixPin conectado</span>` : `<span class="bad">● PixPin no encontrado</span> (configura pixpin_path)`;
    $("#wsInfo").textContent = "Workspace: " + st.workspace;
    connect(); loadSessions(); refreshLibrary();
  })();
})();
