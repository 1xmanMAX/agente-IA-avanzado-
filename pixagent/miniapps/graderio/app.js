/* Escaleras y graderías — mini app de PixAgent.
   Todo el cálculo y el dibujo (SVG, isométrico y 3D en canvas) ocurre en el navegador, sin tokens ni
   dependencias. La IA solo se usa si el usuario pulsa "Revisar con IA". ES2019, compatible con iOS 15. */
(function () {
  "use strict";

  // ------------------------------------------------------------------ utilidades
  const $ = (s, el) => (el || document).querySelector(s);
  const $$ = (s, el) => Array.prototype.slice.call((el || document).querySelectorAll(s));
  const fmt = (v, d) => (isFinite(v) ? Number(v).toFixed(d == null ? 2 : d) : "—");
  const clamp = (v, a, b) => Math.min(b, Math.max(a, v));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const deg = (r) => (r * 180) / Math.PI;
  const debounce = (fn, ms) => { let t; return function () { clearTimeout(t); const a = arguments; t = setTimeout(() => fn.apply(null, a), ms); }; };
  const FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, system-ui, sans-serif";
  const STORE_KEY = "graderio.params.v1";
  const today = () => { const d = new Date(); return d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0"); };

  // ------------------------------------------------------------------ parámetros
  const NUM_IDS = ["H", "L", "B", "t", "cmin", "cmax", "hmin", "hmax", "nmax", "Ld", "Nmin", "Nmax", "Tmin", "Tmax", "Be", "Wp", "Df", "hf", "eyeH"];
  let mode = "stair";

  function readParams() {
    const p = { mode };
    NUM_IDS.forEach((id) => { const v = parseFloat($("#" + id).value); p[id] = isFinite(v) ? v : NaN; });
    p.stepsPerRow = parseInt($("#stepsPerRow").value, 10) || 2;
    p.accessStair = $("#accessStair").checked;
    p.aisle = $("#aisle").checked;
    p.aislePos = $("#aislePos").value;
    p.title = $("#title").value.trim() || "Proyecto";
    p.paper = $("#paper").value;
    p.vis = $("#visDetails").open;
    // saneado mínimo
    if (!(p.H > 0)) p.H = 1; if (!(p.L > 0)) p.L = 1; if (!(p.B > 0)) p.B = 1; if (!(p.t > 0)) p.t = 0.15;
    if (!(p.cmin > 0)) p.cmin = 0.15; if (!(p.cmax > p.cmin)) p.cmax = p.cmin + 0.03;
    if (!(p.hmin > 0)) p.hmin = 0.25; if (!(p.hmax > p.hmin)) p.hmax = p.hmin + 0.05;
    if (!(p.Nmin > 0)) p.Nmin = 0.4; if (!(p.Nmax > p.Nmin)) p.Nmax = p.Nmin + 0.05;
    if (!(p.Tmin > 0)) p.Tmin = 0.7; if (!(p.Tmax > p.Tmin)) p.Tmax = p.Tmin + 0.2;
    if (!(p.nmax >= 2)) p.nmax = 18;
    if (!(p.Be > 0)) p.Be = 1.2; if (!(p.Wp > 0)) p.Wp = 1.2;
    if (!(p.eyeH > 0)) p.eyeH = 1.15; if (!(p.Df >= 0)) p.Df = 6; if (!isFinite(p.hf)) p.hf = 0;
    return p;
  }

  // ------------------------------------------------------------------ geometría: escalera
  // Perfil (x = avance, z = altura) de una escalera con tramos y descansos, con losa de garganta t.
  function stairGeometry(flightsN, c, h, Ld, t) {
    const len = Math.hypot(c, h);
    const top = [[0, 0]], steps = [], flights = [];
    let x = 0, z = 0, idx = 0;
    flightsN.forEach((nk, k) => {
      const xs = x, zs = z;
      for (let r = 1; r <= nk; r++) {
        idx++; z += c; top.push([x, z]);
        const last = r === nk;
        steps.push({ i: idx, flight: k + 1, x, z, c, h: last ? null : h, note: last ? (k < flightsN.length - 1 ? "descanso" : "llegada") : "" });
        if (!last) { x += h; top.push([x, z]); }
      }
      const xe = x, ze = z;
      // intersecciones de la línea de garganta (paralela a la línea de huella, a distancia t) con los niveles
      const xTop = xs + t * c / len + (nk * c - t + t * h / len) * (h / c);
      const xBot = k === 0 ? xs + t * len / c : xs + t * c / len + (-t + t * h / len) * (h / c);
      flights.push({ k, nk, xs, zs, xe, ze, xTop, xBot, len, slope: nk * len });
      if (k < flightsN.length - 1) { x += Ld; top.push([x, z]); }
    });
    const H = z, xEnd = x, lastF = flights[flights.length - 1];
    const a = Math.max(0.3, lastF.xTop - xEnd + 0.05); // apoyo en la losa superior
    const poly = top.slice();
    poly.push([xEnd + a, H]); poly.push([xEnd + a, H - t]);
    for (let k = flights.length - 1; k >= 0; k--) {
      const F = flights[k];
      poly.push([F.xTop, F.ze - t]);
      if (k === 0) poly.push([F.xBot, 0]);
      else poly.push([Math.max(F.xBot, flights[k - 1].xTop), F.zs - t]);
    }
    return { top, poly, steps, flights, H, xEnd, a, len, xMax: xEnd + a };
  }

  function designStair(p) {
    const H = p.H, L = p.L, B = p.B, t = p.t;
    const Ld = p.Ld > 0 ? p.Ld : Math.max(B, 1);
    const nmax = Math.max(2, Math.round(p.nmax));
    const evalN = (n) => {
      const c = H / n, f = Math.ceil(n / nmax), treads = n - f, Lu = L - (f - 1) * Ld;
      const h = treads > 0 ? Lu / treads : NaN, bl = 2 * c + h;
      const cOk = c >= p.cmin - 1e-9 && c <= p.cmax + 1e-9, hOk = h >= p.hmin - 1e-9 && h <= p.hmax + 1e-9;
      const blOk = bl >= 0.6 - 1e-9 && bl <= 0.64 + 1e-9, geomOk = treads > 0 && Lu > 0 && isFinite(h) && h > 0;
      const score = (isFinite(bl) ? Math.abs(bl - 0.62) * 10 : 50) + (cOk ? 0 : 5) + (hOk ? 0 : 5) + (blOk ? 0 : 1) + (geomOk ? 0 : 100);
      return { n, c, f, treads, Lu, h, bl, cOk, hOk, blOk, geomOk, score, valid: cOk && hOk && blOk && geomOk };
    };
    const nlo = Math.max(1, Math.ceil(H / p.cmax - 1e-9)), nhi = Math.floor(H / p.cmin + 1e-9);
    const cands = [];
    for (let n = nlo; n <= nhi; n++) cands.push(evalN(n));
    if (!cands.length) cands.push(evalN(Math.max(1, Math.round(H / ((p.cmin + p.cmax) / 2)))));
    cands.sort((a, b) => a.score - b.score);
    const s = cands[0];
    const hDraw = s.geomOk ? s.h : (p.hmin + p.hmax) / 2;
    // reparto de contrahuellas por tramo
    const base = Math.floor(s.n / s.f), rem = s.n % s.f;
    const flightsN = []; for (let k = 0; k < s.f; k++) flightsN.push(base + (k < rem ? 1 : 0));
    const g = stairGeometry(flightsN, s.c, hDraw, Ld, t);
    // L recomendada para este n
    const hRec = clamp(0.62 - 2 * s.c, p.hmin, p.hmax);
    const Lrec = s.treads * hRec + (s.f - 1) * Ld;
    const Lmin = s.treads * Math.max(p.hmin, 0.6 - 2 * s.c) + (s.f - 1) * Ld;
    const Lmax = s.treads * Math.min(p.hmax, 0.64 - 2 * s.c) + (s.f - 1) * Ld;
    const angle = Math.atan2(s.c, hDraw);

    const checks = [];
    checks.push({ lv: s.cOk ? "ok" : "bad", text: "Contrahuella c = " + fmt(s.c, 3) + " m" + (s.cOk ? " dentro de " : " fuera de ") + fmt(p.cmin, 2) + "–" + fmt(p.cmax, 2) + " m" });
    if (!s.geomOk) checks.push({ lv: "bad", text: "La distancia L no permite ni una huella por tramo: aumenta L o reduce el descanso." });
    else checks.push({ lv: s.hOk ? "ok" : (s.h > p.hmax ? "warn" : "bad"), text: "Huella h = " + fmt(s.h, 3) + " m" + (s.hOk ? " dentro de " : (s.h < p.hmin ? " (corta) · mín " : " (larga) · máx ")) + (s.hOk ? fmt(p.hmin, 2) + "–" + fmt(p.hmax, 2) + " m" : (s.h < p.hmin ? fmt(p.hmin, 2) : fmt(p.hmax, 2)) + " m") });
    if (s.geomOk) checks.push({ lv: s.blOk ? "ok" : (Math.abs(s.bl - 0.62) < 0.05 ? "warn" : "bad"), text: "Blondel 2c + h = " + fmt(s.bl, 3) + " m" + (s.blOk ? " ✓ (0.60–0.64)" : " · objetivo 0.60–0.64") });
    if (s.geomOk && (!s.hOk || !s.blOk)) {
      const sobra = s.h > p.hmax;
      checks.push({ lv: sobra ? "warn" : "bad", text: (sobra ? "Sobra distancia: " : "L insuficiente: ") + "con " + s.n + " contrahuellas conviene L = " + fmt(Lrec, 2) + " m (válida entre " + fmt(Lmin, 2) + " y " + fmt(Lmax, 2) + " m)", action: { label: "Usar " + fmt(Lrec, 2), value: Lrec } });
    } else if (s.geomOk) checks.push({ lv: "ok", text: "L = " + fmt(L, 2) + " m se aprovecha por completo: " + s.treads + " huellas × " + fmt(s.h, 3) + (s.f > 1 ? " + " + (s.f - 1) + " descanso" + (s.f > 2 ? "s" : "") + " de " + fmt(Ld, 2) : "") });
    checks.push({ lv: s.f > 1 && Ld < B - 1e-9 ? "warn" : "ok", text: s.f === 1 ? "1 tramo de " + s.n + " contrahuellas (máx. " + nmax + " por tramo)" : s.f + " tramos de " + flightsN.join(" + ") + " contrahuellas · descanso " + fmt(Ld, 2) + " m" + (Ld < B - 1e-9 ? " (menor que el ancho B)" : " (≥ B)") });
    checks.push({ lv: deg(angle) >= 25 && deg(angle) <= 40 ? "ok" : "warn", text: "Inclinación " + fmt(deg(angle), 1) + "° (" + fmt(100 * Math.tan(angle), 0) + " %) · cómoda entre 25° y 40°" });

    const areaProfile = polyArea(g.poly);
    const volume = areaProfile * B;
    const soffit = g.flights.reduce((acc, F) => acc + Math.hypot(F.xTop - F.xBot, F.ze - F.zs) , 0) * B;
    const landingsUnder = (s.f - 1) * Ld * B;
    const risersArea = s.n * s.c * B;
    const sides = 2 * areaProfile;
    const form = soffit + landingsUnder + risersArea + sides;
    const slopeLen = g.flights.reduce((acc, F) => acc + F.slope, 0);

    return {
      mode: "stair", p, n: s.n, c: s.c, h: hDraw, hReal: s.h, bl: s.bl, f: s.f, flightsN, Ld, treads: s.treads, angle, checks, Lrec, geom: g,
      level: worst(checks),
      kpis: [
        { k: "Contrahuellas", v: s.n, u: "ud", d: s.f > 1 ? s.f + " tramos" : "1 tramo" },
        { k: "Contrahuella c", v: fmt(s.c, 3), u: "m", lv: s.cOk ? "ok" : "bad" },
        { k: "Huella h", v: fmt(s.h, 3), u: "m", lv: s.hOk ? "ok" : (s.h > p.hmax ? "warn" : "bad") },
        { k: "2c + h", v: fmt(s.bl, 3), u: "m", d: "Blondel 0.60–0.64", lv: s.blOk ? "ok" : "warn" },
        { k: "Inclinación", v: fmt(deg(angle), 1), u: "°" },
        { k: "Hormigón", v: fmt(volume, 2), u: "m³" },
      ],
      qty: [
        ["Contrahuellas / huellas", s.n + " / " + s.treads],
        ["Tramos · descansos", s.f + " · " + (s.f - 1)],
        ["Longitud horizontal usada", fmt(g.xEnd, 2) + " m"],
        ["Longitud desarrollada (línea de huella)", fmt(slopeLen, 2) + " m"],
        ["Apoyo en losa superior", fmt(g.a, 2) + " m"],
        ["Volumen de hormigón", fmt(volume, 2) + " m³"],
        ["Encofrado total aprox.", fmt(form, 1) + " m²"],
        ["· fondo de losa y descansos", fmt(soffit + landingsUnder, 1) + " m²"],
        ["· tabicas", fmt(risersArea, 1) + " m²"],
        ["· costados (2 caras)", fmt(sides, 1) + " m²"],
      ],
      qtyNote: "Volumen = área del perfil × ancho B (peldaños macizos sobre losa de garganta t = " + fmt(t, 2) + " m). Encofrado sin recargos ni solapes.",
      meshes: [{ faces: extrude(g.poly, 0, B, COL.concrete, true, true), yc: B / 2 }],
      table: g.steps.map((st) => [st.i, st.flight, fmt(st.z, 3), fmt(st.x, 2), fmt(st.c, 3), st.h == null ? (st.note === "descanso" ? "descanso " + fmt(Ld, 2) : "llegada") : fmt(st.h, 3)]),
      tableHead: ["Nº", "Tramo", "Cota (m)", "Avance (m)", "c (m)", "h (m)"],
      summary: s.n + " contrahuellas de " + fmt(s.c, 3) + " m · " + s.treads + " huellas de " + fmt(s.h, 3) + " m · 2c+h = " + fmt(s.bl, 3) + " m" + (s.f > 1 ? " · " + s.f + " tramos" : ""),
    };
  }

  // ------------------------------------------------------------------ geometría: graderío
  function bleacherGeometry(n, N, T, t, k, aisle) {
    const x0 = aisle && aisle.pos === "bottom" ? aisle.W : 0;
    const Wtop = aisle && aisle.pos === "top" ? aisle.W : 0;
    const len = Math.hypot(N, T), H = n * N, xBack = x0 + n * T;
    const zSoffBack = H - t * len / T, xBot = x0 + t * len / N;
    const saw = (steps, c, h) => { const pts = [[x0, 0]]; let x = x0, z = 0; for (let i = 0; i < steps; i++) { z += c; pts.push([x, z]); x += h; pts.push([x, z]); } return pts; };
    const close = (pts) => {
      const out = pts.slice();
      if (Wtop) { out.push([xBack + Wtop, H]); out.push([xBack + Wtop, H - t]); out.push([xBack, H - t]); }
      out.push([xBack, zSoffBack]); out.push([xBot, 0]);
      return out;
    };
    const rowTop = saw(n, N, T), rowPoly = close(rowTop);
    const stairTop = k > 1 ? saw(n * k, N / k, T / k) : null;
    const stairPoly = stairTop ? close(stairTop) : null;
    // muescas: zona del costado de grada visible junto a la escalera (diferencia grada − escalones)
    const notches = [];
    if (k > 1) {
      const ce = N / k, he = T / k;
      for (let i = 0; i < n; i++) {
        const xf = x0 + i * T, zb = i * N, zt = zb + N;
        const pts = [[xf, zb], [xf, zt], [xf + (k - 1) * he, zt]];
        for (let j = k - 1; j >= 1; j--) { pts.push([xf + j * he, zb + j * ce]); pts.push([xf + (j - 1) * he, zb + j * ce]); }
        notches.push(pts);
      }
    }
    const rows = []; for (let i = 1; i <= n; i++) rows.push({ i, z: i * N, xf: x0 + (i - 1) * T, xb: x0 + i * T });
    const solera = x0 ? [[0, -0.1], [x0, -0.1], [x0, 0], [0, 0]] : null;
    return { rowTop, rowPoly, stairTop, stairPoly, notches, rows, solera, x0, Wtop, H, xBack, xMax: xBack + Wtop, len, xTopSoff: xBack, xBot, zSoffBack };
  }

  function designBleacher(p) {
    const H = p.H, L = p.L, B = p.B, t = p.t, k = p.accessStair ? p.stepsPerRow : 0;
    const aisle = p.aisle ? { pos: p.aislePos, W: p.Wp } : null;
    const Lu = L - (aisle ? aisle.W : 0);
    const Nmid = (p.Nmin + p.Nmax) / 2, Tmid = (p.Tmin + p.Tmax) / 2;
    const evalN = (n) => {
      const N = H / n, T = Lu / n;
      const NOk = N >= p.Nmin - 1e-9 && N <= p.Nmax + 1e-9, TOk = T >= p.Tmin - 1e-9 && T <= p.Tmax + 1e-9, geomOk = Lu > 0 && T > 0;
      const score = Math.abs(N - Nmid) / (p.Nmax - p.Nmin) + Math.abs(T - Tmid) / (p.Tmax - p.Tmin) + (NOk ? 0 : 5) + (TOk ? 0 : 5) + (geomOk ? 0 : 100);
      return { n, N, T, NOk, TOk, geomOk, score };
    };
    const nlo = Math.max(1, Math.ceil(H / p.Nmax - 1e-9)), nhi = Math.floor(H / p.Nmin + 1e-9);
    const cands = []; for (let n = nlo; n <= nhi; n++) cands.push(evalN(n));
    if (!cands.length) cands.push(evalN(Math.max(1, Math.round(H / Nmid))));
    cands.sort((a, b) => a.score - b.score);
    const s = cands[0];
    const TDraw = s.geomOk ? s.T : Tmid;
    const g = bleacherGeometry(s.n, s.N, TDraw, t, k, aisle);
    const Lrec = s.n * clamp(TDraw, p.Tmin, p.Tmax) + (aisle ? aisle.W : 0);
    const angle = Math.atan2(s.N, TDraw);

    const checks = [];
    checks.push({ lv: s.NOk ? "ok" : "bad", text: "Peralte N = " + fmt(s.N, 3) + " m" + (s.NOk ? " dentro de " : " fuera de ") + fmt(p.Nmin, 2) + "–" + fmt(p.Nmax, 2) + " m" });
    if (!s.geomOk) checks.push({ lv: "bad", text: "El pasillo consume toda la longitud L: aumenta L o reduce el pasillo." });
    else checks.push({ lv: s.TOk ? "ok" : (s.T > p.Tmax ? "warn" : "bad"), text: "Profundidad T = " + fmt(s.T, 3) + " m" + (s.TOk ? " dentro de " : (s.T < p.Tmin ? " (corta) · mín " : " (larga) · máx ")) + (s.TOk ? fmt(p.Tmin, 2) + "–" + fmt(p.Tmax, 2) + " m" : (s.T < p.Tmin ? fmt(p.Tmin, 2) : fmt(p.Tmax, 2)) + " m") });
    if (s.geomOk && !s.TOk) checks.push({ lv: s.T > p.Tmax ? "warn" : "bad", text: (s.T > p.Tmax ? "Sobra longitud: " : "L insuficiente: ") + "con " + s.n + " gradas conviene L = " + fmt(Lrec, 2) + " m" + (aisle ? " (incluido pasillo de " + fmt(aisle.W, 2) + ")" : (s.T > p.Tmax ? " o destina el sobrante (" + fmt(L - Lrec, 2) + " m) a un pasillo" : "")), action: { label: "Usar " + fmt(Lrec, 2), value: Lrec } });
    else if (s.geomOk) checks.push({ lv: "ok", text: "L = " + fmt(L, 2) + " m encaja: " + s.n + " gradas × " + fmt(s.T, 3) + (aisle ? " + pasillo " + fmt(aisle.W, 2) : "") });
    let ce = 0, he = 0;
    if (k > 1) {
      ce = s.N / k; he = TDraw / k;
      checks.push({ lv: ce <= 0.2 + 1e-9 ? "ok" : (ce <= 0.225 ? "warn" : "bad"), text: "Escalera de acceso: " + k + " escalones por grada de c = " + fmt(ce, 3) + " y h = " + fmt(he, 3) + " m" + (ce <= 0.2 + 1e-9 ? " (c ≤ 0.20 ✓)" : " · contrahuella alta, prueba " + (k + 1) + " escalones por grada") });
    }
    checks.push({ lv: "ok", text: "Pendiente del graderío " + fmt(deg(angle), 1) + "° (" + fmt(100 * Math.tan(angle), 0) + " %)" });

    // visibilidad (valor C): espectador de delante en la fila i−1, ojo a eyeH sobre la grada, al centro de la fila
    let vis = null;
    if (p.vis && s.n >= 2) {
      vis = [];
      for (let i = 2; i <= s.n; i++) {
        const xFrontEye = g.x0 + (i - 2) * TDraw + TDraw / 2, zFrontEye = (i - 1) * s.N + p.eyeH;
        const D = p.Df + xFrontEye, R = zFrontEye - p.hf;
        const C = D * (s.N + R) / (D + TDraw) - R;
        vis.push({ i, C });
      }
      const Cmin = Math.min.apply(null, vis.map((v) => v.C));
      checks.push({ lv: Cmin >= 0.09 ? "ok" : Cmin >= 0.06 ? "warn" : "bad", text: "Visibilidad: C mínimo " + fmt(Cmin, 3) + " m en la fila " + vis.filter((v) => v.C === Cmin)[0].i + (Cmin >= 0.09 ? " (bueno, ≥ 0.09)" : Cmin >= 0.06 ? " (aceptable, 0.06–0.09)" : " (insuficiente, < 0.06): sube el peralte o acerca el punto focal") });
    }
    const seatWidth = B - (k > 1 ? p.Be : 0);
    const capacity = s.n * Math.max(0, Math.floor(seatWidth / 0.5));

    // mallas 3D
    const meshes = [];
    if (g.solera) meshes.push({ faces: extrude(g.solera, 0, B, COL.solera, true, true), yc: B / 2, first: true });
    if (k > 1 && p.Be < B) {
      const y1 = (B - p.Be) / 2, y2 = (B + p.Be) / 2;
      meshes.push({ faces: extrude(g.rowPoly, 0, y1, COL.concrete, true, false), yc: y1 / 2 });
      meshes.push({ faces: g.notches.map((pts) => ({ pts: pts.map(([x, z]) => [x, y1, z]), n: [0, 1, 0], col: COL.concrete, cap: true })), yc: y1 - 1e-4 });
      meshes.push({ faces: extrude(g.stairPoly, y1, y2, COL.stair, false, false), yc: B / 2 });
      meshes.push({ faces: g.notches.map((pts) => ({ pts: pts.map(([x, z]) => [x, y2, z]), n: [0, -1, 0], col: COL.concrete, cap: true })), yc: y2 + 1e-4 });
      meshes.push({ faces: extrude(g.rowPoly, y2, B, COL.concrete, false, true), yc: (y2 + B) / 2 });
    } else meshes.push({ faces: extrude(k > 1 ? g.stairPoly : g.rowPoly, 0, B, COL.concrete, true, true), yc: B / 2 });

    const areaRow = polyArea(g.rowPoly), areaStair = g.stairPoly ? polyArea(g.stairPoly) : 0;
    const volume = (k > 1 && p.Be < B) ? areaRow * (B - p.Be) + areaStair * p.Be : (k > 1 ? areaStair : areaRow) * B + (g.solera ? polyArea(g.solera) * B : 0);
    const soffit = Math.hypot(g.xTopSoff - g.xBot, g.zSoffBack) * B;
    const risersArea = s.n * s.N * B + (g.Wtop ? 0 : 0);
    const back = (g.H - g.zSoffBack + (g.Wtop ? 0 : 0)) * B + (g.Wtop ? t * B : 0);
    const sides = 2 * areaRow;
    const form = soffit + risersArea + back + sides;

    const table = g.rows.map((r, idx) => {
      const row = [r.i, fmt(r.z, 3), fmt(r.xb - g.x0, 2), fmt(s.N, 3), fmt(TDraw, 3)];
      if (vis) { const v = vis.filter((q) => q.i === r.i)[0]; row.push(v ? { v: fmt(v.C, 3), lv: v.C >= 0.09 ? "ok" : v.C >= 0.06 ? "warn" : "bad" } : "—"); }
      return row;
    });
    const tableHead = ["Fila", "Cota asiento (m)", "Fondo acum. (m)", "N (m)", "T (m)"]; if (vis) tableHead.push("C (m)");

    const kpis = [
      { k: "Gradas", v: s.n, u: "ud", d: "filas" },
      { k: "Peralte N", v: fmt(s.N, 3), u: "m", lv: s.NOk ? "ok" : "bad" },
      { k: "Profundidad T", v: fmt(s.T, 3), u: "m", lv: s.TOk ? "ok" : (s.T > p.Tmax ? "warn" : "bad") },
      { k: "Pendiente", v: fmt(deg(angle), 1), u: "°" },
      { k: "Aforo aprox.", v: capacity, u: "pers.", d: "0.50 m por asiento" },
      { k: "Hormigón", v: fmt(volume, 1), u: "m³" },
    ];
    if (vis) { const Cmin = Math.min.apply(null, vis.map((v) => v.C)); kpis.splice(4, 0, { k: "C mínimo", v: fmt(Cmin, 3), u: "m", d: "objetivo ≥ 0.06–0.09", lv: Cmin >= 0.09 ? "ok" : Cmin >= 0.06 ? "warn" : "bad" }); }

    return {
      mode: "bleacher", p, n: s.n, N: s.N, T: TDraw, TReal: s.T, k, ce, he, aisle, angle, checks, Lrec, geom: g, vis, level: worst(checks), meshes,
      kpis, table, tableHead,
      qty: [
        ["Gradas (filas)", String(s.n)],
        ["Longitud horizontal usada", fmt(g.xMax, 2) + " m"],
        ["Longitud del graderío (frente B)", fmt(B, 2) + " m"],
        ["Escalera de acceso", k > 1 ? p.Be.toFixed(2) + " m de ancho · " + s.n * k + " escalones de " + fmt(ce, 3) + " × " + fmt(he, 3) : "no"],
        ["Pasillo", aisle ? fmt(aisle.W, 2) + " m " + (aisle.pos === "top" ? "superior" : "inferior") : "no"],
        ["Aforo aprox. (0.50 m/asiento)", capacity + " personas"],
        ["Volumen de hormigón", fmt(volume, 1) + " m³"],
        ["Encofrado total aprox.", fmt(form, 1) + " m²"],
        ["· fondo de losa inclinada", fmt(soffit, 1) + " m² (no necesario si apoya en relleno)"],
        ["· tabicas de gradas", fmt(risersArea, 1) + " m²"],
        ["· trasera y costados", fmt(back + sides, 1) + " m²"],
      ],
      qtyNote: "Volumen = área del perfil × longitud (gradas macizas sobre losa inclinada t = " + fmt(t, 2) + " m). Aforo orientativo sin asientos ni separaciones normativas.",
      summary: s.n + " gradas de N = " + fmt(s.N, 3) + " m y T = " + fmt(s.T, 3) + " m" + (k > 1 ? " · escalera de acceso " + k + "×(" + fmt(ce, 3) + "/" + fmt(he, 3) + ")" : "") + (aisle ? " · pasillo " + fmt(aisle.W, 2) : ""),
    };
  }

  function worst(checks) { return checks.some((c) => c.lv === "bad") ? "bad" : checks.some((c) => c.lv === "warn") ? "warn" : "ok"; }
  function polyArea(poly) { let a = 0; for (let i = 0; i < poly.length; i++) { const p1 = poly[i], p2 = poly[(i + 1) % poly.length]; a += p1[0] * p2[1] - p2[0] * p1[1]; } return Math.abs(a) / 2; }

  // ------------------------------------------------------------------ malla 3D (extrusión de un perfil x–z a lo largo de y)
  const COL = { concrete: [206, 210, 219], stair: [216, 206, 188], solera: [186, 192, 204] };
  function extrude(poly, y0, y1, col, capLo, capHi) {
    let area = 0;
    for (let i = 0; i < poly.length; i++) { const p1 = poly[i], p2 = poly[(i + 1) % poly.length]; area += p1[0] * p2[1] - p2[0] * p1[1]; }
    const P = area < 0 ? poly.slice().reverse() : poly;
    const faces = [];
    for (let i = 0; i < P.length; i++) {
      const p1 = P[i], p2 = P[(i + 1) % P.length];
      const dx = p2[0] - p1[0], dz = p2[1] - p1[1], l = Math.hypot(dx, dz);
      if (l < 1e-9) continue;
      faces.push({ pts: [[p1[0], y0, p1[1]], [p2[0], y0, p2[1]], [p2[0], y1, p2[1]], [p1[0], y1, p1[1]]], n: [dz / l, 0, -dx / l], col });
    }
    if (capLo) faces.push({ pts: P.map((q) => [q[0], y0, q[1]]), n: [0, -1, 0], col, cap: true });
    if (capHi) faces.push({ pts: P.map((q) => [q[0], y1, q[1]]), n: [0, 1, 0], col, cap: true });
    return faces;
  }

  // Lista de dibujo ordenada (pintor): mallas de lejos a cerca; dentro de cada malla, caras laterales por
  // profundidad y la tapa visible al final. view = {proj(p) → [sx, sy, depth], visible(n, center), shade(n)}
  function drawList(meshes, view) {
    const groups = meshes.map((m) => {
      const c = centroid(m.faces); const d = view.proj([c[0], m.yc, c[2]])[2];
      return { m, d: m.first ? -Infinity : d };
    });
    groups.sort((a, b) => a.d - b.d);
    const out = [];
    groups.forEach((gp) => {
      const sides = [], caps = [];
      gp.m.faces.forEach((f) => {
        const c = faceCenter(f.pts);
        if (!view.visible(f.n, c)) return;
        const sp = f.pts.map(view.proj);
        const depth = sp.reduce((acc, q) => acc + q[2], 0) / sp.length;
        const item = { sp, depth, col: shadeCol(f.col, view.shade(f.n)) };
        (f.cap ? caps : sides).push(item);
      });
      sides.sort((a, b) => a.depth - b.depth);
      out.push.apply(out, sides); out.push.apply(out, caps);
    });
    return out;
  }
  function faceCenter(pts) { const c = [0, 0, 0]; pts.forEach((p) => { c[0] += p[0]; c[1] += p[1]; c[2] += p[2]; }); return c.map((v) => v / pts.length); }
  function centroid(faces) { const c = [0, 0, 0]; let n = 0; faces.forEach((f) => f.pts.forEach((p) => { c[0] += p[0]; c[1] += p[1]; c[2] += p[2]; n++; })); return c.map((v) => v / n); }
  function shadeCol(col, k) { return "rgb(" + Math.round(col[0] * k) + "," + Math.round(col[1] * k) + "," + Math.round(col[2] * k) + ")"; }
  function norm3(v) { const l = Math.hypot(v[0], v[1], v[2]) || 1; return [v[0] / l, v[1] / l, v[2] / l]; }
  const dot3 = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

  // ------------------------------------------------------------------ SVG: helpers de dibujo técnico
  const SVG_STYLE = "<style>" +
    ".geo{fill:#e9ecf3;stroke:#1f2433;stroke-width:1.4;stroke-linejoin:round}" +
    ".hz{fill:url(#hatch);stroke:none}" +
    ".thin{stroke:#1f2433;stroke-width:.9;fill:none}" +
    ".ref{stroke:#8a92a8;stroke-width:.8;stroke-dasharray:4 3;fill:none}" +
    ".dim{stroke:#3f49c4;stroke-width:.9;fill:none}" +
    ".arr{fill:#3f49c4;stroke:none}" +
    ".dt{fill:#2b34a6;font-size:11px;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round;font-variant-numeric:tabular-nums}" +
    ".tx{fill:#1f2433;font-size:11px;paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}" +
    ".ttl{fill:#1f2433;font-size:12px;font-weight:700;letter-spacing:.08em}" +
    ".sub{fill:#5a6275;font-size:10.5px}" +
    ".num{fill:#1f2433;font-size:10px;font-weight:600;text-anchor:middle}" +
    ".lvl{fill:#fff;stroke:#1f2433;stroke-width:1}" +
    ".ground{stroke:#1f2433;stroke-width:2}" +
    ".eye{fill:#d97706;stroke:#fff;stroke-width:1}" +
    "</style>";
  const HATCH = '<defs><pattern id="hatch" width="7" height="7" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="7" stroke="#9aa3ba" stroke-width="0.8"/></pattern>' +
    '<pattern id="hatch2" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(-45)"><line x1="0" y1="0" x2="0" y2="6" stroke="#c3c9d6" stroke-width="0.7"/></pattern></defs>';
  let svgSeq = 0;
  function svgOpen(w, h) {
    const id = "g" + (++svgSeq) + "_";
    return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' + w + " " + h + '" width="' + w + '" height="' + h + '" font-family="' + FONT.replace(/'/g, "") + '">' +
      SVG_STYLE.replace("url(#hatch)", "url(#" + id + "hatch)") + HATCH.replace('id="hatch"', 'id="' + id + 'hatch"').replace('id="hatch2"', 'id="' + id + 'hatch2"') +
      '<rect width="' + w + '" height="' + h + '" fill="#fff"/>' + "<!--" + id + "-->";
  }
  const hatch2 = (o) => "url(#" + (o.match(/<!--(g\d+_)-->/) || [0, ""])[1] + "hatch2)";
  const pline = (pts, cls) => "<polygon points=\"" + pts.map((q) => q[0].toFixed(1) + "," + q[1].toFixed(1)).join(" ") + "\" class=\"" + cls + "\"/>";
  const line = (x1, y1, x2, y2, cls) => '<line x1="' + x1.toFixed(1) + '" y1="' + y1.toFixed(1) + '" x2="' + x2.toFixed(1) + '" y2="' + y2.toFixed(1) + '" class="' + cls + '"/>';
  const text = (x, y, s, cls, anchor, extra) => '<text x="' + x.toFixed(1) + '" y="' + y.toFixed(1) + '" class="' + cls + '"' + (anchor ? ' text-anchor="' + anchor + '"' : "") + (extra ? " " + extra : "") + ">" + esc(s) + "</text>";
  function arrow(x, y, dx, dy) { // punta en (x,y) apuntando en dirección (dx,dy) unitaria
    const L = 8, Wd = 2.6, bx = x - dx * L, by = y - dy * L, px = -dy, py = dx;
    return '<path class="arr" d="M' + x.toFixed(1) + " " + y.toFixed(1) + "L" + (bx + px * Wd).toFixed(1) + " " + (by + py * Wd).toFixed(1) + "L" + (bx - px * Wd).toFixed(1) + " " + (by - py * Wd).toFixed(1) + 'Z"/>';
  }
  // cota entre dos puntos de pantalla con línea de cota en (x1,y1)-(x2,y2) y líneas de referencia desde (ex1,ey1),(ex2,ey2)
  function dimLine(x1, y1, x2, y2, ex1, ey1, ex2, ey2, label, side) {
    const dx = x2 - x1, dy = y2 - y1, L = Math.hypot(dx, dy) || 1, ux = dx / L, uy = dy / L;
    let s = line(ex1, ey1, x1 - uy * 0 + (x1 - ex1) * 0.08, y1 + (y1 - ey1) * 0.08, "dim") + line(ex2, ey2, x2 + (x2 - ex2) * 0.08, y2 + (y2 - ey2) * 0.08, "dim");
    const inside = L > 26;
    s += inside ? line(x1, y1, x2, y2, "dim") : line(x1 - ux * 18, y1 - uy * 18, x2 + ux * 18, y2 + uy * 18, "dim");
    s += inside ? arrow(x1, y1, -ux, -uy) + arrow(x2, y2, ux, uy) : arrow(x1, y1, ux, uy) + arrow(x2, y2, -ux, -uy);
    const mx = (x1 + x2) / 2, my = (y1 + y2) / 2;
    if (Math.abs(ux) > 0.5) s += text(mx, my - 4, label, "dt", "middle");
    else s += '<text class="dt" text-anchor="middle" transform="translate(' + (mx + (side === "right" ? 12 : -4)).toFixed(1) + " " + my.toFixed(1) + ') rotate(-90)">' + esc(label) + "</text>";
    return s;
  }
  function levelMark(x, y, label, below) {
    return '<path class="lvl" d="M' + x.toFixed(1) + " " + y.toFixed(1) + "l-5 -8h10z\"/>" + (below ? text(x - 6, y + 17, label, "tx") : text(x + 8, y - 3, label, "tx"));
  }
  function scaleBar(x, y, s) {
    const unit = s * 0.25 >= 14 ? 0.25 : 0.5, nseg = unit === 0.25 ? 4 : 2;
    let out = "";
    for (let i = 0; i < nseg; i++) out += '<rect x="' + (x + i * unit * s).toFixed(1) + '" y="' + y + '" width="' + (unit * s).toFixed(1) + '" height="5" fill="' + (i % 2 ? "#fff" : "#1f2433") + '" stroke="#1f2433" stroke-width=".8"/>';
    out += text(x, y + 16, "0", "sub") + text(x + 0.5 * s, y + 16, "0.5", "sub", "middle") + text(x + s, y + 16, "1 m", "sub", "middle");
    out += text(x + s + 34, y + 5, "Cotas en metros", "sub");
    return out;
  }
  // ajuste de escala: mundo (wx0..wx1, wz0..wz1) en un ancho W con márgenes; devuelve mapeo
  function fitMap(W, wx0, wx1, wz0, wz1, mL, mR, mT, mB, maxAspect) {
    let s = (W - mL - mR) / (wx1 - wx0);
    let Hs = (wz1 - wz0) * s + mT + mB;
    const maxH = W * (maxAspect || 0.78);
    if (Hs > maxH) { s = (maxH - mT - mB) / (wz1 - wz0); Hs = maxH; }
    const drawW = (wx1 - wx0) * s, offX = mL + (W - mL - mR - drawW) / 2;
    return { s, W, H: Math.ceil(Hs), X: (x) => offX + (x - wx0) * s, Y: (z) => mT + (wz1 - z) * s };
  }

  // ------------------------------------------------------------------ SVG: corte
  function svgSection(d, W) {
    const g = d.geom, isStair = d.mode === "stair";
    const xMin = -0.6, xMax = g.xMax + 0.75, zMin = -0.22, zMax = g.H + (d.mode === "bleacher" && d.vis ? d.p.eyeH + 0.25 : 0.45);
    const M = fitMap(W, xMin, xMax, zMin, zMax, 12, 12, 40, 92, 0.64);
    const X = M.X, Y = M.Y, s = M.s;
    let o = svgOpen(M.W, M.H);
    const yG = Y(0);
    // suelo y nivel superior de referencia
    o += line(X(xMin), yG, X(xMax), yG, "ground");
    for (let x = X(xMin); x < X(xMax); x += 9) o += line(x, yG, x - 5, yG + 5, "thin");
    if (isStair) o += line(X(g.xEnd), Y(g.H), X(xMax), Y(g.H), "ref");
    // perfil
    const P = (g.mode === undefined && isStair ? g.poly : (isStair ? g.poly : g.rowPoly)).map((q) => [X(q[0]), Y(q[1])]);
    if (!isStair && g.solera) { const S = g.solera.map((q) => [X(q[0]), Y(q[1])]); o += pline(S, "geo") + pline(S, "hz"); }
    o += pline(P, "geo") + pline(P, "hz");
    if (!isStair && g.stairTop) {
      o += '<polyline points="' + g.stairTop.map((q) => X(q[0]).toFixed(1) + "," + Y(q[1]).toFixed(1)).join(" ") + '" class="ref" stroke="#b45309"/>';
      o += text(X(g.x0 + g.rows[0].xb - g.x0 + 0.1), Y(d.N / d.k) - 4, "escalera de acceso (franja central)", "sub", "start", 'fill="#b45309"');
    }
    if (!isStair && d.vis) g.rows.forEach((r) => { const ex = X((r.xf + r.xb) / 2), ey = Y(r.z + d.p.eyeH); o += '<circle class="eye" cx="' + ex.toFixed(1) + '" cy="' + ey.toFixed(1) + '" r="3"/>' + line(ex, ey, ex, Y(r.z), "ref"); });
    // cotas horizontales: fila A por tramos, fila B total
    const rowA = Y(zMin) + 18, rowB = rowA + 24;
    if (isStair) {
      g.flights.forEach((F, k) => {
        o += dimLine(X(F.xs), rowA, X(F.xe), rowA, X(F.xs), yG, X(F.xe), Y(F.ze), (F.nk - 1) + " × " + fmt(d.h, 3) + " = " + fmt(F.xe - F.xs, 2));
        if (k < g.flights.length - 1) o += dimLine(X(F.xe), rowA, X(F.xe + d.Ld), rowA, X(F.xe), Y(F.ze), X(F.xe + d.Ld), Y(F.ze), "Ld = " + fmt(d.Ld, 2));
      });
      o += dimLine(X(0), rowB, X(g.xEnd), rowB, X(0), yG, X(g.xEnd), Y(g.H), "L = " + fmt(g.xEnd, 2));
      // c (primera contrahuella) y h (primera huella)
      o += dimLine(X(0) - 22, yG, X(0) - 22, Y(d.c), X(0), yG, X(0), Y(d.c), "c = " + fmt(d.c, 3));
      if (g.flights[0].nk > 1) o += dimLine(X(0), Y(2 * d.c + 0.22), X(d.h), Y(2 * d.c + 0.22), X(0), Y(d.c), X(d.h), Y(2 * d.c), "h = " + fmt(d.h, 3));
      // H total a la derecha
      o += dimLine(X(g.xMax) + 24, yG, X(g.xMax) + 24, Y(g.H), X(g.xMax), yG, X(g.xMax), Y(g.H), "H = " + fmt(g.H, 2), "right");
      // garganta
      const F0 = g.flights[0], xm = (F0.xTop + F0.xBot) / 2, zm = F0.zs - d.p.t * d.h / F0.len + (xm - F0.xs - d.p.t * d.c / F0.len) * (d.c / d.h);
      o += line(X(xm), Y(zm), X(xm + 0.45), Y(zm - 0.3), "thin") + text(X(xm + 0.5), Y(zm - 0.3) + 4, "garganta t = " + fmt(d.p.t, 2), "tx");
      // niveles
      o += levelMark(X(-0.42), yG, "±0.00", true) + levelMark(X(g.xEnd + g.a / 2), Y(g.H), "+" + fmt(g.H, 2));
      g.flights.slice(0, -1).forEach((F) => { o += levelMark(X(F.xe + d.Ld / 2), Y(F.ze), "+" + fmt(F.ze, 2)); });
      o += text(X(g.xEnd + 0.08), Y(g.H) - 14, "nivel superior", "sub");
    } else {
      if (g.x0) o += dimLine(X(0), rowA, X(g.x0), rowA, X(0), yG, X(g.x0), yG, "pasillo " + fmt(g.x0, 2));
      o += dimLine(X(g.x0), rowA, X(g.xBack), rowA, X(g.x0), yG, X(g.xBack), Y(g.H), d.n + " × " + fmt(d.T, 3) + " = " + fmt(g.xBack - g.x0, 2));
      if (g.Wtop) o += dimLine(X(g.xBack), rowA, X(g.xMax), rowA, X(g.xBack), Y(g.H), X(g.xMax), Y(g.H), "pasillo " + fmt(g.Wtop, 2));
      o += dimLine(X(0), rowB, X(g.xMax), rowB, X(0), yG, X(g.xMax), Y(g.H), "L = " + fmt(g.xMax, 2));
      o += dimLine(X(g.x0) - 22, yG, X(g.x0) - 22, Y(d.N), X(g.x0), yG, X(g.x0), Y(d.N), "N = " + fmt(d.N, 3));
      o += dimLine(X(g.x0), Y(Math.min(2 * d.N, g.H) + 0.22), X(g.x0 + d.T), Y(Math.min(2 * d.N, g.H) + 0.22), X(g.x0), Y(d.N), X(g.x0 + d.T), Y(Math.min(2 * d.N, g.H)), "T = " + fmt(d.T, 3));
      o += dimLine(X(g.xMax) + 24, yG, X(g.xMax) + 24, Y(g.H), X(g.xMax), yG, X(g.xMax), Y(g.H), "H = " + fmt(g.H, 2), "right");
      const xm = (g.xBot + g.xBack) / 2, zm = (g.zSoffBack) * (xm - g.xBot) / (g.xBack - g.xBot);
      o += line(X(xm), Y(zm), X(xm + 0.45), Y(zm - 0.3), "thin") + text(X(xm + 0.5), Y(zm - 0.3) + 4, "losa t = " + fmt(d.p.t, 2), "tx");
      o += levelMark(X(-0.42), yG, "±0.00", true) + levelMark(X(g.xBack - d.T / 2), Y(g.H), "+" + fmt(g.H, 2));
      g.rows.forEach((r) => { if (M.s * d.T > 22) o += text(X((r.xf + r.xb) / 2), Y(r.z) + 11, String(r.i), "num"); });
    }
    o += text(14, 18, isStair ? "CORTE A-A · ESCALERA" : "CORTE A-A · GRADERÍO", "ttl");
    if (W >= 560) o += text(14, 31, d.summary, "sub");
    o += scaleBar(X(xMin) + 2, rowB + 22, s);
    return o + "</svg>";
  }

  // ------------------------------------------------------------------ SVG: planta
  function svgPlan(d, W) {
    const g = d.geom, B = d.p.B;
    let o;
    if (d.mode === "stair") {
      const xMin = -0.5, xMax = g.xMax + 0.75, yMin = -0.2, yMax = B + 0.45;
      const M = fitMap(W, xMin, xMax, yMin, yMax, 12, 12, 40, 78, 0.7);
      const X = M.X, Y = M.Y;
      o = svgOpen(M.W, M.H);
      o += '<rect x="' + X(0).toFixed(1) + '" y="' + Y(B).toFixed(1) + '" width="' + (X(g.xMax) - X(0)).toFixed(1) + '" height="' + (Y(0) - Y(B)).toFixed(1) + '" class="geo" fill="#f4f6fa"/>';
      // descansos y llegada
      g.flights.forEach((F, k) => {
        if (k < g.flights.length - 1) {
          o += '<rect x="' + X(F.xe).toFixed(1) + '" y="' + Y(B).toFixed(1) + '" width="' + (X(F.xe + d.Ld) - X(F.xe)).toFixed(1) + '" height="' + (Y(0) - Y(B)).toFixed(1) + '" fill="' + hatch2(o) + '" stroke="none"/>';
          o += text(X(F.xe + d.Ld / 2), Y(B * 0.5) + 4, "DESCANSO", "tx", "middle");
        }
      });
      o += '<rect x="' + X(g.xEnd).toFixed(1) + '" y="' + Y(B).toFixed(1) + '" width="' + (X(g.xMax) - X(g.xEnd)).toFixed(1) + '" height="' + (Y(0) - Y(B)).toFixed(1) + '" fill="' + hatch2(o) + '" stroke="none"/>';
      // peldaños
      g.steps.forEach((st) => {
        o += line(X(st.x), Y(0), X(st.x), Y(B), "thin");
        if (st.h != null && M.s * d.h > 16) o += text(X(st.x + d.h / 2), Y(B) + 12, String(st.i), "num");
      });
      o += text(X(g.xEnd), Y(B) + 12, String(d.n), "num", undefined, 'dx="' + (M.s * g.a / 2).toFixed(1) + '"');
      // línea de subida
      const yw = Y(B * 0.45);
      o += '<circle cx="' + X(0.14).toFixed(1) + '" cy="' + yw.toFixed(1) + '" r="3.5" fill="#1f2433"/>' + line(X(0.14), yw, X(g.xEnd + g.a * 0.55) - 2, yw, "thin") + arrow(X(g.xEnd + g.a * 0.55), yw, 1, 0).replace('class="arr"', 'class="arr" fill="#1f2433"');
      o += text(X(0.3), yw - 6, "SUBE", "tx");
      o += text(X(g.xEnd + 0.06), Y(B * 0.15), "+" + fmt(g.H, 2), "tx");
      // cotas
      const rowA = Y(0) + 18, rowB = rowA + 24;
      g.flights.forEach((F, k) => {
        o += dimLine(X(F.xs), rowA, X(F.xe), rowA, X(F.xs), Y(0), X(F.xe), Y(0), (F.nk - 1) + " × " + fmt(d.h, 3) + " = " + fmt(F.xe - F.xs, 2));
        if (k < g.flights.length - 1) o += dimLine(X(F.xe), rowA, X(F.xe + d.Ld), rowA, X(F.xe), Y(0), X(F.xe + d.Ld), Y(0), "Ld = " + fmt(d.Ld, 2));
      });
      o += dimLine(X(0), rowB, X(g.xEnd), rowB, X(0), Y(0), X(g.xEnd), Y(0), "L = " + fmt(g.xEnd, 2));
      o += dimLine(X(g.xMax) + 24, Y(0), X(g.xMax) + 24, Y(B), X(g.xMax), Y(0), X(g.xMax), Y(B), "B = " + fmt(B, 2), "right");
      if (g.flights[0].nk > 1) o += dimLine(X(0), Y(B + 0.2), X(d.h), Y(B + 0.2), X(0), Y(B), X(d.h), Y(B), "h = " + fmt(d.h, 3));
      o += text(14, 18, "PLANTA · ESCALERA", "ttl"); if (W >= 560) o += text(14, 31, d.n + " contrahuellas · " + d.f + (d.f > 1 ? " tramos" : " tramo") + " · ancho " + fmt(B, 2) + " m", "sub");
      o += scaleBar(X(xMin) + 2, rowB + 22, M.s);
      return o + "</svg>";
    }
    // graderío: frente B en horizontal, fondo hacia arriba (campo abajo)
    const yMin = -0.5, yMax = B + 0.3 + 60 / 60, dMin = -0.25, dMax = g.xMax + 0.45;
    const M = fitMap(W, yMin, yMax, dMin, dMax, 12, 12, 40, 104, 0.8);
    const X = M.X, Yd = M.Y; // Yd(depth): x del mundo (fondo)
    o = svgOpen(M.W, M.H);
    o += '<rect x="' + X(0).toFixed(1) + '" y="' + Yd(g.xMax).toFixed(1) + '" width="' + (X(B) - X(0)).toFixed(1) + '" height="' + (Yd(0) - Yd(g.xMax)).toFixed(1) + '" class="geo" fill="#f4f6fa"/>';
    if (g.x0) { o += '<rect x="' + X(0).toFixed(1) + '" y="' + Yd(g.x0).toFixed(1) + '" width="' + (X(B) - X(0)).toFixed(1) + '" height="' + (Yd(0) - Yd(g.x0)).toFixed(1) + '" fill="' + hatch2(o) + '"/>' + text(X(B / 2), (Yd(0) + Yd(g.x0)) / 2 + 4, "PASILLO", "tx", "middle"); }
    if (g.Wtop) { o += '<rect x="' + X(0).toFixed(1) + '" y="' + Yd(g.xMax).toFixed(1) + '" width="' + (X(B) - X(0)).toFixed(1) + '" height="' + (Yd(g.xBack) - Yd(g.xMax)).toFixed(1) + '" fill="' + hatch2(o) + '"/>' + text(X(B / 2), (Yd(g.xBack) + Yd(g.xMax)) / 2 + 4, "PASILLO", "tx", "middle"); }
    g.rows.forEach((r) => {
      o += line(X(0), Yd(r.xf), X(B), Yd(r.xf), "thin");
      if (M.s * d.T > 14) o += text(X(0.12), (Yd(r.xf) + Yd(r.xb)) / 2 + 3.5, String(r.i), "num", undefined, 'text-anchor="start"');
    });
    o += line(X(0), Yd(g.xBack), X(B), Yd(g.xBack), "thin");
    if (d.k > 1 && d.p.Be < B) {
      const y1 = (B - d.p.Be) / 2, y2 = (B + d.p.Be) / 2;
      o += line(X(y1), Yd(g.x0), X(y1), Yd(g.xBack), "thin") + line(X(y2), Yd(g.x0), X(y2), Yd(g.xBack), "thin");
      g.rows.forEach((r) => { for (let j = 1; j < d.k; j++) o += line(X(y1), Yd(r.xf + j * d.he), X(y2), Yd(r.xf + j * d.he), "thin"); });
      const xc = X(B / 2);
      o += '<circle cx="' + xc.toFixed(1) + '" cy="' + (Yd(0) - 6).toFixed(1) + '" r="3.5" fill="#1f2433"/>' + line(xc, Yd(0) - 6, xc, Yd(g.xBack) + 10, "thin") + arrow(xc, Yd(g.xBack) + 2, 0, -1).replace('class="arr"', 'class="arr" fill="#1f2433"');
      o += '<text class="tx" transform="translate(' + (xc + 12).toFixed(1) + " " + (Yd(g.x0 + d.T) ).toFixed(1) + ') rotate(-90)">SUBE</text>';
      o += dimLine(X(y1), Yd(0) + 18, X(y2), Yd(0) + 18, X(y1), Yd(0), X(y2), Yd(0), "Be = " + fmt(d.p.Be, 2));
    }
    o += text(X(B / 2), Yd(0) + 66, "CAMPO / PUNTO FOCAL", "sub", "middle");
    o += dimLine(X(0), Yd(0) + 42, X(B), Yd(0) + 42, X(0), Yd(0), X(B), Yd(0), "B = " + fmt(B, 2));
    o += dimLine(X(B) + 22, Yd(g.x0), X(B) + 22, Yd(g.x0 + d.T), X(B), Yd(g.x0), X(B), Yd(g.x0 + d.T), "T = " + fmt(d.T, 3), "right");
    o += dimLine(X(B) + 50, Yd(0), X(B) + 50, Yd(g.xMax), X(B), Yd(0), X(B), Yd(g.xMax), "L = " + fmt(g.xMax, 2), "right");
    o += text(14, 18, "PLANTA · GRADERÍO", "ttl"); if (W >= 560) o += text(14, 31, d.n + " gradas · frente " + fmt(B, 2) + " m · fondo " + fmt(g.xMax, 2) + " m", "sub");
    o += scaleBar(X(yMin) + 2, Yd(0) + 82, M.s);
    return o + "</svg>";
  }

  // ------------------------------------------------------------------ SVG: isométrico (proyección isométrica real, 30°)
  const ISO_VIEW_DIR = norm3([-1, 1, 1]);
  const ISO_LIGHT = norm3([-0.55, 0.3, 1]);
  function isoProj(p) { const u = -p[0], v = p[1]; return [(u - v) * 0.8660254, (u + v) * 0.5 - p[2], u + v + p[2]]; }
  function svgIso(d, W) {
    const g = d.geom, B = d.p.B, xE = d.mode === "stair" ? g.xEnd : g.xMax;
    const view = { proj: isoProj, visible: (n) => dot3(n, ISO_VIEW_DIR) > 1e-6, shade: (n) => 0.52 + 0.48 * Math.max(0, dot3(n, ISO_LIGHT)) };
    const list = drawList(d.meshes, view);
    // cotas generales en isométrico
    const dims = [
      { a: [0, 0, 0], b: [0, B, 0], off: [-0.55, 0, 0], label: "B = " + fmt(B, 2) },
      { a: [0, B, 0], b: [xE, B, 0], off: [0, 0.55, 0], label: "L = " + fmt(xE, 2) },
      { a: [xE, B, 0], b: [xE, B, g.H], off: [0, 0.55, 0], label: "H = " + fmt(g.H, 2) },
    ];
    const pts = [];
    list.forEach((f) => f.sp.forEach((q) => pts.push(q)));
    dims.forEach((dm) => { pts.push(isoProj([dm.a[0] + dm.off[0] * 1.4, dm.a[1] + dm.off[1] * 1.4, dm.a[2]])); pts.push(isoProj([dm.b[0] + dm.off[0] * 1.4, dm.b[1] + dm.off[1] * 1.4, dm.b[2]])); });
    let x0 = Infinity, x1 = -Infinity, y0 = Infinity, y1 = -Infinity;
    pts.forEach((q) => { x0 = Math.min(x0, q[0]); x1 = Math.max(x1, q[0]); y0 = Math.min(y0, q[1]); y1 = Math.max(y1, q[1]); });
    const mL = 40, mR = 40, mT = 44, mB = 30;
    let s = (W - mL - mR) / (x1 - x0); let Hs = (y1 - y0) * s + mT + mB;
    if (Hs > W * 0.66) { s = (W * 0.66 - mT - mB) / (y1 - y0); Hs = W * 0.66; }
    const offX = mL + (W - mL - mR - (x1 - x0) * s) / 2;
    const P = (q) => [offX + (q[0] - x0) * s, mT + (q[1] - y0) * s];
    let o = svgOpen(W, Math.ceil(Hs));
    list.forEach((f) => {
      o += '<polygon points="' + f.sp.map((q) => { const r = P(q); return r[0].toFixed(1) + "," + r[1].toFixed(1); }).join(" ") + '" fill="' + f.col + '" stroke="#2a3040" stroke-width=".8" stroke-linejoin="round"/>';
    });
    dims.forEach((dm) => {
      const a = P(isoProj([dm.a[0] + dm.off[0], dm.a[1] + dm.off[1], dm.a[2] + dm.off[2]])), b = P(isoProj([dm.b[0] + dm.off[0], dm.b[1] + dm.off[1], dm.b[2] + dm.off[2]]));
      const ea = P(isoProj(dm.a)), eb = P(isoProj(dm.b));
      const ux = (b[0] - a[0]) / (Math.hypot(b[0] - a[0], b[1] - a[1]) || 1), uy = (b[1] - a[1]) / (Math.hypot(b[0] - a[0], b[1] - a[1]) || 1);
      o += line(ea[0], ea[1], a[0] + (a[0] - ea[0]) * 0.15, a[1] + (a[1] - ea[1]) * 0.15, "dim") + line(eb[0], eb[1], b[0] + (b[0] - eb[0]) * 0.15, b[1] + (b[1] - eb[1]) * 0.15, "dim");
      o += line(a[0], a[1], b[0], b[1], "dim") + arrow(a[0], a[1], -ux, -uy) + arrow(b[0], b[1], ux, uy);
      const mx = (a[0] + b[0]) / 2 + (a[0] - ea[0]) * 0.35, my = (a[1] + b[1]) / 2 + (a[1] - ea[1]) * 0.35;
      o += text(mx, my + 4, dm.label, "dt", "middle");
    });
    o += text(14, 18, "ISOMÉTRICO", "ttl"); if (W >= 560) o += text(14, 31, "Proyección isométrica (ejes a 30°, sin escala) · " + d.summary, "sub");
    return o + "</svg>";
  }

  // ------------------------------------------------------------------ 3D interactivo (canvas 2D, proyección propia)
  const three = { yaw: -0.75, pitch: 0.5, zoom: 1, design: null, canvas: null, ctx: null, ptrs: new Map(), pinch: 0 };
  function setup3D() {
    const cv = $("#c3d"); three.canvas = cv; three.ctx = cv.getContext("2d");
    cv.addEventListener("pointerdown", (e) => { cv.setPointerCapture(e.pointerId); three.ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY }); if (three.ptrs.size === 2) three.pinch = pinchDist(); e.preventDefault(); });
    cv.addEventListener("pointermove", (e) => {
      const prev = three.ptrs.get(e.pointerId); if (!prev) return;
      if (three.ptrs.size === 1) { three.yaw += (e.clientX - prev.x) * 0.011; three.pitch = clamp(three.pitch + (e.clientY - prev.y) * 0.011, -0.3, 1.5); }
      three.ptrs.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (three.ptrs.size === 2) { const dnow = pinchDist(); if (three.pinch > 0) three.zoom = clamp(three.zoom * dnow / three.pinch, 0.3, 6); three.pinch = dnow; }
      draw3D();
    });
    const up = (e) => { three.ptrs.delete(e.pointerId); three.pinch = 0; };
    cv.addEventListener("pointerup", up); cv.addEventListener("pointercancel", up); cv.addEventListener("lostpointercapture", up);
    cv.addEventListener("wheel", (e) => { e.preventDefault(); three.zoom = clamp(three.zoom * Math.exp(-e.deltaY * 0.0015), 0.3, 6); draw3D(); }, { passive: false });
    cv.tabIndex = 0;
    cv.addEventListener("keydown", (e) => { const k = e.key; if (k === "ArrowLeft") three.yaw -= 0.1; else if (k === "ArrowRight") three.yaw += 0.1; else if (k === "ArrowUp") three.pitch = clamp(three.pitch + 0.1, -0.3, 1.5); else if (k === "ArrowDown") three.pitch = clamp(three.pitch - 0.1, -0.3, 1.5); else if (k === "+" ) three.zoom = clamp(three.zoom * 1.15, .3, 6); else if (k === "-") three.zoom = clamp(three.zoom / 1.15, .3, 6); else return; e.preventDefault(); draw3D(); });
    $("#btnResetView").addEventListener("click", () => { three.yaw = -0.75; three.pitch = 0.5; three.zoom = 1; draw3D(); });
    if (window.ResizeObserver) new ResizeObserver(() => draw3D()).observe(cv);
  }
  function pinchDist() { const a = Array.from(three.ptrs.values()); return a.length < 2 ? 0 : Math.hypot(a[0].x - a[1].x, a[0].y - a[1].y); }
  function draw3D() {
    const d = three.design, cv = three.canvas; if (!d || !cv) return;
    const cw = cv.clientWidth, ch = cv.clientHeight; if (!cw || !ch) return;
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    if (cv.width !== Math.round(cw * dpr) || cv.height !== Math.round(ch * dpr)) { cv.width = Math.round(cw * dpr); cv.height = Math.round(ch * dpr); }
    const ctx = three.ctx; ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = "#f7f8fb"; ctx.fillRect(0, 0, cw, ch);
    const g = d.geom, B = d.p.B;
    const bb = { x0: Math.min(0, -0.1), x1: g.xMax, y0: 0, y1: B, z0: -0.1, z1: g.H };
    const c = [(bb.x0 + bb.x1) / 2, (bb.y0 + bb.y1) / 2, (bb.z0 + bb.z1) / 2];
    const diag = Math.hypot(bb.x1 - bb.x0, bb.y1 - bb.y0, bb.z1 - bb.z0);
    const D = diag * 2.6, S = Math.min(cw, ch) * 0.62 / diag * three.zoom;
    const cy = Math.cos(three.yaw), sy = Math.sin(three.yaw), cp = Math.cos(three.pitch), sp = Math.sin(three.pitch);
    const rot = (p) => { const x = p[0] - c[0], y = p[1] - c[1], z = p[2] - c[2]; const x1 = x * cy - y * sy, y1 = x * sy + y * cy; return [x1, y1 * cp - z * sp, y1 * sp + z * cp]; };
    const rotN = (n) => { const x1 = n[0] * cy - n[1] * sy, y1 = n[0] * sy + n[1] * cy; return [x1, y1 * cp - n[2] * sp, y1 * sp + n[2] * cp]; };
    const proj = (p) => { const r = rot(p); const k = D / (D + r[1]); return [cw / 2 + r[0] * k * S, ch * 0.54 - r[2] * k * S, r[1]]; };
    const light = norm3([-0.4, -0.55, 0.75]);
    const view = {
      proj,
      visible: (n, center) => { const r = rot(center), nn = rotN(n); return dot3(nn, [-r[0], -D - r[1], -r[2]]) > 0; },
      shade: (n) => 0.45 + 0.55 * Math.max(0, dot3(rotN(n), light)),
    };
    // rejilla del suelo
    const step = diag > 24 ? 2 : 1, gx0 = Math.floor(bb.x0 - 1), gx1 = Math.ceil(bb.x1 + 1), gy0 = Math.floor(bb.y0 - 1), gy1 = Math.ceil(bb.y1 + 1);
    ctx.strokeStyle = "#d6dae5"; ctx.lineWidth = 1; ctx.beginPath();
    for (let x = gx0; x <= gx1; x += step) { const a = proj([x, gy0, 0]), b = proj([x, gy1, 0]); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
    for (let y = gy0; y <= gy1; y += step) { const a = proj([gx0, y, 0]), b = proj([gx1, y, 0]); ctx.moveTo(a[0], a[1]); ctx.lineTo(b[0], b[1]); }
    ctx.stroke();
    const list = drawList(d.meshes, view);
    ctx.lineJoin = "round"; ctx.lineWidth = 0.8; ctx.strokeStyle = "rgba(30,36,52,.55)";
    list.forEach((f) => { ctx.beginPath(); f.sp.forEach((q, i) => (i ? ctx.lineTo(q[0], q[1]) : ctx.moveTo(q[0], q[1]))); ctx.closePath(); ctx.fillStyle = f.col; ctx.fill(); ctx.stroke(); });
    ctx.fillStyle = "#5a6275"; ctx.font = "12px " + FONT; ctx.textAlign = "left";
    ctx.fillText("L " + fmt(d.mode === "stair" ? g.xEnd : g.xMax, 2) + " m · B " + fmt(B, 2) + " m · H " + fmt(g.H, 2) + " m · rejilla " + step + " m", 12, 20);
  }

  // ------------------------------------------------------------------ interfaz
  let current = null, lastSVG = { section: "", plan: "", iso: "" };
  const views = { section: svgSection, plan: svgPlan, iso: svgIso };

  function render() {
    const p = readParams();
    const d = p.mode === "stair" ? designStair(p) : designBleacher(p);
    current = d; three.design = d;
    const W = Math.max(300, ($(".views").clientWidth || 900) - 18);
    lastSVG.section = svgSection(d, W); lastSVG.plan = svgPlan(d, W); lastSVG.iso = svgIso(d, W);
    $("#vSection").innerHTML = lastSVG.section; $("#vPlan").innerHTML = lastSVG.plan; $("#vIso").innerHTML = lastSVG.iso;
    const gw = Math.max(280, Math.floor(W / 2) - 8);
    const twoCol = window.matchMedia("(min-width: 901px)").matches;
    $("#gSection").innerHTML = twoCol ? svgSection(d, gw) : lastSVG.section;
    $("#gPlan").innerHTML = twoCol ? svgPlan(d, gw) : lastSVG.plan;
    $("#gIso").innerHTML = twoCol ? svgIso(d, gw) : lastSVG.iso;
    renderStatus(d); renderKpis(d); renderTable(d); renderQty(d);
    $("#paramsSummary").textContent = (p.mode === "stair" ? "Escalera" : "Graderío") + " · H " + fmt(p.H, 2) + " · L " + fmt(p.L, 2) + " · B " + fmt(p.B, 2);
    buildPrintSheet(d);
    draw3D();
    saveParams();
  }
  const ICON = { ok: "#i-check", warn: "#i-warn", bad: "#i-x" };
  function renderStatus(d) {
    $("#status").innerHTML = d.checks.map((c, i) => '<span class="chip ' + c.lv + '"><svg width="16" height="16"><use href="' + ICON[c.lv] + '"/></svg>' + esc(c.text) + (c.action ? '<button data-act="' + i + '">' + esc(c.action.label) + "</button>" : "") + "</span>").join("");
  }
  function renderKpis(d) {
    $("#kpis").innerHTML = d.kpis.map((k) => '<div class="kpi ' + (k.lv || "") + '"><div class="k">' + esc(k.k) + '</div><div class="v">' + esc(k.v) + (k.u ? "<small>" + esc(k.u) + "</small>" : "") + "</div>" + (k.d ? '<div class="d">' + esc(k.d) + "</div>" : "") + "</div>").join("");
  }
  function tableHTML(d) {
    let h = "<table><thead><tr>" + d.tableHead.map((x) => "<th>" + esc(x) + "</th>").join("") + "</tr></thead><tbody>";
    let lastFlight = 0;
    d.table.forEach((r) => {
      if (d.mode === "stair" && r[1] !== lastFlight) { lastFlight = r[1]; if (d.f > 1) h += '<tr class="sep"><td colspan="' + d.tableHead.length + '">Tramo ' + lastFlight + " · " + d.flightsN[lastFlight - 1] + " contrahuellas</td></tr>"; }
      h += "<tr>" + r.map((cell) => (cell && typeof cell === "object") ? '<td class="c-' + cell.lv + '">' + esc(cell.v) + "</td>" : "<td>" + esc(cell) + "</td>").join("") + "</tr>";
    });
    return h + "</tbody></table>";
  }
  function renderTable(d) { $("#vTable").innerHTML = tableHTML(d); $("#vTable").previousElementSibling.textContent = d.mode === "stair" ? "Tabla de escalones" : "Tabla de gradas"; }
  function qtyHTML(d, cls) { return '<div class="' + (cls || "qty") + '">' + d.qty.map((q) => "<div><span>" + esc(q[0]) + "</span><b>" + esc(q[1]) + "</b></div>").join("") + '<div class="note">' + esc(d.qtyNote) + "</div></div>"; }
  function renderQty(d) { $("#vQty").innerHTML = qtyHTML(d); $("#gQty").innerHTML = qtyHTML(d); }

  // hoja de impresión
  function printSheetHTML(d) {
    const p = d.p, a3 = p.paper === "A3";
    const ws = a3 ? [900, 600, 600] : [640, 430, 430];
    const meta = d.mode === "stair"
      ? [["H / L / B", fmt(p.H, 2) + " / " + fmt(p.L, 2) + " / " + fmt(p.B, 2) + " m"], ["Contrahuellas", d.n + " × " + fmt(d.c, 3) + " m"], ["Huellas", d.treads + " × " + fmt(d.hReal, 3) + " m"], ["Blondel 2c+h", fmt(d.bl, 3) + " m"], ["Tramos", d.f + (d.f > 1 ? " · descanso " + fmt(d.Ld, 2) + " m" : "")], ["Losa (garganta)", fmt(p.t, 2) + " m"]]
      : [["H / L / B", fmt(p.H, 2) + " / " + fmt(p.L, 2) + " / " + fmt(p.B, 2) + " m"], ["Gradas", d.n + " × N " + fmt(d.N, 3) + " m"], ["Profundidad T", fmt(d.TReal, 3) + " m"], ["Acceso", d.k > 1 ? d.k + " esc./grada, " + fmt(p.Be, 2) + " m" : "no"], ["Pasillo", d.aisle ? fmt(d.aisle.W, 2) + " m " + (d.aisle.pos === "top" ? "superior" : "inferior") : "no"], ["Losa", fmt(p.t, 2) + " m"]];
    const notes = d.mode === "stair"
      ? ["Contrahuella c = H / n con n elegido para que c quede en el rango indicado y 2c + h se acerque a 0.62 m (Blondel 0.60–0.64).", "Huellas = n − 1 por tramo: la última contrahuella llega al descanso o al nivel superior. h = L útil / huellas, descontando descansos.", "Si n supera el máximo por tramo se intercala un descanso de longitud ≥ ancho B (mín. 1.00 m).", "Losa de garganta de espesor t medida perpendicular a la línea de huella. Cómputos sin solapes ni recargos.", "Verificar la normativa local (CTE DB-SUA, reglamentos municipales): alturas libres, pasamanos, barandillas y accesibilidad."]
      : ["Nº de gradas n elegido para que N = H / n y T = L útil / n queden lo más centrados posible en sus rangos.", "La escalera de acceso divide cada grada en k escalones iguales (c = N/k, h = T/k) dentro de una franja central.", d.vis ? "Visibilidad: C = D·(N+R)/(D+T) − R con ojo a " + fmt(p.eyeH, 2) + " m sobre la grada, punto focal a " + fmt(p.Df, 1) + " m del frente y " + fmt(p.hf, 2) + " m de altura. Objetivo C ≥ 0.06–0.09 m." : "Visibilidad (valor C) no evaluada: actívela en Parámetros › Visibilidad.", "Losa inclinada de espesor t bajo gradas macizas; el fondo de losa no requiere encofrado si apoya en relleno compactado.", "Verificar normativa local de espectáculos públicos: anchos de evacuación, barandillas, aforo y accesibilidad."];
    const sec = svgSection(d, ws[0]), plan = svgPlan(d, ws[1]), iso = svgIso(d, ws[2]);
    return '<div class="ps-head"><div><h1>' + esc(p.title) + " · " + (d.mode === "stair" ? "Escalera" : "Graderío") + '</h1><div class="sub">' + esc(d.summary) + '</div></div><div class="meta">' + meta.map((m) => "<span>" + esc(m[0]) + "</span><b>" + esc(m[1]) + "</b>").join("") + "<span>Fecha</span><b>" + today() + "</b><span>Hoja</span><b>" + p.paper + " apaisada · escala gráfica</b></div></div>" +
      '<div class="ps-grid"><div class="ps-box">' + sec + '</div><div class="ps-box">' + plan + "</div></div>" +
      '<div class="ps-page2"><div class="ps-box">' + iso + '</div><div><div class="ps-box"><h2>' + (d.mode === "stair" ? "Tabla de escalones" : "Tabla de gradas") + "</h2>" + tableHTML(d) + '</div><div class="ps-box"><h2>Cómputos</h2>' + qtyHTML(d, "ps-qty") + '</div><div class="ps-box ps-notes"><h2>Criterios</h2><ul>' + notes.map((n) => "<li>" + esc(n) + "</li>").join("") + "</ul></div></div></div>";
  }
  function buildPrintSheet(d) {
    $("#printSheet").innerHTML = printSheetHTML(d);
    $("#pageStyle").textContent = "@page { size: " + d.p.paper + " landscape; margin: 10mm; }";
  }
  const STANDALONE_CSS = "body{font:10.5pt/1.4 " + FONT + ";color:#111;background:#fff;margin:0;padding:10mm}" +
    ".ps-head{display:grid;grid-template-columns:1fr auto;gap:8mm;border:1.2pt solid #111;padding:3mm 4mm;margin-bottom:4mm}.ps-head h1{font-size:15pt;margin:0}.ps-head .sub{font-size:9.5pt;color:#333;margin-top:1mm}" +
    ".ps-head .meta{display:grid;grid-template-columns:auto auto;column-gap:6mm;row-gap:1mm;font-size:9pt;text-align:right}.ps-head .meta b{font-weight:600}" +
    ".ps-grid{display:grid;grid-template-columns:3fr 2fr;gap:4mm}.ps-box{border:.6pt solid #555;padding:2mm;break-inside:avoid}.ps-box h2{font-size:9pt;text-transform:uppercase;letter-spacing:.06em;color:#333;margin:0 0 1.5mm}" +
    ".ps-box svg{width:100%;height:auto;display:block}table{border-collapse:collapse;width:100%;font-size:8.5pt}th,td{padding:1mm 1.5mm;border-bottom:.4pt solid #999;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}th{font-size:8pt;text-transform:uppercase;color:#333}" +
    ".ps-qty div{display:flex;justify-content:space-between;padding:1mm 0;border-bottom:.4pt solid #bbb;font-size:9pt}.ps-qty .note{border:0;font-size:8pt;color:#444;display:block}" +
    ".ps-page2{break-before:page;display:grid;grid-template-columns:1fr 1fr;gap:4mm;margin-top:4mm}.ps-notes{font-size:8.5pt}.ps-notes li{margin-bottom:1mm}.c-ok{color:#15803d}.c-warn{color:#b45309}.c-bad{color:#c2410c}" +
    "@page{size:A3 landscape;margin:10mm}@media (max-width:900px){.ps-grid,.ps-page2,.ps-head{grid-template-columns:1fr}.ps-head .meta{text-align:left}}";
  function standaloneHTML(d) {
    return "<!doctype html><html lang=\"es\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>" + esc(d.p.title) + " · " + (d.mode === "stair" ? "Escalera" : "Graderío") + "</title><style>" + STANDALONE_CSS.replace("A3 landscape", d.p.paper + " landscape") + "</style></head><body>" + printSheetHTML(d) + "</body></html>";
  }

  // ------------------------------------------------------------------ exportación
  function svgToPng(svgText, scale) {
    return new Promise((resolve, reject) => {
      const img = new Image();
      const url = URL.createObjectURL(new Blob([svgText], { type: "image/svg+xml;charset=utf-8" }));
      img.onload = () => {
        const cv = document.createElement("canvas"); cv.width = Math.round(img.width * scale); cv.height = Math.round(img.height * scale);
        const g = cv.getContext("2d"); g.fillStyle = "#fff"; g.fillRect(0, 0, cv.width, cv.height); g.drawImage(img, 0, 0, cv.width, cv.height);
        URL.revokeObjectURL(url);
        cv.toBlob((b) => (b ? resolve(b) : reject(new Error("No se pudo generar el PNG"))), "image/png");
      };
      img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("No se pudo rasterizar el SVG")); };
      img.src = url;
    });
  }
  function slug() { return (current.mode === "stair" ? "escalera" : "graderio") + "_H" + fmt(current.p.H, 2) + "_L" + fmt(current.p.L, 2); }
  let toastT;
  function toast(msg) { const el = $("#toast"); el.textContent = msg; el.classList.add("show"); clearTimeout(toastT); toastT = setTimeout(() => el.classList.remove("show"), 3200); }
  function busy(btn, on) { btn.disabled = on; }
  function hasSDK() { return !!(window.PixAgent && typeof window.PixAgent.save === "function"); }

  async function saveAll() {
    const btn = $("#btnSave"); busy(btn, true);
    try {
      const base = slug(), folder = "graderio", saved = [];
      saved.push(await PixAgent.save(base + "_corte.svg", new Blob([lastSVG.section], { type: "image/svg+xml" }), { folder }));
      saved.push(await PixAgent.save(base + "_planta.svg", new Blob([lastSVG.plan], { type: "image/svg+xml" }), { folder }));
      saved.push(await PixAgent.save(base + "_isometrico.svg", new Blob([lastSVG.iso], { type: "image/svg+xml" }), { folder }));
      saved.push(await PixAgent.save(base + "_corte.png", await svgToPng(svgSection(current, 1400), 2), { folder }));
      saved.push(await PixAgent.save(base + "_plano.html", new Blob([standaloneHTML(current)], { type: "text/html" }), { folder }));
      saved.push(await PixAgent.save(base + "_parametros.json", current.p, { folder }));
      toast("Guardado en outputs/" + folder + ": " + saved.length + " archivos (" + base + "_*)");
      if (PixAgent.embedded) PixAgent.toast("Plano guardado: " + saved[saved.length - 2]);
    } catch (e) { toast("No se pudo guardar: " + (e && e.message ? e.message : e)); }
    busy(btn, false);
  }
  async function pinIt() {
    const btn = $("#btnPin"); busy(btn, true);
    try {
      const active = $(".tab.is-on").dataset.view;
      const svgText = active === "iso" ? svgIso(current, 1200) : active === "plan" ? svgPlan(current, 1200) : svgSection(current, 1400);
      const path = await PixAgent.save(slug() + "_" + (active === "iso" ? "isometrico" : active === "plan" ? "planta" : "corte") + "_pin.png", await svgToPng(svgText, 2), { folder: "graderio" });
      await PixAgent.pin([path]);
      toast("Fijado en PixPin: " + path);
    } catch (e) { toast("No se pudo fijar en PixPin: " + (e && e.message ? e.message : e)); }
    busy(btn, false);
  }
  async function reviewAI() {
    const btn = $("#btnAI"), panel = $("#aiPanel"), body = $("#aiBody");
    panel.hidden = false; panel.scrollIntoView({ block: "nearest", behavior: "smooth" }); body.innerHTML = '<div class="busy"><span class="spinner"></span>Consultando al modelo rápido…</div>'; busy(btn, true);
    const d = current, p = d.p;
    const resumen = d.mode === "stair"
      ? { tipo: "escalera", desnivel_H_m: p.H, distancia_L_m: p.L, ancho_B_m: p.B, contrahuellas: d.n, contrahuella_m: +fmt(d.c, 4), huellas: d.treads, huella_m: +fmt(d.hReal, 4), blondel_2c_h_m: +fmt(d.bl, 4), tramos: d.flightsN, descanso_m: d.f > 1 ? d.Ld : null, inclinacion_grados: +fmt(deg(d.angle), 1), losa_garganta_m: p.t }
      : { tipo: "graderio", desnivel_H_m: p.H, fondo_L_m: p.L, frente_B_m: p.B, gradas: d.n, peralte_m: +fmt(d.N, 4), profundidad_m: +fmt(d.TReal, 4), escalera_acceso: d.k > 1 ? { escalones_por_grada: d.k, contrahuella_m: +fmt(d.ce, 4), huella_m: +fmt(d.he, 4), ancho_m: p.Be } : null, pasillo: d.aisle, losa_m: p.t, visibilidad_C_min_m: d.vis ? +fmt(Math.min.apply(null, d.vis.map((v) => v.C)), 3) : null };
    resumen.comprobaciones = d.checks.map((c) => "[" + c.lv + "] " + c.text);
    try {
      const txt = await PixAgent.ai("Revisa este diseño geométrico y da como máximo 6 observaciones breves (viñetas) sobre seguridad de uso, confort y puntos a verificar en la normativa local (CTE DB-SUA en España; reglamentos municipales o NEC/RNE en Latinoamérica). Sé concreto; no repitas los datos.\n\n" + JSON.stringify(resumen),
        { quality: "fast", maxTokens: 700, system: "Eres un ingeniero civil revisor de proyectos. Respondes en español, de forma breve y práctica." });
      body.textContent = txt || "(sin respuesta)";
    } catch (e) { body.innerHTML = '<div class="err">No se pudo consultar la IA: ' + esc(e && e.message ? e.message : e) + "</div><div>El diseño y los planos no dependen de la IA: puedes seguir imprimiendo o guardando. Configura la clave de API en PixAgent para activar la revisión.</div>"; }
    busy(btn, false);
  }

  // ------------------------------------------------------------------ persistencia
  function saveParams() {
    try { const o = { mode }; NUM_IDS.forEach((id) => { o[id] = $("#" + id).value; }); ["stepsPerRow", "aislePos", "title", "paper"].forEach((id) => { o[id] = $("#" + id).value; }); o.accessStair = $("#accessStair").checked; o.aisle = $("#aisle").checked; o.vis = $("#visDetails").open; localStorage.setItem(STORE_KEY, JSON.stringify(o)); } catch (e) { /* sin almacenamiento */ }
  }
  function loadParams() {
    try {
      const o = JSON.parse(localStorage.getItem(STORE_KEY) || "null"); if (!o) return;
      NUM_IDS.forEach((id) => { if (o[id] != null) $("#" + id).value = o[id]; });
      ["stepsPerRow", "aislePos", "title", "paper"].forEach((id) => { if (o[id] != null) $("#" + id).value = o[id]; });
      if (o.accessStair != null) $("#accessStair").checked = !!o.accessStair;
      if (o.aisle != null) $("#aisle").checked = !!o.aisle;
      if (o.vis) $("#visDetails").open = true;
      if (o.mode === "bleacher" || o.mode === "stair") setMode(o.mode, true);
    } catch (e) { /* ignorar */ }
  }

  // ------------------------------------------------------------------ modo, pestañas y eventos
  function setMode(m, silent) {
    mode = m;
    $$(".seg-btn").forEach((b) => { const on = b.dataset.mode === m; b.classList.toggle("is-on", on); b.setAttribute("aria-selected", on ? "true" : "false"); });
    $$(".mode-stair").forEach((el) => { el.hidden = m !== "stair"; });
    $$(".mode-bleacher").forEach((el) => { el.hidden = m !== "bleacher"; });
    $("#lblL").textContent = m === "stair" ? "Distancia horizontal L" : "Fondo horizontal L";
    $("#lblB").textContent = m === "stair" ? "Ancho B" : "Longitud del frente B";
    $("#hintGeneral").textContent = m === "stair"
      ? "H es el desnivel a salvar y L la distancia horizontal disponible entre el arranque y la llegada. Medidas en metros."
      : "H es el desnivel entre el suelo y la última grada; L el fondo horizontal disponible (incluido el pasillo) y B la longitud del graderío a lo largo de las filas. Medidas en metros.";
    if (!silent) render();
  }
  function showView(v) {
    $$(".tab").forEach((b) => b.classList.toggle("is-on", b.dataset.view === v));
    $$(".view").forEach((el) => el.classList.toggle("is-on", el.dataset.view === v));
    if (v === "three") requestAnimationFrame(draw3D);
  }

  function init() {
    loadParams();
    setup3D();
    const rerender = debounce(render, 120);
    $$("input, select", $("#params")).forEach((el) => { el.addEventListener("input", rerender); el.addEventListener("change", rerender); });
    $("#visDetails").addEventListener("toggle", rerender);
    $("#accessStair").addEventListener("change", () => { $("#accessFields").hidden = !$("#accessStair").checked; });
    $("#aisle").addEventListener("change", () => { $("#aisleFields").hidden = !$("#aisle").checked; });
    $("#accessFields").hidden = !$("#accessStair").checked; $("#aisleFields").hidden = !$("#aisle").checked;
    $$(".seg-btn").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
    $$(".tab").forEach((b) => b.addEventListener("click", () => showView(b.dataset.view)));
    $("#status").addEventListener("click", (e) => { const b = e.target.closest("button[data-act]"); if (!b) return; const act = current.checks[+b.dataset.act].action; if (act) { $("#L").value = fmt(act.value, 2); render(); } });
    $("#paramsToggle").addEventListener("click", () => { const open = $("#paramsToggle").getAttribute("aria-expanded") === "true"; $("#paramsToggle").setAttribute("aria-expanded", open ? "false" : "true"); $("#paramsBody").hidden = open; });
    $("#btnPrint").addEventListener("click", () => { buildPrintSheet(current); window.print(); });
    window.addEventListener("beforeprint", () => buildPrintSheet(current));
    $("#btnSave").addEventListener("click", saveAll);
    $("#btnPin").addEventListener("click", pinIt);
    $("#btnAI").addEventListener("click", reviewAI);
    $("#aiClose").addEventListener("click", () => { $("#aiPanel").hidden = true; });
    window.addEventListener("resize", debounce(render, 200));
    // SDK / servidor: ocultar acciones que lo requieren si no está disponible
    const hideSdk = () => $$(".needs-sdk").forEach((b) => { b.hidden = true; });
    if (!hasSDK()) hideSdk();
    else fetch("/api/apps", { method: "GET" }).then((r) => { if (!r.ok) hideSdk(); }).catch(hideSdk);
    render();
  }
  window.__graderio = { design: () => current, designStair, designBleacher, render, buildPrint: () => buildPrintSheet(current) };
  document.addEventListener("DOMContentLoaded", init);
})();
