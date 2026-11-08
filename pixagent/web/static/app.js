/* PixAgent — cliente web (Windows, macOS, Android, iOS, iPadOS).
   Sin frameworks ni dependencias; JS ES2019 compatible con Safari iOS 15 (sin lookbehind). */
(() => {
  "use strict";
  const $ = (s) => document.querySelector(s);
  const $$ = (s) => Array.from(document.querySelectorAll(s));
  const isTouch = matchMedia("(pointer: coarse)").matches;
  const isMobile = () => matchMedia("(max-width: 820px)").matches;
  const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  const state = {
    session: null, pending: [], ws: null, running: false, current: null, lastSeq: 0,
    streamEl: null, streamText: "", rafPending: false, retry: 0, maxPx: 3200, everConnected: false,
    tab: "view", view: "agent", pane: "chat", apps: null, app: null, lastDeliverable: null, pixpin: false, undone: false, appsQuery: "",
    saveData: (navigator.connection && navigator.connection.saveData) || localGet("saveData") === "1",
    question: null, apiKey: null, replay: null,
  };

  // Único arranque guiado que queda: «Pedir una mini app» desde la galería vacía
  const TEMPLATES = { app: "Crea una mini app (HTML) que sirva para: " };
  const PLACEHOLDER = "Cuéntame qué necesitas: puedes adjuntar fotos, planos o documentos…";
  const PLACEHOLDER_ANSWER = "Responde al agente…";
  // Ejemplos que rotan en la bienvenida (solo texto: la conversación manda)
  const EXAMPLES = [
    "«Ubica estas 14 fotos en el plano de planta baja y genera el PDF»",
    "«Haz un informe de visita de obra con las fotos y mis notas»",
    "«Monta un panel fotográfico numerado con pie de foto y cajetín»",
    "«Calcula el aforo de esta gradería y dime qué norma aplica»",
    "«Pasa esta tabla de mediciones a Excel y súmala por capítulos»",
    "«Crea una mini app para renombrar fotos de obra por zona»",
  ];
  const TOOL_LABELS = {
    compose_plan: "Componer plano", render_diagram: "Diagrama", create_pdf: "Informe PDF", create_miniapp: "Mini app",
    html_to_pdf: "HTML a PDF", image_tools: "Imagen", view_image: "Ver imagen", todo_write: "Plan", run_python: "Python",
    run_shell: "Terminal", read_file: "Leer archivo", write_file: "Escribir archivo", edit_file: "Editar archivo",
    list_files: "Listar archivos", search_files: "Buscar", pdf_tools: "PDF", photo_panel: "Panel fotográfico",
    pixpin: "PixPin", preview_page: "Vista previa",
  };

  // ---------------------------------------------------------------- utilidades
  function localGet(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }
  function localSet(k, v) { try { localStorage.setItem(k, v); } catch (e) { /* modo privado */ } }
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const enc = (rel) => rel.split("/").map(encodeURIComponent).join("/");
  const fileUrl = (rel) => "/files/" + enc(rel);
  const ico = (name, cls) => `<svg class="icon${cls ? " " + cls : ""}" aria-hidden="true"><use href="#i-${name}"/></svg>`;
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
  const kindIcon = (k) => ({ image: "image", pdf: "report", html: "code", text: "file" }[k] || "file");
  const fileChip = (rel, label) => `<button type="button" class="filechip" data-open="${esc(rel)}" title="${esc(rel)}">${ico(kindIcon(kindOf(rel)))}<span>${esc(label || rel)}</span></button>`;
  const imgTag = (rel, w, extra) => kindOf(rel) === "image" && !/\.svg$/i.test(rel)
    ? `<img loading="lazy" decoding="async" src="${thumbUrl(rel, w)}" data-open="${esc(rel)}" alt="" ${extra || ""}>`
    : `<img loading="lazy" decoding="async" src="${fileUrl(rel)}" data-open="${esc(rel)}" alt="" ${extra || ""}>`;
  const baseName = (p) => p.split("/").pop();
  const fmtSec = (s) => (s < 10 ? s.toFixed(1) : Math.round(s)).toString().replace(".", ",") + " s";

  // Vibración suave solo tras un gesto del usuario (si no, Chrome la bloquea y lo anota en la consola)
  let interacted = false;
  ["pointerdown", "keydown", "touchstart"].forEach((ev) => document.addEventListener(ev, () => { interacted = true; }, { once: true, passive: true, capture: true }));
  function buzz(pattern) {
    const active = (navigator.userActivation && navigator.userActivation.hasBeenActive) || interacted;
    if (navigator.vibrate && active) { try { navigator.vibrate(pattern); } catch (e) { /* no soportado */ } }
  }
  function toast(msg, ms, type) {
    const stack = $("#toasts");
    const t = document.createElement("div");
    t.className = "toast" + (type ? " toast-" + type : "");
    t.innerHTML = (type === "ok" ? ico("check") : type === "err" ? ico("alert") : type === "warn" ? ico("alert") : "") + `<span>${esc(msg)}</span>`;
    stack.appendChild(t);
    while (stack.children.length > 3) stack.removeChild(stack.firstChild);
    setTimeout(() => { t.classList.add("out"); setTimeout(() => t.remove(), 200); }, ms || 2600);
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
    const out = []; let list = null; let listTag = "ul";
    const flush = () => { if (list) { out.push("<" + listTag + ">" + list.join("") + "</" + listTag + ">"); list = null; } };
    s.split("\n").forEach((line) => {
      const h = line.match(/^(#{1,4})\s+(.*)/);
      const li = line.match(/^\s*([-*]|\d+[.)])\s+(.*)/);
      if (li) { const tag = /\d/.test(li[1]) ? "ol" : "ul"; if (list && tag !== listTag) flush(); listTag = tag; (list = list || []).push("<li>" + li[2] + "</li>"); return; }
      flush();
      if (h) { const lvl = Math.min(5, h[1].length + 2); out.push(`<h${lvl}>${h[2]}</h${lvl}>`); }
      else if (/^\s*&gt;\s?/.test(line)) out.push("<blockquote>" + line.replace(/^\s*&gt;\s?/, "") + "</blockquote>");
      else if (/^\s*(-{3,}|\*{3,})\s*$/.test(line)) out.push("<hr>");
      else if (line.trim()) out.push("<p>" + line + "</p>");
    });
    flush();
    return out.join("").replace(/\u0000(\d+)\u0000/g, (_, i) => blocks[i])
      .replace(FILE_RX, (m, pre, f) => pre + fileChip(f, baseName(f)));
  }

  // ---------------------------------------------------------------- conexión (con reanudación)
  function setConn(on) {
    $("#conn").classList.toggle("on", on);
    $("#connPill").classList.toggle("hidden", on || !state.everConnected);
    if (on) state.everConnected = true;
  }
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
  // iOS/Android suspenden las pestañas en segundo plano: al volver, reconectar y recuperar eventos
  document.addEventListener("visibilitychange", () => { if (document.visibilityState === "visible") connect(); });
  window.addEventListener("online", connect);
  setInterval(() => { if (document.visibilityState === "visible") send({ type: "ping" }); }, 25000);

  function handle(ev) {
    switch (ev.type) {
      case "inbox": ev.files.forEach(addPending); toast("Recibido: " + ev.files.length + " archivo(s)", 2600, "ok"); refreshLibrary(); return;
      case "approval_request": askApproval(ev); return;
      case "approval_resolved": if ($("#approval").dataset.id === ev.id) $("#approval").classList.add("hidden"); return;
      case "pong": return;
      case "hello_ok":
        if (state.replay) { // fin de la recuperación tras recargar
          const mode = state.replay; state.replay = null;
          if (mode === "full" && !$("#messages .msg")) { newSession(); } // la sesión ya no existe
          else if (!state.question) setStatus("Pensando…");
        }
        return;
    }
    if (ev.session && state.session && ev.session !== state.session) return;
    // Recuperación «solo preguntas»: el historial ya está pintado desde el archivo; del reenvío solo interesa lo pendiente
    if (state.replay === "questions" && ev.type !== "question" && ev.type !== "done") return;
    // ask_user se muestra como tarjeta de pregunta, no como herramienta
    if ((ev.type === "tool_start" || ev.type === "tool_end" || ev.type === "tool_preparing") && ev.name === "ask_user") return;
    switch (ev.type) {
      case "session":
        if (!state.session && ev.client === clientId) { state.session = ev.session; rememberSession(); loadSessions(); }
        break;
      case "question": addQuestion(ev, true); break;
      case "answer": resolveQuestion(ev.id, ev.text === "(sin respuesta)" ? null : ev.text); break;
      case "question_resolved": resolveQuestion(ev.id, null); setStatus("Pensando…"); break;
      case "turn_start": setStatus("Pensando…"); endStream(); break;
      case "text_delta":
        if (!state.streamEl) { state.streamEl = addMsg("assistant", ""); state.streamEl.classList.add("streaming"); }
        state.streamText += ev.text; scheduleRender(); break;
      case "thinking_delta": setStatus("Razonando: " + ev.text.slice(-160).replace(/\s+/g, " ")); break;
      case "assistant": renderStream(); endStream(); break;
      case "status": setStatus(ev.text); break;
      case "tool_preparing": setStatus("Preparando " + toolLabel(ev.name) + "…"); break;
      case "tool_start": addTool(ev); setStatus("Ejecutando " + toolLabel(ev.name) + "…"); break;
      case "tool_end": finishTool(ev, true); break;
      case "todos": renderTodos(ev.todos); break;
      case "error": addError(ev.text); break;
      case "done":
        renderStream(); endStream(); state.undone = false; clearQuestion(); setRunning(false); loadSessions(); refreshLibrary();
        if (ev.usage) renderUsage(ev.usage);
        break;
    }
  }
  // Tokens y coste estimado acumulado de la sesión, discretos en el pie de la barra lateral
  function renderUsage(u) {
    const total = (u.input || 0) + (u.output || 0);
    $("#usage").textContent = total.toLocaleString("es-ES") + " tokens";
    $("#usage").title = (u.input || 0).toLocaleString("es-ES") + " entrada (" + (u.cache_read || 0).toLocaleString("es-ES") + " en caché) · " + (u.output || 0).toLocaleString("es-ES") + " salida";
    const c = $("#usageCost");
    if (typeof u.usd === "number") {
      const money = u.usd.toLocaleString("es-ES", { style: "currency", currency: "USD", minimumFractionDigits: 2, maximumFractionDigits: 2 });
      c.textContent = u.usd > 0 && u.usd < 0.005 ? "< " + (0.01).toLocaleString("es-ES", { style: "currency", currency: "USD" }) : "≈ " + money;
      c.title = "Coste estimado acumulado de esta sesión"; c.classList.remove("hidden");
    } else c.classList.add("hidden");
  }
  // Contadores locales de uso (para ordenar mini apps frecuentes); fallan en silencio sin localStorage
  function counts(key) { try { return JSON.parse(localStorage.getItem(key) || "{}") || {}; } catch (e) { return {}; } }
  function bump(key, id) { try { const c = counts(key); c[id] = (c[id] || 0) + 1; localStorage.setItem(key, JSON.stringify(c)); } catch (e) { /* modo privado */ } }
  // Repintar como mucho una vez por fotograma (los móviles modestos lo agradecen)
  function scheduleRender() {
    if (state.rafPending) return;
    state.rafPending = true;
    requestAnimationFrame(() => { state.rafPending = false; renderStream(); });
  }
  function renderStream() { if (state.streamEl) { state.streamEl.querySelector(".prose").innerHTML = md(state.streamText); scroll(); } }
  function endStream() { if (state.streamEl) state.streamEl.classList.remove("streaming"); state.streamEl = null; state.streamText = ""; }
  const toolLabel = (n) => TOOL_LABELS[n] || n;

  // ---------------------------------------------------------------- mensajes
  let exTimer = 0;
  function showWelcome() {
    $("#messages").innerHTML = ""; $("#messages").appendChild($("#welcomeTpl").content.cloneNode(true));
    // Una línea de ejemplos que rota despacio; se detiene sola cuando la bienvenida desaparece
    clearInterval(exTimer);
    const exEl = $("#welcomeExText");
    let i = Math.floor(Math.random() * EXAMPLES.length);
    const show = () => { if (!document.contains(exEl)) { clearInterval(exTimer); return; } exEl.textContent = EXAMPLES[i % EXAMPLES.length]; i++; };
    show();
    const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    exTimer = setInterval(() => {
      if (!document.contains(exEl)) { clearInterval(exTimer); return; }
      if (reduced) { show(); return; }
      exEl.classList.add("fade"); setTimeout(() => { show(); exEl.classList.remove("fade"); }, 220);
    }, 5200);
    renderKeyCard();
  }
  function clearWelcome() { const w = $("#messages .welcome"); if (w) w.remove(); }

  // ---------------------------------------------------------------- preguntas del agente (ask_user)
  const REC_RX = /\s*\((recomendad[oa]s?)\)\s*/i;
  function addQuestion(ev, live) {
    if ($('#messages .ask[data-qid="' + ev.id + '"]')) return;
    clearWelcome();
    const opts = (ev.options || []).slice(0, 4);
    const d = document.createElement("div");
    d.className = "msg ask" + (ev.multi ? " multi" : ""); d.dataset.qid = ev.id;
    d.innerHTML = `<div class="ask-head"><span class="ask-icon">${ico("question")}</span><div class="ask-q">${md(ev.question || "")}</div></div>
      <div class="ask-opts" role="${ev.multi ? "group" : "listbox"}" aria-label="Opciones">${opts.map((o, i) => {
        const label = String(o.label || ""), rec = REC_RX.test(label);
        return `<button type="button" class="ask-opt${rec ? " rec" : ""}" role="${ev.multi ? "checkbox" : "option"}" aria-checked="false" data-i="${i}" data-label="${esc(label)}">
          <span class="ask-key tabular">${i + 1}</span>
          <span class="ask-body"><b>${esc(label.replace(REC_RX, " ").trim())}${rec ? ' <span class="ask-rec">Recomendado</span>' : ""}</b>${o.description ? `<small>${esc(o.description)}</small>` : ""}</span>
          <span class="ask-check">${ico("check")}</span></button>`; }).join("")}</div>
      <div class="ask-foot">${ev.multi ? `<button type="button" class="btn btn-primary ask-send" disabled>${ico("send")}Enviar</button>` : ""}<span class="ask-hint">${ev.multi ? "Marca una o varias y envía, " : ""}o escribe tu respuesta abajo</span></div>`;
    $("#messages").appendChild(d); trimDom();
    d._multi = !!ev.multi; d._options = opts;
    const already = state.question && state.question.id !== ev.id;
    if (already) resolveQuestion(state.question.id, null); // solo una pendiente por sesión
    state.question = { id: ev.id, el: d, multi: !!ev.multi };
    setWaiting(true);
    $("#messages").scrollTop = $("#messages").scrollHeight;
    if (live) {
      if (isTouch) buzz([25, 40, 25]);
      if (!isTouch && document.visibilityState === "visible") $("#input").focus();
    }
    return d;
  }
  function $$in(sel, root) { return Array.from(root.querySelectorAll(sel)); }
  function pickOption(i) {
    const q = state.question; if (!q || q.el.classList.contains("done")) return;
    const b = q.el.querySelector('.ask-opt[data-i="' + i + '"]'); if (!b) return;
    if (q.multi) {
      b.classList.toggle("sel"); b.setAttribute("aria-checked", b.classList.contains("sel") ? "true" : "false");
      const n = $$in(".ask-opt.sel", q.el).length, send = q.el.querySelector(".ask-send");
      send.disabled = !n; send.innerHTML = ico("send") + (n > 1 ? "Enviar " + n : "Enviar");
    } else { b.classList.add("sel"); b.setAttribute("aria-checked", "true"); if (!answerQuestion(b.dataset.label)) { b.classList.remove("sel"); b.setAttribute("aria-checked", "false"); } }
  }
  function sendSelection() {
    const q = state.question; if (!q || !q.multi) return;
    const labels = $$in(".ask-opt.sel", q.el).map((b) => b.dataset.label);
    if (labels.length) answerQuestion(labels.join(", "));
  }
  function answerQuestion(text) {
    const q = state.question; if (!q) return false;
    if (!send({ type: "answer", id: q.id, session: state.session, text: text })) { toast("Sin conexión; reintentando…", 3000, "warn"); connect(); return false; }
    resolveQuestion(q.id, text); // optimista: el eco del servidor es idempotente
    if (isTouch) $("#input").blur();
    return true;
  }
  // Estado resuelto: opciones desactivadas, la elegida marcada, y la respuesta escrita bajo la tarjeta
  function resolveQuestion(id, text) {
    const d = $('#messages .ask[data-qid="' + id + '"]');
    if (d && !d.classList.contains("done")) {
      d.classList.add("done");
      $$in(".ask-opt", d).forEach((b) => { b.disabled = true; b.tabIndex = -1; });
      if (text) {
        const parts = text.split(/\s*,\s*/);
        $$in(".ask-opt", d).forEach((b) => { if (text === b.dataset.label || parts.indexOf(b.dataset.label) >= 0) { b.classList.add("sel"); b.setAttribute("aria-checked", "true"); } });
        const custom = !$$in(".ask-opt.sel", d).length;
        d.querySelector(".ask-foot").innerHTML = `<div class="ask-answer${custom ? " custom" : ""}">${ico("check", "icon-sm")}<span>${custom ? esc(text) : "Elegido: " + esc(text.replace(REC_RX, " ").trim())}</span></div>`;
      } else d.querySelector(".ask-foot").innerHTML = `<div class="ask-answer faint">${ico("x", "icon-sm")}<span>Sin respuesta</span></div>`;
    } else if (d && text && !d.querySelector(".ask-answer span")) {
      d.querySelector(".ask-foot").innerHTML = `<div class="ask-answer">${ico("check", "icon-sm")}<span>${esc(text)}</span></div>`;
    }
    if (state.question && state.question.id === id) { state.question = null; setWaiting(false); }
  }
  function clearQuestion() { if (state.question) resolveQuestion(state.question.id, null); }
  function setWaiting(on) {
    $("#statusLine").classList.toggle("waiting", on);
    $("#input").placeholder = on ? PLACEHOLDER_ANSWER : PLACEHOLDER;
    if (!$("#input").value && typeof fitInput === "function") fitInput();
    $("#sendBtn").disabled = state.running && !on;
    if (on) setStatus("Esperando tu respuesta");
  }
  function rememberSession() { try { if (state.session) sessionStorage.setItem("pix:sid", state.session); else sessionStorage.removeItem("pix:sid"); } catch (e) { /* modo privado */ } }
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
    const d = document.createElement("div"); d.className = "msg " + role;
    if (role === "assistant") d.innerHTML = `<img class="mark" src="/static/icon-192.png" alt="" width="28" height="28"><div class="prose">${html}</div>`;
    else d.innerHTML = html;
    $("#messages").appendChild(d); trimDom(); scroll(); return d;
  }
  function addError(text) {
    const keyErr = /clave de API/i.test(text || "");
    addMsg("error", ico("alert") + `<div class="grow">${esc(text)}</div>` + (keyErr ? `<button type="button" class="btn btn-sm err-action" data-addkey>${ico("key")}Añadir clave</button>` : ""));
  }
  function addUser(text, atts) {
    const d = addMsg("user", `<div class="bubble">${md(text || "")}</div>`);
    if (atts && atts.length) {
      const a = document.createElement("div"); a.className = "atts";
      a.innerHTML = atts.map((f) => kindOf(f) === "image" ? imgTag(f, 72) : fileChip(f, baseName(f))).join("");
      d.appendChild(a); d.style.flexWrap = "wrap";
    }
    $("#messages").scrollTop = $("#messages").scrollHeight;
  }
  const tools = {};
  function addTool(ev) {
    clearWelcome();
    const d = document.createElement("details"); d.className = "tool";
    const i = ev.input || {};
    const hint = i.output || i.path || i.target || i.name || i.command || i.action || "";
    d.innerHTML = `<summary><span class="tool-state"><span class="spinner"></span></span><span class="tool-name" title="${esc(ev.name)}">${esc(toolLabel(ev.name))}</span><span class="tool-hint">${esc(hint)}</span><span class="tool-meta">en curso</span></summary><div class="tool-body"></div>`;
    d._input = ev.input;
    d.addEventListener("toggle", () => { // contenido pesado solo al abrir
      if (d.open && !d._filled) {
        d._filled = true;
        d.querySelector(".tool-body").insertAdjacentHTML("afterbegin", d._input && Object.keys(d._input).length ? `<div class="tool-label">Entrada</div><pre>${esc(JSON.stringify(d._input, null, 2))}</pre>` : "");
      }
    });
    $("#messages").appendChild(d); tools[ev.id] = d; trimDom(); scroll();
  }
  const SHOW_TOOLS = ["compose_plan", "render_diagram", "create_pdf", "create_miniapp", "html_to_pdf", "image_tools", "photo_panel"];
  function finishTool(ev, live) {
    let d = tools[ev.id];
    if (!d) { addTool({ id: ev.id, name: ev.name, input: {} }); d = tools[ev.id]; }
    d.classList.toggle("err", !!ev.is_error); d.classList.toggle("ok", !ev.is_error);
    d.querySelector(".tool-state").innerHTML = ico(ev.is_error ? "x" : "check");
    d.querySelector(".tool-meta").textContent = (ev.is_error ? "error" : "") + (ev.seconds != null ? (ev.is_error ? " · " : "") + fmtSec(ev.seconds) : "");
    const imgs = ev.images || [];
    const files = (ev.files || []).filter((f) => f.indexOf(".tmp/") !== 0);
    d.querySelector(".tool-body").insertAdjacentHTML("beforeend", `<div class="tool-label">Resultado</div><pre>${esc(ev.text)}</pre>` +
      (files.length ? `<div class="atts">${files.map((f) => fileChip(f, f)).join("")}</div>` : ""));
    if (imgs.length) { // miniaturas visibles aunque la tarjeta esté cerrada
      d.insertAdjacentHTML("afterend", `<div class="thumbs tool-thumbs">${imgs.slice(0, 4).map((f) => imgTag(f, 160)).join("")}</div>`);
    }
    const main = ev.name === "create_miniapp" ? files.find((f) => /index\.html$/.test(f)) || files[0]
      : files.find((f) => /\.(png|jpe?g|pdf|html)$/i.test(f) && !/\.preview\.png$/.test(f));
    if (!live && main && !ev.is_error && SHOW_TOOLS.indexOf(ev.name) >= 0) state.lastDeliverable = main;
    if (live && main && !ev.is_error && SHOW_TOOLS.indexOf(ev.name) >= 0) {
      if (isMobile()) { state.current = main; $("#viewBadge").classList.remove("hidden"); openFile(main, true); }
      else openFile(main, state.view === "apps"); // sin sacar al usuario de una mini app abierta
    }
    if (ev.name === "create_miniapp" && !ev.is_error) state.apps = null; // la galería se recarga al abrirla
    scroll();
  }
  function renderTodos(todos) {
    const t = $("#todos");
    if (!todos || !todos.length) { t.classList.add("hidden"); t._shown = false; return; }
    if (!t._shown) { t._shown = true; t.open = !isMobile(); } // en móvil, plegado para no tapar el chat
    t.classList.remove("hidden");
    const done = todos.filter((x) => x.status === "completed").length;
    $("#planCount").textContent = done + "/" + todos.length;
    $("#planBar").style.width = Math.round(done / todos.length * 100) + "%";
    $("#planList").innerHTML = todos.map((x) => {
      const cls = x.status === "completed" ? "done" : x.status === "in_progress" ? "prog" : "";
      return `<div class="plan-item ${cls}"><span class="pi">${x.status === "completed" ? ico("check") : ""}</span><span>${esc(x.content)}</span></div>`;
    }).join("");
  }
  function setStatus(text) { if (state.question && text !== "Esperando tu respuesta") return; $("#statusText").textContent = text; }
  function setRunning(on) { state.running = on; $("#statusLine").classList.toggle("hidden", !on); $("#sendBtn").disabled = on && !state.question; updateUndo(); }
  // «Deshacer cambios» bajo el último mensaje del asistente, solo con la sesión en reposo
  function updateUndo() {
    $$("#messages .undo-row").forEach((r) => r.remove());
    if (state.running || !state.session || state.undone) return;
    const msgs = $$("#messages .msg.assistant"), last = msgs[msgs.length - 1];
    if (!last) return;
    const row = document.createElement("div"); row.className = "undo-row";
    row.innerHTML = `<button type="button" class="btn btn-ghost btn-sm" id="undoBtn" title="Restaura los archivos que modificó o creó el agente en su última respuesta">${ico("undo")}Deshacer cambios</button>`;
    last.insertAdjacentElement("afterend", row);
  }
  async function undoLast() {
    if (!state.session || state.running) return;
    const ok = await askConfirm("¿Deshacer los cambios del agente?", "Se restaurarán los archivos que modificó y se borrarán los que creó en su última respuesta. El chat se conserva.", "Deshacer", "undo");
    if (!ok) return;
    const b = $("#undoBtn"); if (b) b.disabled = true;
    let j;
    try { j = await api("/api/sessions/" + state.session + "/undo", {}); } catch (e) { j = { ok: false, error: "Sin conexión con el servidor" }; }
    if (!j.ok) { if (b) b.disabled = false; toast(j.error || "No se pudo deshacer", 4500, "err"); return; }
    const list = j.restored || [];
    state.undone = true; updateUndo();
    addMsg("note", esc("Cambios deshechos: " + list.join(", ")));
    toast(list.length === 1 ? list[0].charAt(0).toUpperCase() + list[0].slice(1) : list.length + " archivos restaurados", 3500, "ok");
    refreshLibrary();
    if (state.current) { // el visor puede estar mostrando un archivo restaurado o borrado
      const gone = list.some((s) => s.indexOf("borrado ") === 0 && s.slice(8) === state.current);
      if (gone) { state.current = null; $("#viewerActions").classList.add("hidden"); $("#viewerBody").innerHTML = `<div class="empty"><span class="empty-icon">${ico("undo")}</span><div class="empty-title">Archivo deshecho</div><div class="empty-text">El agente lo había creado en su última respuesta y se ha eliminado.</div></div>`; }
      else openFile(state.current, true);
    }
  }

  // ---------------------------------------------------------------- adjuntos (reducidos en el dispositivo)
  function addPending(rel) { if (state.pending.indexOf(rel) < 0) { state.pending.push(rel); renderPending(); } }
  function renderPending(extra) {
    $("#pending").innerHTML = state.pending.map((f, i) =>
      `<div class="pend">${kindOf(f) === "image" ? imgTag(f, 36) : `<span class="pend-ico">${ico(kindIcon(kindOf(f)), "icon-sm")}</span>`}<span class="nm" title="${esc(f)}">${esc(baseName(f))}</span><button type="button" class="rm" data-rm="${i}" aria-label="Quitar">${ico("x")}</button></div>`).join("") + (extra || "");
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
    const progChip = (lbl, pct) => `<div class="pend uploading"><span class="lbl"><span id="upLbl">${esc(lbl)}</span><span id="upPct" class="tabular">${pct == null ? "" : pct + "%"}</span></span><span class="progress"><i id="upBar" style="width:${pct || 0}%"></i></span></div>`;
    renderPending(progChip("Preparando " + files.length + " archivo(s)…"));
    const fd = new FormData();
    for (let i = 0; i < files.length; i++) {
      const f = await shrinkImage(files[i]);
      fd.append("files", f, f.name || ("pegado_" + Date.now() + "_" + i + ".png"));
    }
    const lbl = $("#upLbl"); if (lbl) lbl.textContent = "Subiendo…";
    await new Promise((resolve) => {
      const x = new XMLHttpRequest(); x.open("POST", "/api/upload");
      x.upload.onprogress = (e) => {
        if (!e.lengthComputable) return;
        const p = Math.round(e.loaded / e.total * 100), bar = $("#upBar"), pct = $("#upPct");
        if (bar) bar.style.width = p + "%"; if (pct) pct.textContent = p + "%";
      };
      x.onload = () => { try { JSON.parse(x.responseText).files.forEach(addPending); } catch (e) { toast("Error al subir", 3000, "err"); } renderPending(); resolve(); };
      x.onerror = () => { toast("Error de red al subir", 3000, "err"); renderPending(); resolve(); };
      x.send(fd);
    });
  }

  // ---------------------------------------------------------------- visor
  // Zoom universal (rueda, trackpad, pellizco, doble clic/toque, teclado) con PixZoom; una instancia por archivo abierto
  function destroyZoom() { if (state.zoom) { try { state.zoom.destroy(); } catch (e) { /* ya destruido */ } state.zoom = null; } }
  function attachZoom(box, content, opts) {
    destroyZoom();
    if (!window.PixZoom) return null;
    const z = PixZoom.attach(box, content, opts);
    state.zoom = z;
    // Al ampliar una miniatura más de 1,5× se carga el original (nítido), una sola vez
    if (content.tagName === "IMG" && content.dataset.full) {
      let timer = 0;
      const check = () => {
        if (state.zoom !== z) { clearInterval(timer); return; }
        if (z.scale > 1.5 && content.src.indexOf("/thumb/") >= 0) { content.src = content.dataset.full; clearInterval(timer); }
      };
      ["wheel", "pointerup", "keyup", "click", "gesturechange", "dblclick"].forEach((ev) => box.addEventListener(ev, check, { passive: true }));
      timer = setInterval(check, 400); // red de seguridad (gestos del sistema, botones)
    }
    return z;
  }
  function openFile(rel, quiet) {
    state.current = rel;
    const k = kindOf(rel), url = fileUrl(rel), body = $("#viewerBody");
    destroyZoom();
    body.className = "";
    $("#viewerActions").classList.remove("hidden");
    $("#viewerName").textContent = rel;
    $("#openBtn").href = url;
    if (k === "image") {
      body.className = "zooming";
      body.innerHTML = `<div class="zoombox" id="zoomBox"><img id="viewImg" decoding="async" src="${thumbUrl(rel, Math.min(1600, body.clientWidth || 800))}" data-full="${url}" alt=""></div>`;
      attachZoom($("#zoomBox"), $("#viewImg"), { wheel: "zoom" });
    } else if (k === "pdf") {
      if (isTouch || isIOS) { // iOS/iPadOS solo muestran la 1.ª página en iframes: páginas como imágenes (con zoom por pellizco)
        body.innerHTML = '<div class="pdfpages"><div class="loading"><span class="spinner"></span>Cargando páginas…</div></div>';
        api("/api/pdfinfo/" + enc(rel)).then((j) => {
          if (state.current !== rel) return;
          const n = Math.min(j.pages || 0, 60);
          if (!n) { body.innerHTML = `<iframe src="${url}" title="PDF"></iframe>`; return; }
          body.className = "zooming";
          body.innerHTML = '<div class="zoombox" id="zoomBox"><div class="pdfpages">' + Array.from({ length: n }, (_, i) => `<img loading="lazy" decoding="async" src="${thumbUrl(rel, Math.min(900, body.clientWidth || 600), i)}" alt="Página ${i + 1}">`).join("") + "</div></div>";
          attachZoom($("#zoomBox"), $("#zoomBox .pdfpages"), { wheel: "scroll" });
        });
      } else body.innerHTML = `<iframe src="${url}" title="PDF"></iframe>`;
    } else if (k === "html") body.innerHTML = `<iframe src="${url}" title="HTML" sandbox="allow-scripts allow-forms allow-modals allow-downloads allow-popups"></iframe>`;
    else fetch(url).then((r) => r.text()).then((t) => { body.innerHTML = `<pre>${esc(t.slice(0, 200000))}</pre>`; });
    if (!quiet) { switchTab("view"); if (isMobile()) setPane("viewer"); else if (state.view !== "agent") setView("agent"); }
  }
  function switchTab(name) {
    state.tab = name;
    $$(".viewer-tabs [data-tab]").forEach((t) => t.classList.toggle("on", t.dataset.tab === name));
    $("#tab-view").classList.toggle("hidden", name !== "view");
    $("#tab-library").classList.toggle("hidden", name !== "library");
    if (name === "library") refreshLibrary();
  }
  let libTimer = null;
  function refreshLibrary() { // con antirrebote: una sola petición aunque lleguen varios eventos
    clearTimeout(libTimer);
    libTimer = setTimeout(async () => {
      if (state.tab !== "library") return;
      if (isMobile() && state.pane !== "viewer") return;
      const items = await api("/api/library?limit=" + (state.saveData ? 80 : 200));
      const groups = {};
      items.forEach((it) => { (groups[it.folder] = groups[it.folder] || []).push(it); });
      const names = { plans: "Planos", diagrams: "Diagramas", reports: "Informes", apps: "Mini apps", outputs: "Otros", inbox: "Recibidos (PixPin / compartir)", uploads: "Subidos" };
      $("#library").innerHTML = Object.keys(names).filter((g) => groups[g]).map((g) =>
        `<div class="libgroup">${names[g]}<span class="n">${groups[g].length}</span></div>` + groups[g].slice(0, 60).map((it) =>
          `<div class="libitem" data-open="${esc(it.path)}"><div class="th">${it.kind === "image" ? imgTag(it.path, 140) : it.kind === "pdf" ? `<img loading="lazy" decoding="async" alt="" src="${thumbUrl(it.path, 140, 0)}" onerror="this.outerHTML='<svg class=icon><use href=#i-report/></svg>'">` : ico(kindIcon(it.kind))}</div><div class="nm" title="${esc(it.path)}">${esc(it.path.split("/").slice(-2).join("/"))}</div></div>`).join("")).join("")
        || `<div class="empty"><span class="empty-icon">${ico("folder")}</span><div class="empty-title">Biblioteca vacía</div><div class="empty-text">Los planos, diagramas, informes y mini apps que genere el agente aparecerán aquí.</div></div>`;
    }, 250);
  }

  // ---------------------------------------------------------------- navegación (vista principal y paneles móviles)
  function setView(v) {
    state.view = v; document.body.dataset.view = v;
    $$(".side-nav .nav-item[data-view]").forEach((b) => b.classList.toggle("on", b.dataset.view === v));
    if (v === "apps") loadApps();
  }
  function setPane(p, fromBack) {
    if (p !== state.pane && !fromBack) { // «atrás» en el móvil vuelve al chat en vez de salir de la app
      if (p === "chat") dropLayer("pane");
      else if (!layers.some((l) => l.name === "pane")) pushLayer("pane", () => setPane("chat", true));
    }
    state.pane = p; document.body.dataset.pane = p;
    $$("#bottomNav [data-pane]").forEach((b) => b.classList.toggle("on", b.dataset.pane === p));
    if (p === "viewer") { $("#viewBadge").classList.add("hidden"); if (state.tab === "library") refreshLibrary(); }
    if (p === "apps") setView("apps");
    else if (p === "chat") setView("agent");
  }

  // ---------------------------------------------------------------- mini apps
  async function loadApps(force) { // muestra la caché al instante y la actualiza en segundo plano
    const grid = $("#appsGrid");
    if (state.apps && !force) renderApps(state.apps);
    else grid.innerHTML = '<div class="apps-loading"><span class="spinner spinner-lg"></span></div>';
    let apps;
    try { apps = await api("/api/apps"); } catch (e) { apps = state.apps || []; toast("No se pudo cargar la galería", 3000, "err"); }
    if (JSON.stringify(apps) !== JSON.stringify(state.apps)) { state.apps = apps; renderApps(apps); }
    else if (!state.apps || force) { state.apps = apps; renderApps(apps); }
  }
  function renderApps(apps) {
    const n = $("#appsCount"); n.textContent = apps.length; n.classList.toggle("hidden", !apps.length);
    if (!apps.length) {
      $("#appsGrid").innerHTML = `<div class="empty"><span class="empty-icon">${ico("apps")}</span><div class="empty-title">Aún no hay mini apps</div>
        <div class="empty-text">Las mini apps son herramientas a medida que el agente crea para ti: calculadoras, paneles fotográficos, conversores… Pídele una describiendo lo que repites a menudo.</div>
        <button type="button" class="btn btn-primary mt-3" data-tpl="app">${ico("sparkle")}Pedir una mini app</button></div>`;
      return;
    }
    const isEmoji = (s) => s && !/^[a-z-]+$/i.test(s);
    const card = (a, i) => {
      const icon = isEmoji(a.icon) ? esc(a.icon) : ico("apps");
      return `<button type="button" class="app-card" data-app="${i}"${a.url ? "" : ' disabled title="Esta app se ejecuta en el equipo anfitrión"'}>
        <div class="app-card-top"><span class="app-ico">${icon}</span><div class="grow"><b>${esc(a.name)}</b></div>${a.uses_ai ? `<span class="badge badge-accent">${ico("sparkle", "icon-sm")}IA</span>` : ""}</div>
        <p>${esc(a.description || "Sin descripción.")}</p>
        <div class="app-foot">${a.builtin ? "" : '<span class="chip chip-accent">Mía</span>'}${a.kind !== "web" ? `<span class="chip chip-warn">${esc(a.kind)}</span>` : ""}</div></button>`;
    };
    // Búsqueda solo cuando la galería crece (más de 8 apps)
    $("#appsSearchWrap").classList.toggle("hidden", apps.length <= 8);
    const q = (state.appsQuery || "").trim().toLowerCase();
    const items = apps.map((a, i) => ({ a: a, i: i })).filter((x) => !q || (x.a.name + " " + (x.a.description || "") + " " + (x.a.category || "")).toLowerCase().indexOf(q) >= 0);
    if (!items.length) { $("#appsGrid").innerHTML = `<div class="empty"><span class="empty-icon">${ico("search")}</span><div class="empty-title">Sin resultados</div><div class="empty-text">Ninguna mini app coincide con «${esc(q)}».</div></div>`; return; }
    // «Frecuentes» arriba (por aperturas en este dispositivo); el resto, agrupado por categoría
    const used = counts("apps:count");
    const freq = q ? [] : items.filter((x) => used[x.a.slug] > 0).sort((x, y) => used[y.a.slug] - used[x.a.slug]).slice(0, 4);
    const rest = items.filter((x) => freq.indexOf(x) < 0);
    const groups = {}; const order = [];
    rest.forEach((x) => { const c = x.a.category || "General"; if (!groups[c]) { groups[c] = []; order.push(c); } groups[c].push(x); });
    const section = (title, icon, list) => `<div class="apps-group"><span class="apps-group-title">${icon ? ico(icon, "icon-sm") : ""}${esc(title)}</span><span class="n">${list.length}</span></div>` + list.map((x) => card(x.a, x.i)).join("");
    $("#appsGrid").innerHTML = (freq.length ? section("Frecuentes", "star", freq) : "") +
      (order.length === 1 && !freq.length ? rest.map((x) => card(x.a, x.i)).join("") : order.map((c) => section(c, null, groups[c])).join(""));
  }
  $("#appsSearch").addEventListener("input", (e) => { state.appsQuery = e.target.value; if (state.apps) renderApps(state.apps); });
  function openApp(a) {
    if (!a.url) return;
    bump("apps:count", a.slug);
    state.app = a;
    $("#appName").textContent = a.name;
    $("#appIcon").innerHTML = a.icon && !/^[a-z-]+$/i.test(a.icon) ? esc(a.icon) : ico("apps");
    $("#appOpen").href = a.url;
    // location.replace: la mini app no añade entradas al historial (el botón «atrás» sigue cerrando capas)
    const fr = $("#appIframe");
    try { fr.contentWindow.location.replace(a.url); } catch (e) { fr.src = a.url; }
    $("#appsGallery").classList.add("hidden"); $("#appFrame").classList.remove("hidden");
    document.body.classList.add("app-open");
    if (isMobile()) setPane("apps"); else setView("apps");
    if (!layers.some((l) => l.name === "app")) pushLayer("app", () => closeApp(true));
  }
  function closeApp(fromBack) {
    if (!state.app) return;
    state.app = null;
    if (!fromBack) dropLayer("app");
    try { $("#appIframe").contentWindow.location.replace("about:blank"); } catch (e) { $("#appIframe").src = "about:blank"; }
    $("#appFrame").classList.add("hidden"); $("#appsGallery").classList.remove("hidden");
    document.body.classList.remove("app-open");
    loadApps(true);
  }
  // Mensajes desde mini apps incrustadas (mismo origen): rellenar el chat o mostrar avisos
  window.addEventListener("message", (e) => {
    if (e.origin !== location.origin || !e.data || typeof e.data.type !== "string") return;
    if (e.data.type === "pixagent:compose") {
      composeFrom(String(e.data.text || ""), Array.isArray(e.data.attachments) ? e.data.attachments : []);
    } else if (e.data.type === "pixagent:toast") toast(String(e.data.text || ""), 3000);
  });
  function composeFrom(text, attachments) {
    if (isMobile()) setPane("chat"); else setView("agent");
    const inp = $("#input");
    if (text) { inp.value = text; inp.dispatchEvent(new Event("input")); }
    (attachments || []).forEach((f) => { if (typeof f === "string" && f) addPending(f); });
    if (!isTouch) { inp.focus(); inp.selectionStart = inp.selectionEnd = inp.value.length; }
  }

  // ---------------------------------------------------------------- sesiones
  async function loadSessions() {
    const list = await api("/api/sessions");
    $("#sessions").innerHTML = list.map((s) => `<li data-sid="${esc(s.id)}" class="${s.id === state.session ? "on" : ""}"><span class="nm">${esc(s.title)}</span><button type="button" class="del" data-del="${esc(s.id)}" aria-label="Borrar sesión">${ico("trash", "icon-sm")}</button></li>`).join("")
      || '<li class="empty-sessions">Todavía no hay sesiones.</li>';
    const cur = list.find((s) => s.id === state.session);
    $("#sessionTitle").textContent = cur ? cur.title : "Nueva sesión";
  }
  async function openSession(sid) {
    let d;
    try { d = await api("/api/sessions/" + sid + "?limit=" + (state.saveData ? 60 : 160)); } catch (e) { d = null; }
    if (!d || !d.transcript) { toast("Esa sesión ya no existe", 3000, "warn"); newSession(); return false; }
    state.session = sid; state.lastDeliverable = null; state.question = null; endStream(); setWaiting(false); rememberSession();
    $("#messages").innerHTML = d.truncated ? '<div class="msg note">Mensajes anteriores ocultos</div>' : "";
    const answered = {};
    d.transcript.forEach((ev) => { if (ev.type === "answer") answered[ev.id] = ev.text || ""; });
    d.transcript.forEach((ev) => {
      if (ev.type === "user") addUser(ev.text, ev.attachments);
      else if (ev.type === "assistant") addMsg("assistant", md(ev.text));
      else if (ev.type === "tool_end") { if (ev.name === "ask_user") return; addTool({ id: ev.id, name: ev.name, input: {} }); finishTool(ev, false); }
      else if (ev.type === "error") addError(ev.text);
      else if (ev.type === "status" && ev.text) addMsg("note", esc(ev.text));
      else if (ev.type === "question") {
        addQuestion(ev, false);
        // respondida → vista resuelta; sin respuesta y el agente ya no espera → cerrada
        if (ev.id in answered) resolveQuestion(ev.id, answered[ev.id] === "(sin respuesta)" ? null : answered[ev.id]);
        else if (!d.running) resolveQuestion(ev.id, null);
      }
    });
    // si lo último que pasó fue un deshacer, no ofrecerlo otra vez hasta el próximo turno
    const lastEv = d.transcript[d.transcript.length - 1];
    state.undone = !!(lastEv && lastEv.type === "status" && /^Cambios deshechos/.test(lastEv.text || ""));
    renderTodos(d.todos); setRunning(!!d.running); if (state.question) setWaiting(true); loadSessions();
    if (state.lastDeliverable) openFile(state.lastDeliverable, true); // último resultado en el visor
    if (isMobile()) setPane("chat"); else setView("agent");
    $("#messages").scrollTop = $("#messages").scrollHeight;
    return true;
  }
  function newSession() {
    state.session = null; state.lastDeliverable = null; state.undone = false; state.question = null; endStream(); setWaiting(false); rememberSession();
    showWelcome(); renderTodos([]); setRunning(false); loadSessions();
    if (isMobile()) setPane("chat"); else setView("agent");
  }

  // ---------------------------------------------------------------- capas y botón «atrás» (Android, gesto atrás, Alt+←)
  // Cada capa abierta (modal, menú, mini app, panel móvil) añade una entrada al historial; «atrás» cierra la
  // capa superior en vez de sacar al usuario de la app.
  const layers = [];
  let backPending = 0; // history.back() programáticos aún sin su popstate: evita carreras al cerrar una capa y abrir otra
  function pushLayer(name, close) {
    const entry = { name: name, close: close };
    layers.push(entry);
    const push = () => { if (layers.indexOf(entry) < 0) return; try { history.pushState({ layer: layers.indexOf(entry) + 1 }, ""); } catch (e) { /* sin historial */ } };
    if (backPending > 0) setTimeout(push, 40); else push();
  }
  function dropLayer(name) { // cierre programático: quita la capa y retrocede en el historial si era la última
    const i = layers.map((l) => l.name).lastIndexOf(name);
    if (i < 0) return false;
    const wasTop = i === layers.length - 1;
    layers.splice(i, 1);
    if (wasTop && history.state && history.state.layer === layers.length + 1) {
      backPending++; setTimeout(() => { backPending = Math.max(0, backPending - 1); }, 600);
      try { history.back(); } catch (e) { backPending = Math.max(0, backPending - 1); }
    }
    return true;
  }
  window.addEventListener("popstate", (e) => {
    if (backPending > 0) { backPending--; return; } // retroceso programático ya aplicado
    const depth = (e.state && e.state.layer) || 0;
    while (layers.length > depth) { const l = layers.pop(); try { l.close(); } catch (err) { /* ya cerrada */ } }
  });
  try { history.replaceState({ layer: 0 }, ""); } catch (e) { /* nada */ }

  // Modales accesibles: foco atrapado dentro y devuelto al cerrar; Esc y «atrás» cierran
  const FOCUSABLE = 'button:not([disabled]), a[href], input:not([disabled]):not([type=hidden]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';
  function openModal(m, onClose) {
    if (!m.classList.contains("hidden")) return;
    m._prevFocus = document.activeElement; m._onClose = onClose || null;
    m.classList.remove("hidden");
    pushLayer("modal:" + m.id, () => finishModal(m, true));
    const f = $$(FOCUSABLE).filter((el) => m.contains(el) && el.offsetParent !== null);
    const first = m.querySelector("[autofocus]") || f[0];
    if (first) setTimeout(() => first.focus(), 30);
  }
  function finishModal(m, fromBack) {
    if (m.classList.contains("hidden")) return;
    m.classList.add("hidden");
    if (!fromBack) dropLayer("modal:" + m.id);
    const cb = m._onClose; m._onClose = null; if (cb) cb();
    const p = m._prevFocus; m._prevFocus = null;
    if (p && p.focus && document.contains(p)) setTimeout(() => p.focus(), 0);
  }
  const closeModal = (m) => finishModal(m, false);
  document.addEventListener("keydown", (e) => { // trampa de foco con Tab
    if (e.key !== "Tab") return;
    const m = $$(".modal:not(.hidden)").pop(); if (!m) return;
    const f = $$(FOCUSABLE).filter((el) => m.contains(el) && el.offsetParent !== null); if (!f.length) return;
    if (e.shiftKey && (document.activeElement === f[0] || !m.contains(document.activeElement))) { e.preventDefault(); f[f.length - 1].focus(); }
    else if (!e.shiftKey && document.activeElement === f[f.length - 1]) { e.preventDefault(); f[0].focus(); }
  });

  // ---------------------------------------------------------------- aprobación y confirmación
  function askApproval(ev) {
    const m = $("#approval"); m.dataset.id = ev.id;
    $("#approvalName").textContent = toolLabel(ev.name);
    $("#approvalBody").textContent = ev.summary;
    let answered = false;
    const done = (ok) => { if (answered) return; answered = true; send({ type: "approve", id: ev.id, ok: ok }); closeModal(m); };
    openModal(m, () => done(false)); // cerrar con «atrás» o Esc equivale a rechazar
    $("#allowBtn").onclick = () => done(true); $("#denyBtn").onclick = () => done(false);
    buzz(60);
  }
  function askConfirm(title, text, label, icon) {
    return new Promise((resolve) => {
      const m = $("#confirm");
      $("#confirmTitle").textContent = title; $("#confirmText").textContent = text || "";
      const yes = $("#confirmYes"); yes.textContent = label || "Borrar";
      yes.className = "btn " + (icon ? "btn-primary" : "btn-danger");
      $("#confirmIcon").className = "modal-icon" + (icon ? "" : " danger"); $("#confirmIcon").innerHTML = ico(icon || "trash");
      let result = false;
      openModal(m, () => resolve(result));
      const close = (v) => { result = v; closeModal(m); };
      yes.onclick = () => close(true); $("#confirmNo").onclick = () => close(false);
      m.onclick = (e) => { if (e.target === m) close(false); };
    });
  }

  // ---------------------------------------------------------------- menú contextual (clic derecho · pulsación larga)
  function showMenu(items, x, y) {
    hideMenu();
    const menu = document.createElement("div"); menu.className = "ctx-menu"; menu.id = "ctxMenu"; menu.setAttribute("role", "menu");
    menu.innerHTML = items.map((it, i) => it === "-" ? '<hr>' : `<button type="button" role="menuitem" data-i="${i}" class="${it.danger ? "danger" : ""}" ${it.disabled ? "disabled" : ""}>${it.icon ? ico(it.icon, "icon-sm") : ""}<span>${esc(it.label)}</span></button>`).join("");
    if (isMobile()) menu.classList.add("sheet");
    document.body.appendChild(menu);
    if (!isMobile()) {
      const r = menu.getBoundingClientRect();
      menu.style.left = Math.max(8, Math.min(x, innerWidth - r.width - 8)) + "px";
      menu.style.top = Math.max(8, Math.min(y, innerHeight - r.height - 8)) + "px";
    }
    menu.addEventListener("click", (e) => { const b = e.target.closest("[data-i]"); if (!b) return; const it = items[+b.dataset.i]; hideMenu(); if (it && it.onClick) it.onClick(); });
    menu.addEventListener("keydown", (e) => {
      const bs = $$("#ctxMenu button:not([disabled])"), i = bs.indexOf(document.activeElement);
      if (e.key === "ArrowDown") { e.preventDefault(); (bs[i + 1] || bs[0]).focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); (bs[i - 1] || bs[bs.length - 1]).focus(); }
    });
    menu._prevFocus = document.activeElement;
    pushLayer("menu", () => hideMenu(true));
    setTimeout(() => { const b = menu.querySelector("button:not([disabled])"); if (b && !isTouch) b.focus(); }, 20);
    if (isTouch) buzz(12);
  }
  function hideMenu(fromBack) {
    const m = $("#ctxMenu"); if (!m) return;
    m.remove(); if (!fromBack) dropLayer("menu");
    const p = m._prevFocus; if (p && p.focus && document.contains(p) && !isTouch) p.focus();
  }
  document.addEventListener("pointerdown", (e) => { if ($("#ctxMenu") && !e.target.closest("#ctxMenu")) hideMenu(); }, true);
  window.addEventListener("resize", () => hideMenu());
  function fileMenuItems(rel) {
    const items = [
      { label: "Abrir en el visor", icon: "eye", onClick: () => openFile(rel) },
      { label: "Adjuntar al mensaje", icon: "clip", onClick: () => { addPending(rel); toast("Añadido como adjunto", 2000, "ok"); if (isMobile()) setPane("chat"); } },
    ];
    if (state.pixpin) items.push({ label: "Fijar en PixPin", icon: "pin", onClick: async () => { const j = await api("/api/pixpin/pin", { files: [rel], session: state.session }); toast(j.ok ? "Fijado en PixPin" : j.error, j.ok ? 2000 : 6000, j.ok ? "ok" : "err"); } });
    if (navigator.share) items.push({ label: "Compartir…", icon: "share", onClick: () => shareFile(rel) });
    items.push("-", { label: "Abrir en pestaña nueva", icon: "external", onClick: () => window.open(fileUrl(rel), "_blank", "noopener") },
      { label: "Descargar", icon: "download", onClick: () => { const a = document.createElement("a"); a.href = fileUrl(rel); a.download = baseName(rel); document.body.appendChild(a); a.click(); a.remove(); } });
    return items;
  }
  function sessionMenuItems(li) {
    const sid = li.dataset.sid, title = li.querySelector(".nm").textContent;
    return [
      { label: "Abrir sesión", icon: "chat", onClick: () => openSession(sid) },
      "-",
      { label: "Borrar sesión", icon: "trash", danger: true, onClick: async () => {
        if (await askConfirm("¿Borrar esta sesión?", "«" + title + "» se eliminará de forma permanente.")) {
          await fetch("/api/sessions/" + sid, { method: "DELETE" });
          if (state.session === sid) newSession(); loadSessions(); toast("Sesión borrada", 2000, "ok");
        } } },
    ];
  }
  function contextFor(target) {
    const li = target.closest("#sessions li[data-sid]"); if (li) return sessionMenuItems(li);
    const f = target.closest("[data-open]"); if (f && !target.closest("#viewerBody")) return fileMenuItems(f.dataset.open);
    if (target.closest("#viewerBody") && state.current) return fileMenuItems(state.current);
    return null;
  }
  let lpTimer = null, lpStart = null, lpFired = 0;
  document.addEventListener("contextmenu", (e) => {
    if (Date.now() - lpFired < 1200) { e.preventDefault(); return; } // ya lo abrió la pulsación larga
    const items = contextFor(e.target); if (!items) return;
    e.preventDefault(); showMenu(items, e.clientX, e.clientY);
  });
  // Pulsación larga (táctil y lápiz): mismo menú que el clic derecho, sin pelear con el scroll
  document.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" || !contextFor(e.target)) return;
    clearTimeout(lpTimer); lpStart = { x: e.clientX, y: e.clientY, t: e.target };
    lpTimer = setTimeout(() => { lpFired = Date.now(); const items = contextFor(lpStart.t); if (items) showMenu(items, lpStart.x, lpStart.y); }, 480);
  }, { passive: true });
  document.addEventListener("pointermove", (e) => { if (lpStart && Math.hypot(e.clientX - lpStart.x, e.clientY - lpStart.y) > 10) { clearTimeout(lpTimer); lpStart = null; } }, { passive: true });
  ["pointerup", "pointercancel"].forEach((ev) => document.addEventListener(ev, () => { clearTimeout(lpTimer); lpStart = null; }, { passive: true }));
  document.addEventListener("click", (e) => { if (Date.now() - lpFired < 600 && !e.target.closest("#ctxMenu")) { e.stopPropagation(); e.preventDefault(); } }, true); // el toque que abrió el menú no "hace clic"
  async function shareFile(rel) {
    try {
      const blob = await (await fetch(fileUrl(rel))).blob();
      const file = new File([blob], baseName(rel), { type: blob.type });
      if (navigator.canShare && navigator.canShare({ files: [file] })) await navigator.share({ files: [file], title: file.name });
      else await navigator.share({ title: file.name, url: location.origin + fileUrl(rel) });
    } catch (err) { if (err.name !== "AbortError") toast("No se pudo compartir", 3000, "err"); }
  }

  // ---------------------------------------------------------------- teclado (Windows: Ctrl · Mac: ⌘)
  const isMac = /Mac|iPhone|iPad|iPod/.test(navigator.platform) || /Mac/.test(navigator.userAgent);
  const MOD = isMac ? "⌘" : "Ctrl";
  const mod = (e) => (isMac ? e.metaKey : e.ctrlKey) && !e.altKey;
  const inField = (el) => el && (el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT" || el.isContentEditable);
  state.enterSend = localGet("enterSend") == null ? !isTouch : localGet("enterSend") === "1";
  const SHORTCUTS = [
    ["Mensajes", [[MOD + " K", "Buscar o cambiar de sesión"], [MOD + " N", "Nueva sesión"], ["Intro", "Enviar (si está activado en «Más ajustes»)"], [MOD + " Intro", "Enviar siempre"], ["Mayús Intro", "Salto de línea"], [MOD + " U", "Adjuntar archivos"], ["/", "Escribir en el mensaje"], ["Esc", "Cerrar menú o ventana · detener el agente"]]],
    ["Navegación", [["Alt 1", "Agente"], ["Alt 2", "Mini apps"], ["Alt 3", "Resultado / Biblioteca"], ["Alt 4", "Informes"], ["?", "Esta ayuda"]]],
    ["Visor", [["Rueda · pellizco", "Zoom hacia el cursor"], ["Arrastrar", "Mover la imagen"], ["Doble clic", "Ajustar ↔ ampliar"], ["+ − 0 1", "Acercar · alejar · ajustar · tamaño real"], ["Flechas", "Desplazar"]]],
  ];
  function showShortcuts() {
    const m = $("#shortcuts");
    $("#shortcutsBody").innerHTML = SHORTCUTS.map(([g, rows]) => `<div class="sc-group"><div class="sc-title">${esc(g)}</div>${rows.map(([k, d]) => `<div class="sc-row"><span>${esc(d)}</span><span class="sc-keys">${k.split(" ").map((p) => `<span class="kbd">${esc(p)}</span>`).join("")}</span></div>`).join("")}</div>`).join("");
    openModal(m);
  }
  // Paleta de sesiones (Ctrl/⌘+K): filtrar, flechas, Intro
  let palItems = [];
  async function showPalette() {
    const m = $("#palette"), inp = $("#paletteInput");
    inp.value = ""; $("#paletteList").innerHTML = '<div class="pal-empty">Cargando…</div>';
    openModal(m);
    palItems = await api("/api/sessions");
    renderPalette("");
  }
  function renderPalette(q) {
    q = q.trim().toLowerCase();
    const list = palItems.filter((s) => !q || s.title.toLowerCase().indexOf(q) >= 0).slice(0, 30);
    $("#paletteList").innerHTML = `<button type="button" class="pal-item ${!list.length || q ? "on" : ""}" data-pal="new">${ico("plus", "icon-sm")}<span>Nueva sesión${q ? ": «" + esc(q) + "»" : ""}</span><span class="kbd">${MOD} N</span></button>` +
      list.map((s, i) => `<button type="button" class="pal-item ${i === 0 && !q ? "on" : ""}" data-pal="${esc(s.id)}">${ico("chat", "icon-sm")}<span>${esc(s.title)}</span></button>`).join("");
  }
  $("#paletteInput").addEventListener("input", (e) => renderPalette(e.target.value));
  $("#paletteInput").addEventListener("keydown", (e) => {
    const items = $$("#paletteList .pal-item"), i = items.findIndex((x) => x.classList.contains("on"));
    if (e.key === "ArrowDown" || e.key === "ArrowUp") { e.preventDefault(); const j = Math.max(0, Math.min(items.length - 1, i + (e.key === "ArrowDown" ? 1 : -1))); items.forEach((x, k) => x.classList.toggle("on", k === j)); if (items[j]) items[j].scrollIntoView({ block: "nearest" }); }
    else if (e.key === "Enter") { e.preventDefault(); const it = items[i] || items[0]; if (it) it.click(); }
  });
  $("#paletteList").addEventListener("click", (e) => {
    const it = e.target.closest("[data-pal]"); if (!it) return;
    const q = $("#paletteInput").value.trim();
    closeModal($("#palette"));
    if (it.dataset.pal === "new") { newSession(); if (q) composeFrom(q, []); } else openSession(it.dataset.pal);
  });
  document.addEventListener("keydown", (e) => {
    if (e.isComposing) return;
    const field = inField(e.target);
    if (e.key === "Escape") {
      if ($("#ctxMenu")) { hideMenu(); return; }
      const m = $$(".modal:not(.hidden)").pop();
      if (m) { if (m.id === "confirm") $("#confirmNo").click(); else closeModal(m); return; }
      if (state.app) { closeApp(); return; }
      if (state.running && !field) { send({ type: "cancel", session: state.session }); toast("Deteniendo…", 1500); return; }
      if (field) e.target.blur();
      return;
    }
    if (mod(e) && !e.shiftKey && (e.key === "k" || e.key === "K")) { e.preventDefault(); showPalette(); return; }
    if ((mod(e) || e.altKey) && !e.shiftKey && (e.key === "n" || e.key === "N")) { e.preventDefault(); newSession(); if (!isTouch) $("#input").focus(); return; }
    if (mod(e) && (e.key === "u" || e.key === "U")) { e.preventDefault(); $("#fileInput").click(); return; }
    if (e.altKey && !mod(e) && /^[1-4]$/.test(e.key)) {
      e.preventDefault();
      if (e.key === "1") { if (isMobile()) setPane("chat"); else setView("agent"); if (!isTouch) $("#input").focus(); }
      else if (e.key === "2") { if (isMobile()) setPane("apps"); else setView("apps"); }
      else if (e.key === "3") { if (isMobile()) setPane("viewer"); else { if (state.view !== "agent") setView("agent"); switchTab(state.tab === "view" ? "library" : "view"); } }
      else location.href = "/reports";
      return;
    }
    // Pregunta pendiente: 1–4 eligen opción e Intro envía la selección (con el compositor vacío o sin foco en un campo)
    if (state.question && !mod(e) && !e.altKey && (!field || (e.target.id === "input" && !e.target.value))) {
      if (/^[1-4]$/.test(e.key)) { e.preventDefault(); pickOption(+e.key - 1); return; }
      if (e.key === "Enter" && state.question.multi && !e.shiftKey) { e.preventDefault(); sendSelection(); return; }
    }
    if (field) return;
    if (e.key === "/" && !mod(e)) { e.preventDefault(); if (isMobile()) setPane("chat"); $("#input").focus(); return; }
    if (e.key === "?" || (e.shiftKey && e.key === "/")) { e.preventDefault(); showShortcuts(); return; }
  });
  $("#shortcutsBtn").onclick = showShortcuts;
  // Los atajos globales también funcionan con el foco dentro de una mini app (mismo origen)
  $("#appIframe").addEventListener("load", () => {
    try {
      const doc = $("#appIframe").contentDocument; if (!doc) return;
      doc.addEventListener("keydown", (e) => {
        const relay = e.key === "Escape" || (e.altKey && /^[1-4nN]$/.test(e.key)) || (mod(e) && /^[kKnN]$/.test(e.key));
        if (!relay) return;
        e.preventDefault();
        document.dispatchEvent(new KeyboardEvent("keydown", { key: e.key, code: e.code, altKey: e.altKey, ctrlKey: e.ctrlKey, metaKey: e.metaKey, shiftKey: e.shiftKey, bubbles: true }));
      });
    } catch (err) { /* otro origen */ }
  });
  $("#enterSend").checked = state.enterSend;
  $("#enterSend").onchange = (e) => { state.enterSend = e.target.checked; localSet("enterSend", e.target.checked ? "1" : "0"); renderComposerHint(); };
  function renderComposerHint() {
    $("#composerHint").innerHTML = state.enterSend
      ? `<span class="kbd">Intro</span> enviar · <span class="kbd">Mayús</span>+<span class="kbd">Intro</span> salto de línea`
      : `<span class="kbd">${MOD}</span>+<span class="kbd">Intro</span> enviar`;
  }
  renderComposerHint();
  $$(".mod-key").forEach((el) => { el.textContent = MOD; });

  // ---------------------------------------------------------------- teclado virtual (Android/iOS): el compositor no queda tapado
  if (window.visualViewport) {
    const vv = window.visualViewport;
    const onVV = () => {
      if (!isMobile()) { document.body.classList.remove("kb-open"); return; }
      const kb = window.innerHeight - vv.height - vv.offsetTop;
      const open = kb > 120;
      document.body.classList.toggle("kb-open", open);
      document.documentElement.style.setProperty("--vvh", open ? vv.height + "px" : "");
      if (open) { window.scrollTo(0, 0); setTimeout(scroll, 60); }
    };
    vv.addEventListener("resize", onVV); vv.addEventListener("scroll", onVV);
  }

  // ---------------------------------------------------------------- tema
  function applyTheme(t) {
    if (t === "dark" || t === "light") document.documentElement.setAttribute("data-theme", t);
    else document.documentElement.removeAttribute("data-theme");
    localSet("theme", t);
    $$("#themeSeg button").forEach((b) => b.classList.toggle("on", b.dataset.theme === t));
  }
  applyTheme(localGet("theme") || "system");

  // ---------------------------------------------------------------- eventos de la interfaz
  const clientId = Math.random().toString(36).slice(2);
  $("#composer").addEventListener("submit", (e) => {
    e.preventDefault();
    const text = $("#input").value.trim();
    if (state.question) { // lo que se escribe mientras el agente pregunta es la respuesta
      if (!text) { if (state.question.multi) sendSelection(); return; }
      if (answerQuestion(text)) { $("#input").value = ""; fitInput(); }
      return;
    }
    if (!text && !state.pending.length) return;
    if (state.running) { toast("El agente está trabajando…", 2200, "warn"); return; }
    if (!send({ type: "chat", session: state.session, text: text, attachments: state.pending, client: clientId })) { toast("Sin conexión; reintentando…", 3000, "warn"); connect(); return; }
    try { sessionStorage.setItem("pix:turnseq", String(state.lastSeq)); } catch (e) { /* modo privado */ }
    addUser(text, state.pending);
    state.pending = []; renderPending(); $("#input").value = ""; fitInput(); setRunning(true); setStatus("Enviando…");
    if (isTouch) $("#input").blur(); // cerrar el teclado para ver la respuesta
  });
  $("#input").addEventListener("keydown", (e) => {
    if (e.key !== "Enter" || e.isComposing) return;
    const modEnter = e.ctrlKey || e.metaKey;
    if (modEnter || (state.enterSend && !e.shiftKey && !isTouch)) { e.preventDefault(); $("#composer").requestSubmit(); }
  });
  // El compositor crece con el texto (y con el placeholder largo, para que no se corte)
  function fitInput() { const t = $("#input"); t.style.height = "auto"; t.style.height = Math.min(200, t.scrollHeight) + "px"; }
  $("#input").addEventListener("input", fitInput);
  window.addEventListener("resize", () => { if (!$("#input").value) fitInput(); });
  fitInput();
  $("#fileInput").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });
  $("#camInput").addEventListener("change", (e) => { uploadFiles(e.target.files); e.target.value = ""; });
  document.addEventListener("paste", (e) => {
    const files = Array.from((e.clipboardData && e.clipboardData.files) || []);
    if (files.length) { e.preventDefault(); uploadFiles(files); toast("Imagen pegada", 2000, "ok"); }
  });
  const chat = $("#chat");
  chat.addEventListener("dragover", (e) => { e.preventDefault(); $("#dropHint").classList.remove("hidden"); });
  chat.addEventListener("dragleave", (e) => { if (!chat.contains(e.relatedTarget)) $("#dropHint").classList.add("hidden"); });
  chat.addEventListener("drop", (e) => { e.preventDefault(); $("#dropHint").classList.add("hidden"); uploadFiles(e.dataTransfer.files); });

  document.addEventListener("click", async (e) => {
    const t = e.target;
    const close = t.closest("[data-close]"); if (close) { closeModal($(close.dataset.close)); return; }
    if (t.classList.contains("modal") && (t.id === "shortcuts" || t.id === "palette")) { closeModal(t); return; }
    const o = t.closest("[data-open]"); if (o && !t.closest("#viewerBody")) { openFile(o.dataset.open); return; }
    const rm = t.closest("[data-rm]"); if (rm) { state.pending.splice(+rm.dataset.rm, 1); renderPending(); return; }
    const del = t.closest("[data-del]");
    if (del) {
      e.stopPropagation();
      const title = del.closest("li").querySelector(".nm").textContent;
      if (await askConfirm("¿Borrar esta sesión?", "«" + title + "» se eliminará de forma permanente.")) {
        await fetch("/api/sessions/" + del.dataset.del, { method: "DELETE" });
        if (state.session === del.dataset.del) newSession(); loadSessions(); toast("Sesión borrada", 2000, "ok");
      }
      return;
    }
    const li = t.closest("[data-sid]"); if (li) { openSession(li.dataset.sid); return; }
    if (t.closest("#undoBtn")) { undoLast(); return; }
    const opt = t.closest(".ask-opt"); if (opt && !opt.disabled) { pickOption(+opt.dataset.i); return; }
    if (t.closest(".ask-send")) { sendSelection(); return; }
    if (t.closest("[data-addkey]")) { openKeySettings(); return; }
    if (t.closest("[data-view-apps]")) { if (isMobile()) setPane("apps"); else setView("apps"); return; }
    const tpl = t.closest("[data-tpl]"); if (tpl && TEMPLATES[tpl.dataset.tpl]) { composeFrom(TEMPLATES[tpl.dataset.tpl], []); if (isTouch) $("#input").focus(); return; }
    const pane = t.closest("#bottomNav [data-pane]"); if (pane) { setPane(pane.dataset.pane); return; }
    const nav = t.closest(".side-nav [data-view]"); if (nav) { setView(nav.dataset.view); if (isMobile()) setPane(nav.dataset.view === "apps" ? "apps" : "chat"); return; }
    const card = t.closest("[data-app]"); if (card && state.apps) { openApp(state.apps[+card.dataset.app]); return; }
    const cap = t.closest("[data-capture]");
    if (cap) {
      toast("Pidiendo captura a PixPin…", 2000);
      const j = await api("/api/pixpin/capture", { region: cap.dataset.capture });
      if (j.ok) { addPending(j.file); toast("Captura añadida", 2000, "ok"); if (isMobile()) setPane("chat"); } else toast(j.error, 5000, "err");
      return;
    }
    const tab = t.closest(".viewer-tabs [data-tab]"); if (tab) { switchTab(tab.dataset.tab); return; }
    const th = t.closest("#themeSeg [data-theme]"); if (th) applyTheme(th.dataset.theme);
  });
  $("#newSession").onclick = newSession;
  $("#cancelBtn").onclick = () => send({ type: "cancel", session: state.session });
  $("#appBack").onclick = () => closeApp();
  $("#appsRefresh").onclick = () => loadApps(true);
  $("#attachBtn").onclick = () => { if (state.current) { addPending(state.current); toast("Añadido como adjunto", 2000, "ok"); if (isMobile()) setPane("chat"); } };
  $("#pinBtn").onclick = async () => {
    if (!state.current) return;
    const j = await api("/api/pixpin/pin", { files: [state.current], session: state.session });
    toast(j.ok ? "Fijado en PixPin" : j.error, j.ok ? 2000 : 6000, j.ok ? "ok" : "err");
  };
  // Compartir con la hoja nativa (iOS, iPadOS, Android, macOS Safari, Windows Edge)
  if (navigator.share) {
    $("#shareBtn").classList.remove("hidden");
    $("#shareBtn").onclick = () => { if (state.current) shareFile(state.current); };
  }
  $("#installScripts").onclick = async () => { await api("/api/pixpin/install", {}); toast("Scripts generados en pixpin_scripts/ (ver LEEME.txt)", 5000, "ok"); refreshLibrary(); };
  // Velocidad de respuesta (3 opciones visibles) ↔ nivel de esfuerzo exacto (5 valores, en «Más ajustes»)
  const EFFORT_NAMES = { low: "Bajo", medium: "Medio", high: "Alto", xhigh: "Muy alto", max: "Extremo" };
  function renderEffort(v) {
    $("#effort").value = v;
    $$("#effortSeg [data-effort]").forEach((b) => b.classList.toggle("on", b.dataset.effort === v));
    const custom = !$("#effortSeg .on");
    $("#effortNote").classList.toggle("hidden", !custom);
    if (custom) $("#effortNote").textContent = "Nivel personalizado: " + (EFFORT_NAMES[v] || v) + " (ver «Más ajustes»)";
  }
  function setEffort(v) { renderEffort(v); api("/api/settings", { effort: v }); }
  $("#effortSeg").addEventListener("click", (e) => { const b = e.target.closest("[data-effort]"); if (b) setEffort(b.dataset.effort); });
  $("#effort").onchange = (e) => setEffort(e.target.value);
  // Permisos: auto (confirma terminal) · ask (también Python y PixPin) · full (sin confirmaciones, solo en «Más ajustes»)
  function renderPerm(mode) {
    const full = mode === "full";
    $("#permAsk").checked = mode === "ask"; $("#permAsk").disabled = full;
    $("#permFull").checked = full;
    $("#permShell").textContent = full ? "No" : "Siempre";
    $("#permFullNote").classList.toggle("hidden", !full);
    $(".perm-list").classList.toggle("off", full);
  }
  function setPerm(mode) { renderPerm(mode); api("/api/settings", { permission_mode: mode }); }
  $("#permAsk").onchange = (e) => setPerm(e.target.checked ? "ask" : "auto");
  $("#permFull").onchange = async (e) => {
    if (e.target.checked && !await askConfirm("¿Activar el modo total?", "El agente ejecutará comandos de terminal, Python y PixPin sin pedir confirmación. Puedes volver a desactivarlo aquí mismo.", "Activar", "shield")) { e.target.checked = false; return; }
    setPerm(e.target.checked ? "full" : "auto");
  };
  // ---------------------------------------------------------------- clave de API (primer uso y Ajustes)
  function refreshKey(info) {
    state.apiKey = info || { configured: false, source: "", masked: "" };
    const k = state.apiKey, fromEnv = k.source === "entorno";
    $("#keyDot").className = "dot " + (k.configured ? "dot-ok" : "dot-warn");
    $("#keyStatus").innerHTML = k.configured
      ? (fromEnv ? "Configurada desde la variable de entorno <code>ANTHROPIC_API_KEY</code>" : `Configurada · <span class="mono">${esc(k.masked || "sk-ant-…")}</span>`)
      : "Sin configurar: el agente no puede responder todavía.";
    $("#keyChange span").textContent = k.configured ? "Cambiar" : "Añadir clave";
    $("#keyRemove").classList.toggle("hidden", !(k.configured && !fromEnv));
    renderKeyCard();
  }
  // Tarjeta de bienvenida: solo mientras no haya clave
  function renderKeyCard() {
    const card = $("#keyCard"); if (!card) return;
    const show = !!(state.apiKey && !state.apiKey.configured);
    card.classList.toggle("hidden", !show);
    $("#messages .welcome").classList.toggle("needs-key", show);
    if (show && !$("#keyCardForm .key-form")) mountKeyForm($("#keyCardForm"), { autofocus: !isTouch });
  }
  function mountKeyForm(container, opts) {
    container.innerHTML = ""; container.appendChild($("#keyFormTpl").content.cloneNode(true));
    const form = container.querySelector(".key-form"), inp = form.querySelector(".key-input"), eye = form.querySelector(".key-eye");
    const msg = form.querySelector(".key-msg"), save = form.querySelector(".key-save");
    const setMsg = (text, kind) => { msg.textContent = text || ""; msg.className = "key-msg xs" + (kind ? " key-" + kind : ""); };
    eye.onclick = () => { const show = inp.type === "password"; inp.type = show ? "text" : "password"; eye.setAttribute("aria-pressed", show ? "true" : "false"); eye.setAttribute("aria-label", show ? "Ocultar clave" : "Mostrar clave"); eye.innerHTML = ico(show ? "eye-off" : "eye"); inp.focus(); };
    inp.addEventListener("input", () => setMsg(""));
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      const key = inp.value.trim();
      if (!key) { setMsg("Pega la clave primero.", "err"); inp.focus(); return; }
      save.disabled = true; inp.disabled = true; form.classList.add("busy");
      save.innerHTML = '<span class="spinner"></span><span>Comprobando…</span>'; setMsg("Conectando con Anthropic para verificar la clave (no gasta tokens)…");
      let j;
      try { const r = await fetch("/api/apikey", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: key }) }); j = await r.json(); }
      catch (err) { j = { ok: false, error: "No se pudo contactar con el servidor. Comprueba la conexión e inténtalo de nuevo." }; }
      form.classList.remove("busy");
      if (!j || !j.ok) {
        save.disabled = false; inp.disabled = false; save.innerHTML = ico("check") + "<span>Guardar y comprobar</span>";
        setMsg((j && j.error) || "No se pudo guardar la clave.", "err"); inp.focus(); inp.select();
        return;
      }
      save.innerHTML = ico("check") + "<span>Guardada</span>"; save.classList.add("ok"); setMsg("Clave guardada y verificada. Ya puedes pedirle cosas al agente.", "ok");
      inp.value = "";
      toast("Clave de API guardada", 2600, "ok");
      setTimeout(() => { refreshKey(j); $("#keySettingForm").classList.add("hidden"); if (opts && opts.then) opts.then(); }, 900);
    });
    if (opts && opts.autofocus) setTimeout(() => inp.focus(), 60);
    return form;
  }
  function openKeySettings() {
    const fold = $("#settingsFold"); if (!fold.open) { fold._auto = true; fold.open = true; }
    if (isMobile()) setPane("sidebar");
    const box = $("#keySettingForm"); box.classList.remove("hidden");
    if (!box.querySelector(".key-form")) mountKeyForm(box, { autofocus: !isTouch, then: () => { if (isMobile()) setPane("chat"); } });
    else setTimeout(() => { const i = box.querySelector(".key-input"); if (i && !isTouch) i.focus(); }, 60);
    setTimeout(() => { try { $("#keySetting").scrollIntoView({ block: "start", behavior: "smooth" }); } catch (e) { $("#keySetting").scrollIntoView(); } }, 220);
  }
  $("#keyChange").onclick = () => { const box = $("#keySettingForm"); if (!box.classList.contains("hidden") && box.querySelector(".key-form")) { box.classList.add("hidden"); return; } openKeySettings(); };
  $("#keyRemove").onclick = async () => {
    if (!await askConfirm("¿Quitar la clave de API?", "El agente dejará de responder hasta que añadas otra. Las mini apps seguirán funcionando.", "Quitar")) return;
    let j; try { j = await fetch("/api/apikey", { method: "DELETE" }).then((r) => r.json()); } catch (e) { j = null; }
    if (!j || !j.ok) { toast("No se pudo quitar la clave", 3500, "err"); return; }
    refreshKey(j); $("#keySettingForm").classList.add("hidden"); toast("Clave quitada", 2200, "ok");
  };

  $("#saveData").checked = state.saveData;
  $("#saveData").onchange = (e) => { state.saveData = e.target.checked; localSet("saveData", e.target.checked ? "1" : "0"); refreshLibrary(); };
  // En escritorio las secciones plegables recuerdan su estado
  $$(".side-fold").forEach((d) => {
    const k = "fold:" + d.id, v = localGet(k);
    if (v === "1") d.open = true; else if (v === "0") d.open = false;
    d.addEventListener("toggle", (e) => { if (e.isTrusted === false || d._auto) { d._auto = false; return; } localSet(k, d.open ? "1" : "0"); });
  });

  // Instalación como app (PWA)
  let deferredInstall = null;
  window.addEventListener("beforeinstallprompt", (e) => { e.preventDefault(); deferredInstall = e; $("#installApp").classList.remove("hidden"); });
  $("#installApp").onclick = async () => {
    if (deferredInstall) { deferredInstall.prompt(); deferredInstall = null; $("#installApp").classList.add("hidden"); }
    else if (isIOS) toast("En Safari: Compartir → «Añadir a pantalla de inicio»", 6000);
  };
  if (isIOS && !navigator.standalone) $("#installApp").classList.remove("hidden");
  if ("serviceWorker" in navigator && window.isSecureContext) navigator.serviceWorker.register("/sw.js").catch(() => {});

  // ---------------------------------------------------------------- inicio
  showWelcome();
  (async () => {
    let st;
    try { st = await api("/api/status"); } catch (e) { toast("No se pudo contactar con el servidor", 5000, "err"); connect(); return; }
    state.lastSeq = st.seq; state.maxPx = st.upload_max_px || 3200; state.pixpin = !!st.pixpin;
    renderEffort(st.effort); renderPerm(st.permission_mode); refreshKey(st.api_key);
    $("#pixpinDot").className = "dot " + (st.pixpin ? "dot-ok" : "dot-danger");
    $("#pixpinSum").textContent = st.pixpin ? "" : "No conectado";
    $("#pixpinStatus").innerHTML = st.pixpin
      ? `<span class="dot dot-ok" style="margin-top:5px"></span><span>PixPin conectado${st.is_host ? "" : " en el equipo anfitrión"}</span>`
      : `<span class="dot dot-danger" style="margin-top:5px"></span><span>PixPin no disponible${st.is_host ? ". Configura <code>pixpin_path</code> en los ajustes." : " en el anfitrión."}</span>`;
    // PixPin plegado si no está conectado; si lo está, abierto salvo que el usuario lo haya cerrado antes
    const pf = $("#pixpinFold"), want = st.pixpin ? localGet("fold:pixpinFold") !== "0" : false;
    if (pf.open !== want) { pf._auto = true; pf.open = want; }
    if (!st.pixpin) { $$("[data-capture]").forEach((b) => b.classList.add("hidden")); $("#pinBtn").classList.add("hidden"); }
    else if (st.is_host) $("#capBtn").classList.remove("hidden");
    $("#wsInfo").textContent = st.workspace + " · v" + st.version; $("#wsInfo").title = "Workspace: " + st.workspace;
    // Recarga a mitad de tarea: volver a la sesión de esta pestaña si el agente sigue trabajando o esperando una
    // respuesta. El historial guardado se pinta desde el archivo; lo que aún no se guardó (el turno en curso, la
    // pregunta pendiente) se recupera pidiendo al servidor que reenvíe los eventos desde que empezó el turno.
    let prevSid = null, turnSeq = 0;
    try { prevSid = sessionStorage.getItem("pix:sid"); turnSeq = +sessionStorage.getItem("pix:turnseq") || 0; } catch (e) { /* modo privado */ }
    if (prevSid) {
      let d = null, exists = false;
      try { // la lista primero: evita un 404 ruidoso si el turno en curso aún no se ha guardado
        const list = await api("/api/sessions");
        exists = list.some((x) => x.id === prevSid);
        if (exists) d = await api("/api/sessions/" + prevSid + "?limit=1");
      } catch (e) { d = null; }
      const from = turnSeq > 0 ? turnSeq : Math.max(0, st.seq - 1500);
      if (exists && d.running) { await openSession(prevSid); state.replay = "questions"; state.lastSeq = Math.min(state.lastSeq, from); }
      else if (!exists) { state.session = prevSid; state.replay = "full"; state.lastSeq = from; clearWelcome(); setRunning(true); setStatus("Recuperando la sesión…"); }
      else rememberSession();
    }
    connect(); loadSessions(); if (!isMobile() && state.tab === "library") refreshLibrary();
    const q = new URLSearchParams(location.search);
    if (q.get("shared") === "1") toast("Archivos compartidos recibidos", 3000, "ok");
    if (q.get("compose")) composeFrom(q.get("compose"), []);
    if (q.get("view") === "apps") { if (isMobile()) setPane("apps"); else setView("apps"); }
    if (q.has("shared") || q.has("compose") || q.has("view")) history.replaceState(null, "", "/");
  })();
})();
