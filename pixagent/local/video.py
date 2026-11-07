"""Análisis de vídeo fotograma a fotograma con un modelo de visión local.

Fuente: archivo del workspace, URL de vídeo (YouTube y otros, con yt-dlp si está instalado) o
captura en directo desde el navegador (la mini app envía fotogramas a /api/local/run).

Pasos:
1. Obtener el vídeo (descarga a ≤480p: suficiente para describir y mucho más rápido).
2. Elegir fotogramas: cada N segundos o por CAMBIO DE ESCENA (filtro 'scene' de ffmpeg), con tope.
3. Describir cada fotograma con el modelo local, pasándole la descripción anterior para que narre
   la continuidad y no repita lo que no cambia ("streaming": los resultados salen en cuanto se
   generan).
4. (Opcional) Transcribir el audio con Whisper local y alinear por tiempo.
5. (Opcional) Resumen final con el modelo de texto local (o lo hace Claude desde el agente).
"""
from __future__ import annotations

import re
from pathlib import Path

from .service import PROMPTS, run_ffmpeg, ytdlp_available


def fetch_source(ws: Path, source: str, out_dir: Path, want_audio: bool) -> Path:
    if re.match(r"^https?://", source):
        if not ytdlp_available():
            raise RuntimeError("Para analizar vídeos por URL instala yt-dlp (pip install yt-dlp). "
                               "Respeta los términos del sitio y los derechos de autor.")
        import yt_dlp
        from .service import ffmpeg_exe
        fmt = "b[height<=480]/bv*[height<=480]+ba/b" if want_audio else "bv*[height<=480]/b[height<=480]/b"
        opts = {"outtmpl": str(out_dir / "video.%(ext)s"), "format": fmt, "quiet": True, "noplaylist": True,
                "no_warnings": True, "ffmpeg_location": ffmpeg_exe()}
        with yt_dlp.YoutubeDL(opts) as y:
            info = y.extract_info(source, download=True)
            p = Path(y.prepare_filename(info))
        if not p.exists():
            cands = sorted(out_dir.glob("video.*"))
            if not cands:
                raise RuntimeError("No se pudo descargar el vídeo.")
            p = cands[0]
        return p
    p = (ws / source).resolve()
    if ws not in p.parents or not p.exists():
        raise RuntimeError(f"No existe el vídeo: {source}")
    return p


def duration(video: Path) -> float:
    r = run_ffmpeg(["-i", str(video)], timeout=60)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def extract_frames(video: Path, out_dir: Path, every: float, scene: float | None, max_frames: int,
                   width: int = 640) -> list[tuple[float, Path]]:
    fdir = out_dir / "frames"
    fdir.mkdir(parents=True, exist_ok=True)
    dur = duration(video)
    if scene:
        # un fotograma por cambio de escena (y como mínimo uno cada 'every' segundos)
        vf = (f"select='gt(scene\\,{scene})+isnan(prev_selected_t)+gte(t-prev_selected_t\\,{max(every, 1)})',"
              f"showinfo,scale={width}:-2")
        r = run_ffmpeg(["-i", str(video), "-vf", vf, "-vsync", "vfr", "-q:v", "4", "-frames:v", str(max_frames),
                        str(fdir / "f_%05d.jpg")])
        times = [float(t) for t in re.findall(r"pts_time:([\d.]+)", r.stderr)]
        files = sorted(fdir.glob("f_*.jpg"))
        return list(zip(times, files))[:max_frames]
    if dur and dur / every > max_frames:
        every = dur / max_frames
    fps = 1.0 / max(every, 0.2)
    run_ffmpeg(["-i", str(video), "-vf", f"fps={fps:.5f},scale={width}:-2", "-q:v", "4",
                "-frames:v", str(max_frames), str(fdir / "f_%05d.jpg")])
    files = sorted(fdir.glob("f_*.jpg"))
    return [(round(i * every, 2), f) for i, f in enumerate(files)]


def transcribe(audio_src: Path, out_dir: Path, model_size: str = "small", language: str | None = "es") -> list[dict]:
    """Whisper local (faster-whisper, CPU int8). Devuelve segmentos [{start, end, text}]."""
    from faster_whisper import WhisperModel
    wav = out_dir / "audio.wav"
    run_ffmpeg(["-y", "-i", str(audio_src), "-vn", "-ac", "1", "-ar", "16000", str(wav)])
    model = WhisperModel(model_size, device="auto", compute_type="int8")
    segs, _ = model.transcribe(str(wav), language=language, vad_filter=True)
    return [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()} for s in segs]


def signature(f: Path):
    """Huella de 32x32 en gris para detectar fotogramas casi idénticos sin IA."""
    from PIL import Image
    with Image.open(f) as im:
        return list(im.convert("L").resize((32, 32)).getdata())


def image_diff(a, b) -> float:
    return sum(abs(x - y) for x, y in zip(a, b)) / len(a)


def fmt_t(t: float) -> str:
    t = int(t)
    return f"{t // 3600:02d}:{t % 3600 // 60:02d}:{t % 60:02d}" if t >= 3600 else f"{t // 60:02d}:{t % 60:02d}"


