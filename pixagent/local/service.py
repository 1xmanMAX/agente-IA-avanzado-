"""Servicio de IA local: elige motor y modelo por tarea y ofrece tareas listas para usar.

Tareas: ask (pregunta con o sin imágenes), caption (describir), ocr (leer texto), text (solo texto),
transcribe (audio → texto con marcas de tiempo) y video (análisis fotograma a fotograma, con
transcripción opcional y resumen final).

Idea: los modelos pequeños (0.5–8 B) son rápidos y gratuitos en local; se usan como HERRAMIENTAS
para trabajo masivo (describir 300 fotos, leer 50 planos, narrar un vídeo) y Claude razona encima.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import catalog
from .engines import Engine, discover

# Prompts cortos y "anti-invención": los modelos pequeños rellenan lo que el prompt sugiere
# (si mencionas "personas", las inventan), así que se pide SOLO lo visible.
PROMPTS = {
    "caption": "Describe en 2-3 frases, en español, SOLO lo que se ve en la imagen. No inventes nada "
               "que no aparezca. Si hay texto visible, cítalo.",
    "ocr": "Transcribe TODO el texto visible en la imagen, respetando el orden de lectura, saltos de línea "
           "y tablas (en Markdown). No añadas comentarios ni traduzcas. Si no hay texto, responde: (sin texto).",
    "frame": "Describe en una o dos frases, en español, SOLO lo que se ve en esta imagen. No inventes "
             "personas, objetos ni acciones que no aparezcan. Si hay texto en pantalla, cítalo.{prev}",
}


class LocalAI:
    def __init__(self, settings):
        self.s = settings
        self._engines: list[Engine] = []
        self._at = 0.0
        self.lock = threading.Lock()
        self.jobs: dict[str, "Job"] = {}

    # ---------------------------------------------------------------- descubrimiento
    def engines(self, refresh: bool = False) -> list[Engine]:
        with self.lock:
            if refresh or time.time() - self._at > 20:
                self._engines = discover(getattr(self.s, "local_engines", []) or [])
                for e in self._engines:
                    if e.online:
                        try:
                            e.models()
                        except Exception as ex:  # noqa: BLE001
                            e.error = str(ex)[:120]
                self._at = time.time()
            return self._engines

    def status(self, refresh: bool = False) -> dict:
        engines = self.engines(refresh)
        installed = [{"id": m.id, "engine": e.name, "size_gb": m.size_gb,
                      "caps": catalog.capabilities(m.id)} for e in engines if e.online for m in e._models]
        return {
            "engines": [{"name": e.name, "kind": e.kind, "url": e.base_url, "online": e.online,
                         "version": e.version, "models": len(e._models)} for e in engines],
            "installed": installed,
            "assigned": {task: self.pick(task, quiet=True) for task in ("vision", "ocr", "text")},
            "catalog": catalog.CATALOG,
            "profiles": catalog.PROFILES,
            "asr": asr_available(),
            "video": {"ffmpeg": bool(ffmpeg_exe()), "youtube": ytdlp_available()},
        }

    def pick(self, task: str, model: str | None = None, quiet: bool = False):
        """Devuelve (motor, modelo) para la tarea: el elegido por el usuario, el asignado en ajustes o
        el mejor instalado según el catálogo."""
        engines = [e for e in self.engines() if e.online]
        if not engines:
            if quiet:
                return None
            raise RuntimeError("No hay ningún motor de IA local en marcha. Instala Ollama (ollama.com) o "
                               "arranca llama.cpp / LM Studio, y descarga un modelo.")
        want = model or (getattr(self.s, "local_models", {}) or {}).get(task)
        for e in engines:
            for m in e._models:
                if want and (m.id == want or m.id.split(":")[0] == want.split(":")[0] and ":" not in want):
                    return (e.name, m.id) if quiet else (e, m.id)
        ranked = catalog.rank_installed([(e, m.id) for e in engines for m in e._models], task)
        if ranked:
            e, mid = ranked[0]
            return (e.name, mid) if quiet else (e, mid)
        if quiet:
            return None
        need = {"vision": "un modelo de visión (p. ej. " + catalog.suggest("vision") + ")",
                "ocr": "un modelo de visión/OCR (p. ej. " + catalog.suggest("ocr") + ")",
                "text": "un modelo de texto (p. ej. " + catalog.suggest("text") + ")"}.get(task, "un modelo")
        raise RuntimeError(f"Falta {need}. Descárgalo desde Ajustes → IA local o con: ollama pull <modelo>.")

    # ---------------------------------------------------------------- tareas
    def run(self, task: str, prompt: str = "", images: list[Path] | None = None, model: str | None = None,
            json_mode: bool = False, max_tokens: int | None = None, system: str = "") -> dict:
        cap = "text" if task == "text" else ("ocr" if task == "ocr" else "vision")
        if cap != "text" and not images:
            raise ValueError("Esta tarea necesita al menos una imagen.")
        eng, mid = self.pick(cap, model)
        p = prompt or PROMPTS.get(task, "")
        fam = catalog.family_of(mid) or ""
        if task == "ocr":
            p = catalog.OCR_PROMPTS.get(fam) or (PROMPTS["ocr"] + ("\n" + prompt if prompt else ""))
        side = 1280 if task == "ocr" else 768  # el OCR necesita más resolución
        text, usage = eng.chat(mid, p, images, system=system, json_mode=json_mode, image_side=side,
                               max_tokens=max_tokens or (2048 if task == "ocr" else 400),
                               think=False if fam in catalog.THINKING_FAMILIES and task != "text" else None)
        res = {"ok": True, "text": text, "model": mid, "engine": eng.name, "usage": usage}
        if json_mode:
            res["data"] = parse_json(text)
        return res

    def batch(self, task: str, images: list[Path], prompt: str = "", model: str | None = None,
              on_item: Callable[[int, dict], None] | None = None) -> list[dict]:
        out = []
        for i, img in enumerate(images):
            try:
                r = self.run(task, prompt, [img], model)
            except Exception as e:  # noqa: BLE001
                r = {"ok": False, "error": str(e)}
            r["path"] = str(img)
            out.append(r)
            if on_item:
                on_item(i, r)
        return out

    # ---------------------------------------------------------------- trabajos largos (vídeo)
    def start_video(self, spec: dict, emit: Callable[[dict], None] | None = None) -> "Job":
        job = Job(id=uuid.uuid4().hex[:10], kind="video", spec=spec)
        self.jobs[job.id] = job
        th = threading.Thread(target=self._video_worker, args=(job, emit or (lambda e: None)), daemon=True)
        job.thread = th
        th.start()
        return job

    def _video_worker(self, job: "Job", emit) -> None:
        from .video import analyze_video
        try:
            analyze_video(self, job, emit)
            job.status = "cancelled" if job.cancel else "done"
        except Exception as e:  # noqa: BLE001
            job.status, job.error = "error", str(e)[:500]
        job.save()
        emit({"type": "local_done", "job": job.id, "status": job.status, "error": job.error})


@dataclass
class Job:
    id: str
    kind: str
    spec: dict
    status: str = "running"
    stage: str = "preparando"
    progress: float = 0.0
    items: list[dict] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    summary: str = ""
    error: str = ""
    cancel: bool = False
    out_dir: str = ""
    started: float = field(default_factory=time.time)
    thread: threading.Thread | None = None

    def public(self, after: int = 0) -> dict:
        return {"id": self.id, "kind": self.kind, "status": self.status, "stage": self.stage,
                "progress": round(self.progress, 3), "items": self.items[after:], "total_items": len(self.items),
                "transcript": self.transcript if after == 0 or self.status != "running" else [],
                "summary": self.summary, "error": self.error, "out_dir": self.out_dir,
                "elapsed": round(time.time() - self.started, 1), "spec": self.spec}

    def save(self) -> None:
        if self.out_dir:
            Path(self.out_dir, "analisis.json").write_text(json.dumps(
                {k: v for k, v in self.public().items()}, ensure_ascii=False, indent=1), "utf-8")


# ---------------------------------------------------------------- utilidades
def parse_json(text: str):
    m = re.search(r"[\[{].*[\]}]", text, re.S)
    try:
        return json.loads(m.group(0) if m else text)
    except json.JSONDecodeError:
        return None


def ffmpeg_exe() -> str | None:
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:  # binario portátil incluido con imageio-ffmpeg (Windows/macOS/Linux)
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:  # noqa: BLE001
        return None


def ytdlp_available() -> bool:
    import importlib.util
    return importlib.util.find_spec("yt_dlp") is not None


def asr_available() -> dict:
    import importlib.util
    return {"faster_whisper": importlib.util.find_spec("faster_whisper") is not None}


def run_ffmpeg(args: list[str], timeout: float = 3600) -> subprocess.CompletedProcess:
    exe = ffmpeg_exe()
    if not exe:
        raise RuntimeError("Falta ffmpeg: instala 'pip install imageio-ffmpeg' o ffmpeg del sistema.")
    return subprocess.run([exe, "-hide_banner", *args], capture_output=True, text=True, timeout=timeout,
                          encoding="utf-8", errors="replace")
