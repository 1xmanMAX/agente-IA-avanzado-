"""Herramienta del agente para delegar trabajo masivo en modelos pequeños locales (gratis)."""
from __future__ import annotations

import json

from .base import ToolContext, ToolError, ToolResult, tool

_SVC = {}


def _svc(ctx: ToolContext):
    from ..local.service import LocalAI
    if "svc" not in _SVC:
        _SVC["svc"] = LocalAI(ctx.settings)
    return _SVC["svc"]


@tool("local_ai",
      """IA LOCAL GRATUITA (modelos pequeños en el equipo del usuario vía Ollama/llama.cpp/LM Studio).
      Úsala para TRABAJO MASIVO o repetitivo que no necesita tu razonamiento: describir decenas de fotos,
      OCR de muchas imágenes o páginas, clasificar/etiquetar, analizar un vídeo fotograma a fotograma.
      Después revisa y razona tú sobre los resultados (los modelos pequeños pueden equivocarse en detalles).
      Acciones: status (motores y modelos disponibles; llámala primero), caption | ocr | ask (sobre
      'images'; varias imágenes se procesan una a una y se guarda un JSON con los resultados), text,
      video (source = ruta del vídeo o URL; every = segundos entre fotogramas; scene = 0.3 para cortes
      de escena; max_frames; transcribe; devuelve la línea de tiempo y la guarda en outputs/video/).""",
      {"properties": {
          "action": {"type": "string", "enum": ["status", "caption", "ocr", "ask", "text", "video"]},
          "images": {"type": "array", "items": {"type": "string"}},
          "prompt": {"type": "string"}, "model": {"type": "string"},
          "source": {"type": "string"}, "every": {"type": "number"}, "scene": {"type": "number"},
          "max_frames": {"type": "integer"}, "transcribe": {"type": "boolean"},
          "output": {"type": "string", "description": "JSON de resultados (por defecto outputs/local_ai/<acción>.json)"}},
       "required": ["action"]})
def local_ai(ctx: ToolContext, action: str, images: list | None = None, prompt: str = "", model: str | None = None,
             source: str | None = None, every: float = 5, scene: float | None = None, max_frames: int = 60,
             transcribe: bool = False, output: str | None = None) -> ToolResult:
    svc = _svc(ctx)
    if action == "status":
        st = svc.status(refresh=True)
        on = [e for e in st["engines"] if e["online"]]
        if not on:
            return ToolResult("No hay motores locales activos. Sugiere al usuario instalar Ollama (ollama.com) y "
                              "descargar p. ej. 'qwen3.5:4b' (visión/OCR) desde la mini app 'IA local'.")
        inst = ", ".join(f"{m['id']} ({'/'.join(m['caps'])})" for m in st["installed"]) or "ninguno"
        return ToolResult(f"Motores: {', '.join(e['name'] for e in on)}. Modelos: {inst}. "
                          f"Asignados: {st['assigned']}. Vídeo: {st['video']}. Audio: {st['asr']}")
    try:
        if action == "video":
            if not source:
                raise ToolError("video necesita 'source'.")
            job = svc.start_video({"source": source, "every": every, "scene": scene, "max_frames": max_frames,
                                   "transcribe": transcribe, "prompt": prompt, "model": model}, ctx.emit)
            job.thread.join()
            if job.status == "error":
                raise ToolError(job.error)
            lines = [f"[{it['time']}] {it.get('text') or it.get('error')}" for it in job.items if not it.get("same")]
            out_rel = ctx.rel(ctx.ws / "outputs" / "video" / job.id)
            return ToolResult(f"Vídeo analizado ({len(job.items)} fotogramas) → {out_rel}/analisis.md\n" + "\n".join(lines)[:15000]
                              + (f"\n\nResumen local: {job.summary}" if job.summary else ""),
                              files=[ctx.ws / "outputs" / "video" / job.id / "analisis.md"])
        if action == "text":
            r = svc.run("text", prompt, [], model)
            return ToolResult(r["text"] + f"\n\n({r['model']}, {r['usage'].get('seconds')} s)")
        paths = [ctx.resolve(p, must_exist=True) for p in images or []]
        if not paths:
            raise ToolError("Indica 'images'.")
        results = svc.batch(action, paths, prompt, model,
                            on_item=lambda i, r: ctx.emit({"type": "status", "text": f"IA local: {i + 1}/{len(paths)}"}))
        for r in results:
            r["path"] = ctx.rel(__import__("pathlib").Path(r["path"]))
        out = ctx.resolve(output or f"outputs/local_ai/{action}.json")
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(results, ensure_ascii=False, indent=1), "utf-8")
        body = "\n\n".join(f"### {r['path']}\n{r.get('text') or 'ERROR: ' + r.get('error', '')}" for r in results)
        return ToolResult(f"{len(results)} imagen(es) procesadas con IA local → {ctx.rel(out)}\n\n{body}"[:20000], files=[out])
    except ToolError:
        raise
    except Exception as e:  # noqa: BLE001
        raise ToolError(str(e))
