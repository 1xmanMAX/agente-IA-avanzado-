/* PixAgent SDK para mini apps (sin dependencias, ~3 KB).
   Incluir en una mini app:  <script src="/static/pixagent-sdk.js"></script>
   Todas las funciones devuelven promesas. La IA es OPCIONAL y barata (modelo rápido por defecto):
   las mini apps hacen el cálculo/maquetado en el navegador y solo llaman a la IA cuando aporta. */
(function () {
  "use strict";
  const enc = (p) => String(p).split("/").map(encodeURIComponent).join("/");
  async function j(url, opts) {
    const r = await fetch(url, opts);
    const t = await r.text();
    let d; try { d = JSON.parse(t); } catch (e) { d = { error: t }; }
    if (!r.ok || d.ok === false) throw new Error(d.error || ("HTTP " + r.status));
    return d;
  }
  const post = (url, body) => j(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

  async function toRef(x) {
    // Acepta ruta del workspace (string), File/Blob o dataURL. Los binarios se suben primero.
    if (typeof x === "string" && !x.startsWith("data:")) return x;
    if (typeof x === "string") x = await (await fetch(x)).blob();
    const [p] = await PixAgent.upload([x]);
    return p;
  }

  const PixAgent = {
    version: "1",
    /** true si la mini app está abierta dentro de la interfaz de PixAgent */
    embedded: window.parent !== window,

    /** URL para mostrar un archivo del workspace / miniatura WebP ligera */
    fileUrl: (path) => "/files/" + enc(path),
    thumbUrl: (path, w) => "/thumb/" + enc(path) + "?w=" + (w || 480),

    /** Sube archivos (File/Blob) al workspace. Devuelve rutas relativas, p. ej. "uploads/2026-11-07/foto.jpg" */
    async upload(files) {
      const fd = new FormData();
      Array.from(files).forEach((f, i) => fd.append("files", f, f.name || ("archivo_" + Date.now() + "_" + i + (f.type === "image/png" ? ".png" : f.type === "application/pdf" ? ".pdf" : ".jpg"))));
      return (await j("/api/upload", { method: "POST", body: fd })).files;
    },

    /** Guarda un resultado (Blob, string, objeto) en el workspace: outputs/<carpeta>/<nombre>. Devuelve la ruta. */
    async save(name, data, opts) {
      opts = opts || {};
      let blob = data;
      if (!(data instanceof Blob)) blob = new Blob([typeof data === "string" ? data : JSON.stringify(data, null, 2)],
        { type: typeof data === "string" ? "text/plain" : "application/json" });
      const fd = new FormData();
      fd.append("file", blob, name);
      fd.append("folder", opts.folder || "");
      return (await j("/api/files/save", { method: "POST", body: fd })).path;
    },

    /** Lista archivos de una carpeta del workspace (p. ej. "outputs/graderio") */
    async list(folder) { return (await j("/api/files/list?folder=" + encodeURIComponent(folder || ""))).files; },

    /** Fija archivos del workspace en PixPin (en el PC anfitrión) */
    async pin(paths) { return post("/api/pixpin/pin", { files: [].concat(paths) }); },

    /**
     * IA rápida y barata. opts: { images: [ruta|File|Blob|dataURL], system, json: bool|schemaDesc,
     *   maxTokens (def 1024), quality: "fast" (def, modelo económico) | "best" (modelo principal) }
     * Devuelve texto, o un objeto si json está activo.
     */
    async ai(prompt, opts) {
      opts = opts || {};
      const images = await Promise.all((opts.images || []).map(toRef));
      const d = await post("/api/ai/quick", { prompt, images, system: opts.system || "", json: opts.json || false,
        max_tokens: opts.maxTokens || 1024, quality: opts.quality || "fast" });
      return opts.json ? d.data : d.text;
    },

    /** Genera un panel fotográfico PDF en el servidor. spec: ver docs/MINIAPPS_SDK.md */
    async photoPanel(spec) { return post("/api/photo-panel", spec); },

    /** Envía una petición al agente principal (chat). Si la app está incrustada, la abre en el chat. */
    sendToAgent(text, attachments) {
      if (PixAgent.embedded) window.parent.postMessage({ type: "pixagent:compose", text, attachments: attachments || [] }, location.origin);
      else location.href = "/?compose=" + encodeURIComponent(text);
    },

    /** IA LOCAL (gratis, en el equipo anfitrión: Ollama / llama.cpp / LM Studio). Modelos pequeños
        rápidos para trabajo masivo: describir, leer texto (OCR), preguntar sobre imágenes, vídeo. */
    local: {
      /** Estado: motores, modelos instalados, modelo asignado por tarea, catálogo recomendado */
      status: (refresh) => j("/api/local/status" + (refresh ? "?refresh=1" : "")),
      /** task: "ask" | "caption" | "ocr" | "text". opts: {prompt, images:[ruta|File|Blob|dataURL], model, json} */
      async run(task, opts) {
        opts = opts || {};
        const images = await Promise.all((opts.images || []).map(toRef));
        return post("/api/local/run", { task, prompt: opts.prompt || "", images, model: opts.model,
          json: !!opts.json, max_tokens: opts.maxTokens });
      },
      ask: (prompt, images, opts) => PixAgent.local.run("ask", Object.assign({ prompt, images }, opts)).then((r) => r.text),
      caption: (image, opts) => PixAgent.local.run("caption", Object.assign({ images: [image] }, opts)).then((r) => r.text),
      ocr: (image, opts) => PixAgent.local.run("ocr", Object.assign({ images: [image] }, opts)).then((r) => r.text),
      /** Fotograma en directo (canvas/vídeo/dataURL) sin guardarlo: ideal para cámara o pantalla */
      async frame(source, prompt, opts) {
        let url = source;
        if (source && source.getContext) url = source.toDataURL("image/jpeg", 0.8);
        else if (source && source.videoWidth) {
          const c = document.createElement("canvas"); const k = Math.min(1, 640 / source.videoWidth);
          c.width = Math.round(source.videoWidth * k); c.height = Math.round(source.videoHeight * k);
          c.getContext("2d").drawImage(source, 0, 0, c.width, c.height); url = c.toDataURL("image/jpeg", 0.8);
        }
        return post("/api/local/run", Object.assign({ task: "ask", prompt: prompt || "", image_b64: url }, opts || {}));
      },
      /** Vídeo fotograma a fotograma. spec: {source: ruta|URL, every: s, scene: 0.3|null, max_frames,
          prompt, transcribe, summary, model}. onUpdate(job) recibe los resultados en cuanto salen. */
      async video(spec, onUpdate) {
        const { job } = await post("/api/local/video", spec);
        let after = 0, items = [];
        for (;;) {
          const d = await j("/api/local/jobs/" + job + "?after=" + after);
          items = items.concat(d.items); after = items.length; d.items = items;
          if (onUpdate) onUpdate(d);
          if (d.status !== "running") return d;
          await new Promise((r) => setTimeout(r, 1200));
        }
      },
      cancel: (jobId) => post("/api/local/jobs/" + jobId + "/cancel", {}),
      pull: (model) => post("/api/local/pull", { model }),
    },

    /** Muestra un aviso en la interfaz anfitriona (o alert si va suelta) */
    toast(msg) {
      if (PixAgent.embedded) window.parent.postMessage({ type: "pixagent:toast", text: msg }, location.origin);
      else console.log("[PixAgent]", msg);
    },
  };
  window.PixAgent = PixAgent;
})();
