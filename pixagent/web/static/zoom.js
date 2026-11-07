/* PixZoom — zoom y desplazamiento universales para imágenes, planos, SVG y páginas de PDF.
   Sin dependencias (~5 KB). Funciona igual con:
   - Ratón:    rueda = zoom hacia el cursor (modo "zoom") · arrastrar = mover · doble clic = ajustar/2×
   - Trackpad: pellizcar = zoom (llega como ctrl+rueda; en Safari, gesture*) · dos dedos = mover
   - Táctil:   pellizcar = zoom · un dedo = mover (si hay zoom) · doble toque = ajustar/2×
   - Lápiz:    como el ratón
   - Teclado:  + / − zoom · 0 ajustar · 1 tamaño real · flechas mover (con el visor enfocado)
   Uso:
     const z = PixZoom.attach(contenedor, contenido, { wheel: "zoom" | "scroll", controls: true });
     z.fit(); z.zoomTo(2); z.reset(); z.destroy();
   - wheel:"zoom"   (visor de imagen/plano): la rueda del ratón hace zoom.
   - wheel:"scroll" (documentos/PDF): la rueda desplaza; zoom con ctrl+rueda, pellizco o botones.
   El contenedor debe tener tamaño propio (overflow se fija a hidden). */
(function () {
  "use strict";
  var MIN = 0.1, MAX = 12;

  function attach(box, content, opts) {
    opts = opts || {};
    var mode = opts.wheel || "zoom";
    var s = 1, x = 0, y = 0, fitScale = 1;
    var pointers = {}, pinch = null, drag = null, lastTap = 0, raf = 0, multi = false;

    box.style.overflow = "hidden";
    box.style.touchAction = "none";
    box.style.position = box.style.position || "relative";
    box.style.cursor = "grab";
    if (!box.hasAttribute("tabindex")) box.setAttribute("tabindex", "0");
    box.setAttribute("aria-label", box.getAttribute("aria-label") || "Visor: rueda o pellizco para zoom, arrastrar para mover");
    content.style.transformOrigin = "0 0";
    var idle = 0;
    content.style.userSelect = "none";
    content.draggable = false;

    function size() {
      var w = content.naturalWidth || content.offsetWidth || content.scrollWidth;
      var h = content.naturalHeight || content.offsetHeight || content.scrollHeight;
      return { w: w || 1, h: h || 1 };
    }
    function apply() {
      if (raf) return;
      raf = requestAnimationFrame(function () {
        raf = 0;
        // will-change solo durante el gesto: al terminar, el navegador vuelve a rasterizar el SVG/texto
        // a la escala real (si no, al ampliar se vería borroso)
        content.style.willChange = "transform";
        clearTimeout(idle);
        idle = setTimeout(function () { content.style.willChange = "auto"; }, 180);
        content.style.transform = "translate(" + x + "px," + y + "px) scale(" + s + ")";
        if (label) label.textContent = Math.round(s * 100) + "%";
      });
    }
    function clamp() {
      var c = size(), bw = box.clientWidth, bh = box.clientHeight, w = c.w * s, h = c.h * s;
      // si cabe, centrar; si no, no dejar huecos más allá del borde
      x = w <= bw ? (bw - w) / 2 : Math.min(0, Math.max(bw - w, x));
      y = h <= bh ? (mode === "scroll" ? 0 : (bh - h) / 2) : Math.min(0, Math.max(bh - h, y));
    }
    function zoomAt(ns, cx, cy) {
      ns = Math.max(Math.min(fitScale, 1) * 0.5, Math.max(MIN, Math.min(MAX, ns)));
      var r = box.getBoundingClientRect();
      var px = (cx === undefined ? r.width / 2 : cx - r.left), py = (cy === undefined ? r.height / 2 : cy - r.top);
      x = px - (px - x) * (ns / s);
      y = py - (py - y) * (ns / s);
      s = ns; clamp(); apply();
    }
    function fit() {
      var c = size(), bw = box.clientWidth || 1, bh = box.clientHeight || 1;
      fitScale = mode === "scroll" ? Math.min(1.5, bw / c.w) : Math.min(bw / c.w, bh / c.h, opts.maxFit || 1.5);
      s = fitScale; x = 0; y = 0; clamp(); apply();
    }
    function toggle(cx, cy) {
      if (Math.abs(s - fitScale) < 0.02) zoomAt(Math.max(fitScale * 2.5, 1), cx, cy);
      else fit();
    }

    // ---- rueda / trackpad
    function onWheel(e) {
      e.preventDefault();
      var dy = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaMode === 2 ? e.deltaY * box.clientHeight : e.deltaY;
      var dx = e.deltaMode === 1 ? e.deltaX * 16 : e.deltaX;
      // trackpad: deltas finos y/o horizontales sin ctrl → desplazar; ratón: rueda → zoom (modo "zoom")
      var trackpadPan = !e.ctrlKey && (Math.abs(dx) > 0 || (Math.abs(dy) < 40 && dy % 1 !== 0));
      if (e.ctrlKey || e.metaKey || (mode === "zoom" && !trackpadPan && !e.shiftKey)) {
        // pellizco de trackpad = ctrl+rueda con deltas pequeños (sensibilidad alta); la rueda de ratón
        // (con o sin ctrl) llega a saltos de ~100: sensibilidad baja y tope por evento
        var fine = e.ctrlKey && Math.abs(dy) < 40;
        var k = Math.exp(-Math.max(-150, Math.min(150, dy)) * (fine ? 0.01 : 0.0022));
        zoomAt(s * k, e.clientX, e.clientY);
      } else {
        if (e.shiftKey && !dx) { dx = dy; dy = 0; }
        x -= dx; y -= dy; clamp(); apply();
      }
    }
    // ---- Safari (macOS/iPadOS): gestos de pellizco del trackpad
    var gStart = 1;
    function onGestureStart(e) { e.preventDefault(); gStart = s; }
    function onGestureChange(e) { e.preventDefault(); zoomAt(gStart * e.scale, e.clientX, e.clientY); }

    // ---- punteros (ratón, táctil, lápiz)
    function onDown(e) {
      if (e.button !== undefined && e.button > 0 && e.pointerType === "mouse") return;
      if (e.target.closest && e.target.closest(".pz-controls")) return;
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      try { if (e.pointerType !== "touch") box.setPointerCapture(e.pointerId); } catch (err) { /* sin captura */ }
      var ids = Object.keys(pointers);
      if (ids.length === 2) {
        var a = pointers[ids[0]], b = pointers[ids[1]];
        multi = true;  // gesto de varios dedos: no cuenta como toque
        pinch = { d: Math.hypot(a.x - b.x, a.y - b.y) || 1, s: s, cx: (a.x + b.x) / 2, cy: (a.y + b.y) / 2 };
        drag = null;
      } else if (ids.length === 1) {
        drag = { x: e.clientX, y: e.clientY, ox: x, oy: y, moved: false };
        box.style.cursor = "grabbing";
      }
    }
    function onMove(e) {
      if (!pointers[e.pointerId]) return;
      pointers[e.pointerId] = { x: e.clientX, y: e.clientY };
      var ids = Object.keys(pointers);
      if (pinch && ids.length >= 2) {
        var a = pointers[ids[0]], b = pointers[ids[1]];
        var d = Math.hypot(a.x - b.x, a.y - b.y), cx = (a.x + b.x) / 2, cy = (a.y + b.y) / 2;
        x += cx - pinch.cx; y += cy - pinch.cy; pinch.cx = cx; pinch.cy = cy;
        zoomAt(pinch.s * d / pinch.d, cx, cy);
      } else if (drag) {
        var mx = e.clientX - drag.x, my = e.clientY - drag.y;
        if (Math.abs(mx) + Math.abs(my) > 4) drag.moved = true;
        x = drag.ox + mx; y = drag.oy + my; clamp(); apply();
      }
    }
    function onUp(e) {
      var wasDrag = drag && drag.moved;
      delete pointers[e.pointerId];
      if (Object.keys(pointers).length < 2) pinch = null;
      var last = !Object.keys(pointers).length;
      if (last) { drag = null; box.style.cursor = "grab"; }
      // doble toque (táctil) — el doble clic del ratón usa dblclick
      if (e.pointerType === "touch" && !wasDrag && !multi && last) {
        var now = Date.now();
        if (now - lastTap < 300) { toggle(e.clientX, e.clientY); lastTap = 0; } else lastTap = now;
      }
      if (last) multi = false;
    }
    function onDbl(e) {
      if (e.target.closest && e.target.closest(".pz-controls")) return;  // doble clic en los botones
      e.preventDefault(); toggle(e.clientX, e.clientY);
    }

    // ---- teclado
    function onKey(e) {
      var step = 60;
      if (e.key === "+" || e.key === "=") zoomAt(s * 1.25);
      else if (e.key === "-" || e.key === "_") zoomAt(s / 1.25);
      else if (e.key === "0") fit();
      else if (e.key === "1") zoomAt(1);
      else if (e.key === "ArrowLeft") { x += step; clamp(); apply(); }
      else if (e.key === "ArrowRight") { x -= step; clamp(); apply(); }
      else if (e.key === "ArrowUp") { y += step; clamp(); apply(); }
      else if (e.key === "ArrowDown") { y -= step; clamp(); apply(); }
      else return;
      e.preventDefault();
    }

    // ---- botones visibles (táctil y usuarios que no conocen los gestos)
    var controls = null, label = null;
    if (opts.controls !== false) {
      controls = document.createElement("div");
      controls.className = "pz-controls";
      controls.innerHTML = '<button type="button" data-z="out" aria-label="Alejar" title="Alejar (&#8722;)">&#8722;</button>' +
        '<button type="button" data-z="fit" class="pz-label" aria-label="Ajustar a la pantalla" title="Ajustar (0)">100%</button>' +
        '<button type="button" data-z="in" aria-label="Acercar" title="Acercar (+)">+</button>';
      label = controls.querySelector(".pz-label");
      controls.addEventListener("click", function (e) {
        var b = e.target.closest("button"); if (!b) return;
        if (b.dataset.z === "in") zoomAt(s * 1.4); else if (b.dataset.z === "out") zoomAt(s / 1.4); else fit();
      });
      box.appendChild(controls);
      injectStyle();
    }

    box.addEventListener("wheel", onWheel, { passive: false });
    box.addEventListener("gesturestart", onGestureStart);
    box.addEventListener("gesturechange", onGestureChange);
    box.addEventListener("pointerdown", onDown);
    box.addEventListener("pointermove", onMove);
    box.addEventListener("pointerup", onUp);
    box.addEventListener("pointercancel", onUp);
    box.addEventListener("dblclick", onDbl);
    box.addEventListener("keydown", onKey);
    var ro = window.ResizeObserver ? new ResizeObserver(function () { var wasFit = Math.abs(s - fitScale) < 0.02; if (wasFit) fit(); else { clamp(); apply(); } }) : null;
    if (ro) ro.observe(box);
    if (content.tagName === "IMG" && !content.complete) content.addEventListener("load", fit, { once: true }); else fit();

    return {
      fit: fit, reset: fit,
      zoomTo: function (v) { zoomAt(v); },
      zoomBy: function (k) { zoomAt(s * k); },
      get scale() { return s; },
      get fitScale() { return fitScale; },
      destroy: function () {
        box.removeEventListener("wheel", onWheel); box.removeEventListener("gesturestart", onGestureStart);
        box.removeEventListener("gesturechange", onGestureChange); box.removeEventListener("pointerdown", onDown);
        box.removeEventListener("pointermove", onMove); box.removeEventListener("pointerup", onUp);
        box.removeEventListener("pointercancel", onUp); box.removeEventListener("dblclick", onDbl);
        box.removeEventListener("keydown", onKey); if (ro) ro.disconnect(); if (controls) controls.remove();
        content.style.transform = "";
      },
    };
  }

  var styled = false;
  function injectStyle() {
    if (styled) return; styled = true;
    var st = document.createElement("style");
    st.textContent = ".pz-controls{position:absolute;right:12px;bottom:12px;display:flex;gap:2px;padding:3px;" +
      "border-radius:12px;background:rgba(20,22,30,.72);backdrop-filter:blur(8px);-webkit-backdrop-filter:blur(8px);z-index:3}" +
      ".pz-controls button{min-width:40px;height:40px;border:0;border-radius:9px;background:transparent;color:#fff;" +
      "font:600 15px/1 system-ui,sans-serif;cursor:pointer;touch-action:manipulation}" +
      ".pz-controls button:hover{background:rgba(255,255,255,.14)}.pz-controls .pz-label{min-width:58px;font-size:12.5px}" +
      ".pz-controls button:focus-visible{outline:2px solid #8b8bff;outline-offset:1px}" +
      "@media (pointer:coarse){.pz-controls button{min-width:46px;height:46px}}";
    document.head.appendChild(st);
  }

  window.PixZoom = { attach: attach };
})();
