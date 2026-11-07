/* Detector de gestos — mini app de PixAgent.
   Cámara (getUserMedia) + MediaPipe Tasks Vision GestureRecognizer (en el dispositivo, sin IA de pago).
   ES2019 salvo import() dinámico (Safari 11+). */
(function () {
  "use strict";
  var $ = function (s, r) { return (r || document).querySelector(s); };
  var CDN = "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@0.10.14";
  var MODEL = "https://storage.googleapis.com/mediapipe-models/gesture_recognizer/gesture_recognizer/float16/1/gesture_recognizer.task";
  var FRAME_MS = 60;                                   // ~16 fps: suficiente para gestos, ahorra batería
  var NAMES = { Thumb_Up: "Pulgar arriba", Thumb_Down: "Pulgar abajo", Victory: "Victoria", Closed_Fist: "Puño cerrado",
    Open_Palm: "Palma abierta", Pointing_Up: "Señalar arriba", ILoveYou: "Te quiero", None: "Sin gesto" };
  var CONNECTIONS = [[0, 1], [1, 2], [2, 3], [3, 4], [0, 5], [5, 6], [6, 7], [7, 8], [5, 9], [9, 10], [10, 11], [11, 12], [9, 13], [13, 14], [14, 15], [15, 16], [13, 17], [17, 18], [18, 19], [19, 20], [0, 17]];
  var FINGER_COLORS = ["#f6c343", "#5bd6ff", "#8c7bff", "#ff7bb0", "#6fe3a0"];   // pulgar, índice, medio, anular, meñique

  var video = $("#video"), canvas = $("#overlay"), ctx = canvas.getContext("2d");
  var stage = $("#stage"), ov = $("#ov"), ovBox = $("#ovBox");
  var stream = null, recognizer = null, visionMod = null, running = false, raf = 0, lastT = 0, facing = "user";
  var fpsN = 0, fpsT = 0, lastResult = null, captures = [];

  /* ---------- utilidades ---------- */
  var toastTimer;
  function toast(msg) {
    var t = $("#toast"); t.textContent = msg; t.classList.add("show");
    clearTimeout(toastTimer); toastTimer = setTimeout(function () { t.classList.remove("show"); }, 2400);
    if (window.PixAgent && PixAgent.embedded) PixAgent.toast(msg);
  }
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]; }); }
  function setStatus(s, txt) { $("#status").dataset.s = s; $("#statusTxt").textContent = txt; }
  function overlay(opts) {
    if (!opts) { ov.hidden = true; return; }
    ov.hidden = false;
    var h = "";
    if (opts.spinner) h += '<span class="spin"></span>';
    else h += '<div class="ico' + (opts.error ? " err" : "") + '"><svg class="i" style="width:30px;height:30px"><use href="#' + (opts.icon || "i-hand") + '"/></svg></div>';
    h += "<h2>" + esc(opts.title) + "</h2>";
    if (opts.text) h += "<p>" + esc(opts.text) + "</p>";
    ovBox.innerHTML = h;
    (opts.buttons || []).forEach(function (b) {
      var el = document.createElement("button"); el.type = "button"; el.className = "btn " + (b.cls || "light");
      el.innerHTML = (b.icon ? '<svg class="i"><use href="#' + b.icon + '"/></svg> ' : "") + esc(b.label);
      el.onclick = b.onClick; ovBox.appendChild(el);
    });
  }
  function isSecure() { return window.isSecureContext || location.hostname === "localhost" || location.hostname === "127.0.0.1"; }
  function support() { return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia); }

  /* ---------- estado inicial ---------- */
  function showIdle() {
    setStatus("idle", "Cámara apagada");
    if (!support()) {
      overlay({ error: true, icon: "i-camera-off", title: "Este navegador no puede usar la cámara",
        text: isSecure() ? "Prueba con Chrome, Edge, Firefox o Safari actualizados." : "El acceso a la cámara requiere HTTPS (o localhost). Abre PixAgent con una dirección segura." });
      return;
    }
    overlay({ icon: "i-hand", title: "Muestra la mano a la cámara", text: "Reconoce pulgar arriba, victoria, puño, palma abierta y más. Todo se procesa en tu dispositivo.",
      buttons: [{ label: "Iniciar cámara", icon: "i-play", cls: "primary", onClick: start }] });
  }

  /* ---------- cámara ---------- */
  function stopStream() {
    if (stream) { stream.getTracks().forEach(function (t) { t.stop(); }); stream = null; }
    video.srcObject = null;
  }
  function openCamera() {
    stopStream();
    var constraints = { audio: false, video: { facingMode: facing, width: { ideal: 1280 }, height: { ideal: 720 } } };
    return navigator.mediaDevices.getUserMedia(constraints).catch(function (e) {
      if (e && (e.name === "OverconstrainedError" || e.name === "NotFoundError") && facing === "environment") {
        facing = "user"; return navigator.mediaDevices.getUserMedia({ audio: false, video: true });
      }
      throw e;
    }).then(function (s) {
      stream = s; video.srcObject = s;
      stage.classList.toggle("mirror", facing === "user");
      return new Promise(function (res) {
        var done = false, fin = function () { if (!done) { done = true; res(); } };
        video.onloadedmetadata = function () { video.play().then(fin, fin); };
        setTimeout(fin, 2500);
      });
    }).then(function () {
      canvas.width = video.videoWidth || 640; canvas.height = video.videoHeight || 480;
      stage.style.aspectRatio = canvas.width + " / " + canvas.height;
      $("#hudRes").textContent = canvas.width + "×" + canvas.height;
      var hasMany = navigator.mediaDevices.enumerateDevices ? navigator.mediaDevices.enumerateDevices().then(function (ds) { return ds.filter(function (d) { return d.kind === "videoinput"; }).length > 1; }) : Promise.resolve(false);
      return hasMany.then(function (many) { $("#btnSwitch").disabled = !many; });
    });
  }
  function cameraError(e) {
    var name = (e && e.name) || "";
    var title = "No se pudo abrir la cámara", text = (e && e.message) || "";
    if (name === "NotAllowedError" || name === "SecurityError") { title = "Permiso de cámara denegado"; text = "Permite el acceso a la cámara para esta página (icono del candado o de la cámara en la barra de direcciones) y vuelve a intentarlo."; }
    else if (name === "NotFoundError" || name === "DevicesNotFoundError") { title = "No se encontró ninguna cámara"; text = "Conecta una cámara o abre la app en un dispositivo que tenga una."; }
    else if (name === "NotReadableError" || name === "TrackStartError") { title = "La cámara está ocupada"; text = "Otra aplicación la está usando. Ciérrala y vuelve a intentarlo."; }
    else if (name === "OverconstrainedError") { title = "Esa cámara no está disponible"; text = "Prueba a cambiar de cámara."; }
    setStatus("error", title);
    overlay({ error: true, icon: "i-camera-off", title: title, text: text, buttons: [{ label: "Reintentar", icon: "i-play", cls: "primary", onClick: start }] });
  }

  /* ---------- modelo ---------- */
  function loadModel() {
    if (recognizer) return Promise.resolve(recognizer);
    var mod = visionMod ? Promise.resolve(visionMod) : import(CDN + "/vision_bundle.mjs").then(function (m) { visionMod = m; return m; });
    return mod.then(function (m) {
      return m.FilesetResolver.forVisionTasks(CDN + "/wasm").then(function (fileset) {
        var make = function (delegate) {
          return m.GestureRecognizer.createFromOptions(fileset, {
            baseOptions: { modelAssetPath: MODEL, delegate: delegate }, runningMode: "VIDEO", numHands: 2,
            minHandDetectionConfidence: 0.5, minHandPresenceConfidence: 0.5, minTrackingConfidence: 0.5
          });
        };
        return make("GPU").catch(function () { return make("CPU"); });
      });
    }).then(function (r) { recognizer = r; return r; });
  }
  function modelError(e) {
    var offline = navigator.onLine === false;
    var title = offline ? "Sin conexión a internet" : "No se pudo cargar el modelo";
    var text = offline ? "El modelo de reconocimiento se descarga la primera vez (≈8 MB). Conéctate y vuelve a intentarlo; después el navegador lo guarda en caché."
      : "No se pudo descargar MediaPipe desde cdn.jsdelivr.net o el modelo desde storage.googleapis.com. Revisa la red o un bloqueador de contenido. " + ((e && e.message) ? "(" + String(e.message).slice(0, 120) + ")" : "");
    setStatus("error", title);
    overlay({ error: true, icon: "i-wifi-off", title: title, text: text, buttons: [{ label: "Reintentar", icon: "i-play", cls: "primary", onClick: start }] });
  }

  /* ---------- arranque / parada ---------- */
  var starting = false;
  function start() {
    if (starting) return;
    if (!support()) { showIdle(); return; }
    starting = true; $("#btnStart").disabled = true;
    setStatus("loading", "Abriendo la cámara…");
    overlay({ spinner: true, title: "Abriendo la cámara…", text: "Acepta el permiso si el navegador lo pide." });
    var modelP = loadModel();
    modelP.catch(function () { /* se gestiona abajo */ });
    openCamera().then(function () {
      setStatus("loading", "Cargando el modelo…");
      overlay({ spinner: true, title: "Cargando el modelo de gestos…", text: "Solo tarda la primera vez (≈8 MB). Luego queda en la caché del navegador." });
      return modelP.then(function () {
        overlay(null); running = true; lastT = 0; fpsN = 0; fpsT = performance.now();
        setStatus("live", "Reconociendo");
        $("#hud").hidden = false; $("#btnSnap").disabled = false;
        $("#btnStart").innerHTML = '<svg class="i"><use href="#i-stop"/></svg> Detener'; $("#btnStart").disabled = false;
        $("#gName").textContent = "Muestra la mano"; $("#gName").className = "g none";
        raf = requestAnimationFrame(loop);
      }, function (e) { stopStream(); modelError(e); });
    }, cameraError).then(function () { starting = false; $("#btnStart").disabled = false; });
  }
  function stop() {
    running = false; cancelAnimationFrame(raf); stopStream();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    $("#hud").hidden = true; $("#btnSnap").disabled = true; $("#btnSwitch").disabled = true; $("#pill").classList.remove("show");
    $("#btnStart").innerHTML = '<svg class="i"><use href="#i-play"/></svg> Iniciar cámara';
    $("#gName").textContent = "Cámara apagada"; $("#gName").className = "g none"; $("#gRaw").textContent = "—"; $("#gBar").style.width = "0";
    ["#sConf", "#sFingers", "#sHands"].forEach(function (id) { $(id).textContent = "—"; });
    showIdle();
  }
  $("#btnStart").onclick = function () { if (running || stream) stop(); else start(); };
  $("#btnSwitch").onclick = function () {
    if (!stream) return;
    facing = facing === "user" ? "environment" : "user";
    var was = running; running = false; cancelAnimationFrame(raf);
    openCamera().then(function () { if (was) { running = true; raf = requestAnimationFrame(loop); } }, cameraError);
  };

  /* ---------- bucle ---------- */
  function loop(ts) {
    if (!running) return;
    raf = requestAnimationFrame(loop);
    if (ts - lastT < FRAME_MS) return;
    lastT = ts;
    if (video.readyState < 2 || !recognizer) return;
    var res;
    try { res = recognizer.recognizeForVideo(video, performance.now()); } catch (e) { return; }
    lastResult = res;
    draw(res);
    fpsN++;
    var now = performance.now();
    if (now - fpsT >= 1000) { $("#hudFps").textContent = Math.round(fpsN * 1000 / (now - fpsT)) + " fps"; fpsN = 0; fpsT = now; }
  }
  function dist(a, b) { var dx = a.x - b.x, dy = a.y - b.y, dz = (a.z || 0) - (b.z || 0); return Math.sqrt(dx * dx + dy * dy + dz * dz); }
  function fingersUp(lm) {
    var n = 0, tips = [8, 12, 16, 20], pips = [6, 10, 14, 18];
    for (var i = 0; i < 4; i++) if (dist(lm[tips[i]], lm[0]) > dist(lm[pips[i]], lm[0]) * 1.08) n++;
    if (dist(lm[4], lm[9]) > dist(lm[2], lm[9]) * 1.15) n++;      // pulgar separado del centro de la palma
    return n;
  }
  function draw(res) {
    var W = canvas.width, H = canvas.height;
    ctx.clearRect(0, 0, W, H);
    var hands = (res && res.landmarks) || [];
    var best = null, fingers = 0;
    hands.forEach(function (lm, hi) {
      var sc = Math.max(1.5, W / 480);
      ctx.lineWidth = 3 * sc / 1.5; ctx.lineCap = "round"; ctx.strokeStyle = "rgba(255,255,255,.85)";
      CONNECTIONS.forEach(function (c, ci) {
        var finger = ci < 4 ? 0 : ci < 8 ? 1 : ci < 12 ? 2 : ci < 16 ? 3 : 4;
        ctx.strokeStyle = (ci === 4 || ci === 8 || ci === 12 || ci === 16 || ci === 20) ? "rgba(255,255,255,.75)" : FINGER_COLORS[finger];
        ctx.beginPath(); ctx.moveTo(lm[c[0]].x * W, lm[c[0]].y * H); ctx.lineTo(lm[c[1]].x * W, lm[c[1]].y * H); ctx.stroke();
      });
      lm.forEach(function (p, i) {
        ctx.beginPath(); ctx.arc(p.x * W, p.y * H, (i === 0 ? 5 : 3.5) * sc / 1.5, 0, Math.PI * 2);
        ctx.fillStyle = "#fff"; ctx.fill(); ctx.lineWidth = 1.5; ctx.strokeStyle = "rgba(12,14,20,.6)"; ctx.stroke();
      });
      fingers += fingersUp(lm);
      var g = res.gestures && res.gestures[hi] && res.gestures[hi][0];
      if (g && (!best || g.score > best.score)) best = g;
      // etiqueta de mano (sin espejo: el canvas ya se voltea por CSS)
      var hd = res.handedness && res.handedness[hi] && res.handedness[hi][0];
      if (hd) {
        var label = hd.categoryName === "Left" ? "Izquierda" : "Derecha";
        if (stage.classList.contains("mirror")) label = hd.categoryName === "Left" ? "Derecha" : "Izquierda";
        var x = lm[0].x * W, y = lm[0].y * H + 22 * sc / 1.5;
        ctx.font = "600 " + Math.round(12 * sc / 1.5) + "px -apple-system, Segoe UI, Roboto, sans-serif";
        ctx.save();
        if (stage.classList.contains("mirror")) { ctx.translate(x, y); ctx.scale(-1, 1); ctx.translate(-x, -y); }
        var tw = ctx.measureText(label).width + 12;
        ctx.fillStyle = "rgba(12,14,20,.6)"; ctx.fillRect(x - tw / 2, y - 12, tw, 18); ctx.fillStyle = "#fff"; ctx.textAlign = "center"; ctx.fillText(label, x, y + 1);
        ctx.restore();
      }
    });
    $("#sHands").textContent = hands.length ? String(hands.length) : "0";
    $("#sFingers").textContent = hands.length ? String(fingers) : "—";
    var pill = $("#pill");
    if (best && best.categoryName && best.categoryName !== "None") {
      var name = NAMES[best.categoryName] || best.categoryName, pct = Math.round(best.score * 100);
      $("#gName").textContent = name; $("#gName").className = "g";
      $("#gRaw").textContent = best.categoryName + " · " + pct + " %";
      $("#gBar").style.width = pct + "%"; $("#sConf").innerHTML = pct + "<small> %</small>";
      pill.textContent = name + " · " + pct + " %"; pill.classList.add("show");
    } else {
      $("#gName").textContent = hands.length ? "Sin gesto reconocido" : "Muestra la mano"; $("#gName").className = "g none";
      $("#gRaw").textContent = hands.length ? "None" : "—"; $("#gBar").style.width = "0"; $("#sConf").textContent = "—";
      pill.classList.remove("show");
    }
  }

  /* ---------- pausa automática ---------- */
  document.addEventListener("visibilitychange", function () {
    if (!stream) return;
    if (document.hidden) {
      running = false; cancelAnimationFrame(raf);
      stream.getVideoTracks().forEach(function (t) { t.enabled = false; });
      setStatus("paused", "En pausa (pestaña oculta)");
    } else {
      stream.getVideoTracks().forEach(function (t) { t.enabled = true; });
      if (recognizer) { running = true; lastT = 0; raf = requestAnimationFrame(loop); setStatus("live", "Reconociendo"); }
    }
  });
  window.addEventListener("pagehide", function () { stopStream(); });

  /* ---------- captura ---------- */
  function renderCaps() {
    var box = $("#caps"); box.innerHTML = "";
    $("#capsEmpty").hidden = captures.length > 0;
    $("#capCount").textContent = captures.length ? "· " + captures.length : "";
    captures.forEach(function (c) {
      var el = document.createElement("div"); el.className = "cap";
      el.innerHTML = '<img alt="' + esc(c.label) + '" src="' + c.url + '"><div class="acts">' +
        '<a href="' + PixAgent.fileUrl(c.path) + '" target="_blank" rel="noopener" title="Abrir"><svg class="i sm"><use href="#i-open"/></svg></a>' +
        '<button type="button" title="Fijar en PixPin"><svg class="i sm"><use href="#i-pin"/></svg></button></div>';
      el.querySelector("button").onclick = function () {
        var b = this; b.disabled = true;
        PixAgent.pin([c.path]).then(function () { toast("Fijado en PixPin"); }, function (e) { toast("PixPin no respondió: " + ((e && e.message) || e)); }).then(function () { b.disabled = false; });
      };
      box.appendChild(el);
    });
  }
  $("#btnSnap").onclick = function () {
    if (!stream || video.readyState < 2) return;
    var W = video.videoWidth || canvas.width, H = video.videoHeight || canvas.height;
    var snap = document.createElement("canvas"); snap.width = W; snap.height = H;
    var sc = snap.getContext("2d");
    if (stage.classList.contains("mirror")) { sc.translate(W, 0); sc.scale(-1, 1); }
    sc.drawImage(video, 0, 0, W, H); sc.drawImage(canvas, 0, 0, W, H);
    var g = $("#gName").textContent, stamp = new Date().toISOString().replace(/[-:T]/g, "").slice(0, 14);
    var btn = this; btn.disabled = true;
    snap.toBlob(function (blob) {
      snap.width = 1; snap.height = 1;
      if (!blob) { btn.disabled = false; toast("No se pudo capturar el fotograma"); return; }
      PixAgent.save("gesto_" + stamp + ".png", blob, { folder: "gestos" }).then(function (path) {
        captures.unshift({ path: path, url: URL.createObjectURL(blob), label: g }); captures = captures.slice(0, 8);
        renderCaps(); toast("Captura guardada: " + path.split("/").pop());
      }, function (e) { toast("No se pudo guardar: " + ((e && e.message) || e)); }).then(function () { btn.disabled = false; });
    }, "image/png");
  };
  document.addEventListener("keydown", function (e) { if (e.key === " " && running && !/INPUT|BUTTON/.test(e.target.tagName)) { e.preventDefault(); $("#btnSnap").click(); } });

  if (!window.PixAgent) window.PixAgent = { embedded: false, fileUrl: function (p) { return "/files/" + p; }, save: function () { return Promise.reject(new Error("SDK no cargado")); }, pin: function () { return Promise.reject(new Error("SDK no cargado")); }, toast: function () { } };
  renderCaps();
  showIdle();
})();