def analyze_video(svc, job, emit) -> None:
    ws = svc.s.ws
    spec = job.spec
    out_dir = ws / "outputs" / "video" / job.id
    out_dir.mkdir(parents=True, exist_ok=True)
    job.out_dir = str(out_dir)
    ev = lambda **kw: emit({"type": "local_progress", "job": job.id, **kw})  # noqa: E731

    job.stage = "obteniendo vídeo"
    ev(stage=job.stage)
    video = fetch_source(ws, spec["source"], out_dir, bool(spec.get("transcribe")))
    job.stage = "extrayendo fotogramas"
    ev(stage=job.stage)
    frames = extract_frames(video, out_dir, float(spec.get("every", 5)), spec.get("scene"),
                            int(spec.get("max_frames", 120)))
    if not frames:
        raise RuntimeError("No se pudieron extraer fotogramas (¿vídeo válido?).")

    if spec.get("transcribe"):
        job.stage = "transcribiendo audio"
        ev(stage=job.stage)
        try:
            job.transcript = transcribe(video, out_dir, spec.get("whisper", "small"), spec.get("language", "es"))
        except ImportError:
            job.transcript = [{"start": 0, "end": 0, "text": "(Instala faster-whisper para transcribir: pip install faster-whisper)"}]
        except Exception as e:  # noqa: BLE001
            job.transcript = [{"start": 0, "end": 0, "text": f"(No se pudo transcribir: {e})"}]

    job.stage = "describiendo fotogramas"
    eng, model = svc.pick("vision", spec.get("model"))
    custom = (spec.get("prompt") or "").strip()
    prev_sig, prev_text = None, ""
    for i, (t, f) in enumerate(frames):
        if job.cancel:
            break
        sig = signature(f)
        if prev_sig is not None and image_diff(sig, prev_sig) < float(spec.get("same_threshold", 4.0)):
            # Casi idéntico al anterior: no se gasta una inferencia (y no se fuerza al modelo a "comparar",
            # algo que los modelos pequeños hacen mal)
            item = {"t": t, "time": fmt_t(t), "frame": f.relative_to(ws).as_posix(), "text": "Sin cambios.",
                    "same": True, "seconds": 0}
        else:
            prompt = custom or PROMPTS["frame"].format(prev="")
            try:
                from .catalog import THINKING_FAMILIES, family_of
                text, usage = eng.chat(model, prompt, [f], max_tokens=int(spec.get("max_tokens", 120)),
                                       image_side=int(spec.get("side", 640)),
                                       think=False if (family_of(model) or "") in THINKING_FAMILIES else None)
                item = {"t": t, "time": fmt_t(t), "frame": f.relative_to(ws).as_posix(),
                        "text": text.lstrip(": ").strip(), "seconds": usage.get("seconds")}
                prev_text = text
            except Exception as e:  # noqa: BLE001
                item = {"t": t, "time": fmt_t(t), "frame": f.relative_to(ws).as_posix(), "text": "", "error": str(e)[:200]}
        prev_sig = sig
        job.items.append(item)
        job.progress = (i + 1) / len(frames)
        ev(stage=job.stage, item=item, progress=job.progress, index=i, total=len(frames))
        if i % 5 == 4:
            job.save()

    if spec.get("summary", True) and job.items and not job.cancel:
        job.stage = "resumiendo"
        ev(stage=job.stage)
        try:
            timeline = "\n".join(f"[{it['time']}] {it['text']}" for it in job.items if it.get("text"))[:12000]
            speech = "\n".join(f"[{fmt_t(s['start'])}] {s['text']}" for s in job.transcript)[:6000]
            teng, tmodel = svc.pick("text")
            dur = duration(video)
            job.summary, _ = teng.chat(tmodel, f"El vídeo dura {fmt_t(dur)}. Resume en español, en 3-8 viñetas, lo que ocurre, "
                                       "usando SOLO las marcas de tiempo de la lista (no inventes otras ni añadas "
                                       "hechos que no estén). Agrupa los tramos sin cambios. Descripción por fotogramas" +
                                       (" y la transcripción" if speech else "") + ":\n\n" + timeline +
                                       (f"\n\nTRANSCRIPCIÓN:\n{speech}" if speech else ""), max_tokens=700)
        except Exception as e:  # noqa: BLE001
            job.summary = f"(Sin resumen: {e})"
    write_markdown(job, out_dir)


def write_markdown(job, out_dir: Path) -> None:
    lines = [f"# Análisis de vídeo\n\nFuente: {job.spec.get('source')}\n"]
    if job.summary:
        lines += ["## Resumen\n", job.summary, ""]
    lines.append("## Fotograma a fotograma\n")
    lines += [f"- **{it['time']}** — {it.get('text') or '(error: ' + it.get('error', '') + ')'}" for it in job.items]
    if job.transcript:
        lines += ["\n## Transcripción\n"] + [f"- **{fmt_t(s['start'])}** {s['text']}" for s in job.transcript]
    (out_dir / "analisis.md").write_text("\n".join(lines), "utf-8")
