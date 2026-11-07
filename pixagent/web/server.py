"""Servidor web de PixAgent.

Diseñado para clientes de todas las plataformas (Windows, macOS, Android, iOS, iPadOS) y móviles
modestos:
- Un único servidor ligero (el "anfitrión") hace el trabajo pesado; los dispositivos son clientes
  web instalables (PWA), sin apps nativas ni Electron que consuman recursos.
- Eventos con número de secuencia y búfer circular: si el móvil pierde la conexión o iOS suspende
  la pestaña, al volver se reanuda sin perder nada.
- Fragmentos de texto agrupados (~60 ms): menos mensajes y menos repintados en el teléfono.
- Miniaturas WebP en caché y páginas de PDF rasterizadas: no se descargan originales pesados.
- Compresión gzip solo para texto (HTML/JS/CSS/JSON), nunca para imágenes (ahorra CPU).
- Token de acceso cuando se abre a la red.
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import threading
import time
import uuid
from collections import deque
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.middleware.gzip import GZipMiddleware

from .. import __version__
from .. import pixpin_bridge as PB
from ..config import Settings
from ..tools.base import guess_kind

STATIC = Path(__file__).parent / "static"
OUTPUT_DIRS = ("plans", "diagrams", "reports", "apps", "outputs", "inbox", "uploads")
DELTA_TYPES = ("text_delta", "thinking_delta")
COOKIE = "pixagent_token"


# ============================================================ eventos
class EventHub:
    """Difunde eventos a todos los clientes con orden garantizado, reanudación y agrupado."""

    def __init__(self, maxlen: int = 4000):
        self.seq = 0
        self.buffer: deque[dict] = deque(maxlen=maxlen)
        self.queues: dict[WebSocket, asyncio.Queue] = {}
        self._pending: dict | None = None
        self._timer: asyncio.TimerHandle | None = None
        self.loop: asyncio.AbstractEventLoop | None = None

    # -- llamadas desde el hilo del bucle de eventos
    def publish(self, ev: dict) -> None:
        if ev.get("type") in DELTA_TYPES:
            p = self._pending
            if p and p["type"] == ev["type"] and p.get("session") == ev.get("session"):
                p["text"] += ev["text"]
                return
            self.flush()
            self._pending = dict(ev)
            self._timer = self.loop.call_later(0.06, self.flush)
            return
        self.flush()
        self._send(ev)

    def flush(self) -> None:
        if self._timer:
            self._timer.cancel()
            self._timer = None
        if self._pending:
            p, self._pending = self._pending, None
            self._send(p)

    def _send(self, ev: dict) -> None:
        self.seq += 1
        ev = {**ev, "seq": self.seq}
        self.buffer.append(ev)
        for q in self.queues.values():
            q.put_nowait(ev)

    # -- desde cualquier hilo
    def publish_threadsafe(self, ev: dict) -> None:
        if self.loop:
            self.loop.call_soon_threadsafe(self.publish, ev)

    def since(self, after: int) -> list[dict]:
        return [e for e in self.buffer if e["seq"] > after]


# ============================================================ aplicación
def create_app(settings: Settings, llm_factory=None, report_writer_factory=None) -> FastAPI:
    from contextlib import asynccontextmanager

    ws_root = settings.ws
    hub = EventHub()
    agents: dict = {}
    running: dict[str, threading.Thread] = {}
    approvals: dict[str, dict] = {}
    state = {"inbox_seen": set(p.name for p in (ws_root / "inbox").glob("*"))}
    static_version = _static_version()

    @asynccontextmanager
    async def lifespan(_app):
        hub.loop = asyncio.get_running_loop()
        task = asyncio.create_task(watch_inbox())
        yield
        task.cancel()

    app = FastAPI(title="PixAgent", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

    # ------------------------------------------------------------- seguridad
    def authorized(token: str | None) -> bool:
        if not settings.require_token:
            return True
        return bool(token) and bool(settings.access_token) and _consteq(token, settings.access_token)

    @app.middleware("http")
    async def auth_mw(request: Request, call_next):
        if settings.require_token:
            path = request.url.path
            q_token = request.query_params.get("token")
            if q_token and authorized(q_token):
                # emparejamiento: guardar cookie y limpiar la URL
                clean = str(request.url.remove_query_params("token"))
                resp = RedirectResponse(clean, status_code=303)
                resp.set_cookie(COOKIE, q_token, max_age=3600 * 24 * 365, httponly=True, samesite="lax",
                                secure=request.url.scheme == "https")
                return resp
            bearer = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
            if not (authorized(request.cookies.get(COOKIE)) or authorized(bearer)):
                if path in ("/manifest.webmanifest", "/static/icon-192.png", "/static/icon-512.png",
                            "/static/apple-touch-icon.png"):
                    return await call_next(request)
                if path == "/" or path.endswith(".html"):
                    return HTMLResponse(LOCKED_HTML, status_code=401)
                return JSONResponse({"error": "Se requiere token de acceso"}, status_code=401)
        return await call_next(request)

    # gzip solo para texto: las imágenes ya están comprimidas y comprimirlas gasta CPU del anfitrión
    app.add_middleware(SelectiveGZip)

    # ------------------------------------------------------------- utilidades
    def safe_path(rel: str) -> Path:
        p = (ws_root / rel).resolve()
        if ws_root not in p.parents and p != ws_root:
            raise HTTPException(403, "Ruta fuera del workspace")
        return p

    def make_approver(session_id: str):
        def approve(name: str, inp: dict) -> bool:
            aid = uuid.uuid4().hex[:10]
            evt = threading.Event()
            approvals[aid] = {"event": evt, "ok": False}
            summary = inp.get("command") or inp.get("code") or inp.get("script") or json.dumps(inp, ensure_ascii=False)
            hub.publish_threadsafe({"type": "approval_request", "id": aid, "session": session_id,
                                    "name": name, "summary": str(summary)[:3000]})
            evt.wait(timeout=600)
            ok = approvals.pop(aid, {}).get("ok", False)
            hub.publish_threadsafe({"type": "approval_resolved", "id": aid, "session": session_id})
            return ok
        return approve

    def get_agent(session_id: str | None):
        from ..agent import Agent  # import diferido: arranque más rápido y ligero
        sid = session_id or ""
        if sid and sid in agents:
            return agents[sid]
        kw = dict(emit=hub.publish_threadsafe)
        if llm_factory:
            kw["llm"] = llm_factory(settings)
        if sid and (ws_root / ".sessions" / f"{sid}.json").exists():
            a = Agent.load(settings, sid, **kw)
        else:
            a = Agent(settings, session_id=sid or None, **kw)
        a.ctx.approve = make_approver(a.session_id)
        agents[a.session_id] = a
        # liberar memoria de sesiones inactivas (máx. 8 en RAM)
        if len(agents) > 8:
            for old in list(agents)[:-8]:
                if old not in running or not running[old].is_alive():
                    agents.pop(old, None)
        return a

    def save_upload(uf: UploadFile, folder: Path) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        name = re.sub(r"[^\w.\-() ]+", "_", Path(uf.filename or "archivo").name) or "archivo"
        dest = folder / name
        i = 1
        while dest.exists():
            dest = folder / f"{Path(name).stem}_{i}{Path(name).suffix}"
            i += 1
        with dest.open("wb") as fh:
            shutil.copyfileobj(uf.file, fh, length=256 * 1024)
        return dest

    # ------------------------------------------------------------- bandeja de entrada (PixPin)
    async def watch_inbox():
        inbox = ws_root / "inbox"
        while True:
            await asyncio.sleep(1.5)
            try:
                new = []
                with_mtime = [(p, p.stat()) for p in inbox.iterdir() if p.is_file()]
                for p, st in sorted(with_mtime, key=lambda x: x[1].st_mtime):
                    if p.name not in state["inbox_seen"] and st.st_size > 0 and time.time() - st.st_mtime > 0.4:
                        state["inbox_seen"].add(p.name)
                        new.append(f"inbox/{p.name}")
                if new:
                    hub.publish({"type": "inbox", "files": new})
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------- páginas y PWA
    def page() -> str:
        html = (STATIC / "index.html").read_text("utf-8")
        return html.replace("{{V}}", static_version)

    @app.get("/", response_class=HTMLResponse)
    async def index():
        return HTMLResponse(page(), headers={"Cache-Control": "no-cache"})

    @app.get("/manifest.webmanifest")
    async def manifest():
        return Response((STATIC / "manifest.webmanifest").read_text("utf-8"),
                        media_type="application/manifest+json", headers={"Cache-Control": "no-cache"})

    @app.get("/sw.js")
    async def sw():
        js = (STATIC / "sw.js").read_text("utf-8").replace("{{V}}", static_version)
        return Response(js, media_type="application/javascript",
                        headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    @app.get("/static/{name}")
    async def static(name: str):
        p = (STATIC / name).resolve()
        if STATIC not in p.parents or not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    # ------------------------------------------------------------- archivos y miniaturas
    @app.get("/files/{rel:path}")
    async def files(rel: str):
        p = safe_path(rel)
        if not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "private, max-age=60"})

    @app.get("/thumb/{rel:path}")
    async def thumb(rel: str, w: int = 480, page: int = 0):
        from .thumbs import make_thumb
        p = safe_path(rel)
        if not p.is_file():
            raise HTTPException(404)
        try:
            t = await asyncio.to_thread(make_thumb, ws_root, p, w, page)
        except Exception:  # noqa: BLE001
            t = None
        if t is None:
            if p.suffix.lower() == ".pdf":
                raise HTTPException(415, "Instala pymupdf para ver páginas de PDF como imágenes")
            return FileResponse(p, headers={"Cache-Control": "private, max-age=60"})
        return FileResponse(t, media_type="image/webp",
                            headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @app.get("/api/pdfinfo/{rel:path}")
    async def pdfinfo(rel: str):
        from .thumbs import pdf_page_count
        return {"pages": await asyncio.to_thread(pdf_page_count, safe_path(rel))}

    # ------------------------------------------------------------- API
    @app.get("/api/status")
    async def status(request: Request):
        try:
            pix = str(PB.find_pixpin(settings.pixpin_path))
        except PB.PixPinNotFound:
            pix = None
        return {"workspace": str(ws_root), "model": settings.model, "effort": settings.effort,
                "pixpin": pix, "permission_mode": settings.permission_mode, "seq": hub.seq,
                "version": __version__, "upload_max_px": settings.upload_max_px,
                "is_host": request.client is not None and request.client.host in ("127.0.0.1", "::1")}

    @app.post("/api/settings")
    async def update_settings(body: dict):
        for k in ("model", "effort", "permission_mode", "pixpin_path", "enable_web", "upload_max_px"):
            if k in body:
                setattr(settings, k, body[k])
        settings.save()
        return {"ok": True}

    @app.get("/api/sessions")
    async def sessions():
        out = []
        files_ = sorted((ws_root / ".sessions").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:60]
        for f in files_:
            title = _read_title(f)
            out.append({"id": f.stem, "title": title or f.stem, "updated": f.stat().st_mtime})
        return out

    @app.get("/api/sessions/{sid}")
    async def session(sid: str, limit: int = 120):
        f = ws_root / ".sessions" / f"{sid}.json"
        if not f.exists():
            raise HTTPException(404)
        d = await asyncio.to_thread(lambda: json.loads(f.read_text("utf-8")))
        tr = d.get("transcript", [])
        return {"id": d["id"], "title": d.get("title"), "transcript": tr[-limit:], "truncated": len(tr) > limit,
                "todos": d.get("state", {}).get("todos", []),
                "running": sid in running and running[sid].is_alive()}

    @app.delete("/api/sessions/{sid}")
    async def delete_session(sid: str):
        f = ws_root / ".sessions" / f"{sid}.json"
        if f.exists():
            f.unlink()
        agents.pop(sid, None)
        return {"ok": True}

    @app.post("/api/sessions/{sid}/undo")
    async def undo(sid: str):
        if sid in running and running[sid].is_alive():
            return JSONResponse({"ok": False, "error": "Espera a que el agente termine"}, status_code=409)
        a = get_agent(sid)
        restored = await asyncio.to_thread(a.undo_last_turn)
        if not restored:
            return {"ok": False, "error": "No hay cambios que deshacer"}
        return {"ok": True, "restored": restored}

    @app.post("/api/upload")
    async def upload(files: list[UploadFile] = File(...)):
        day = ws_root / "uploads" / datetime.now().strftime("%Y-%m-%d")
        saved = [await asyncio.to_thread(save_upload, uf, day) for uf in files]
        return {"files": [p.relative_to(ws_root).as_posix() for p in saved]}

    @app.post("/share-target")
    async def share_target(request: Request):
        """Destino de 'Compartir' en Android: fotos/PDF de la galería u otras apps llegan a la bandeja."""
        form = await request.form()
        for v in form.getlist("files"):
            if hasattr(v, "filename") and v.filename:
                await asyncio.to_thread(save_upload, v, ws_root / "inbox")
        text = " ".join(str(form.get(k) or "") for k in ("title", "text", "url")).strip()
        if text:
            (ws_root / "inbox" / f"compartido_{datetime.now():%Y%m%d_%H%M%S}.txt").write_text(text, "utf-8")
        return RedirectResponse("/?shared=1", status_code=303)

    @app.get("/api/library")
    async def library(limit: int = 200):
        def scan():
            items = []
            for d in OUTPUT_DIRS:
                base = ws_root / d
                if not base.exists():
                    continue
                for p in base.rglob("*"):
                    if not p.is_file() or ".pin." in p.name or p.name.endswith((".scene.json", ".diagram.json")):
                        continue
                    if d == "apps" and p.name not in ("index.html",) and p.suffix != ".py":
                        continue
                    st = p.stat()
                    items.append({"path": p.relative_to(ws_root).as_posix(), "kind": guess_kind(p),
                                  "folder": d, "mtime": st.st_mtime, "size": st.st_size})
            items.sort(key=lambda x: x["mtime"], reverse=True)
            return items[:limit]
        return await asyncio.to_thread(scan)

    @app.post("/api/pixpin/pin")
    async def pin(body: dict):
        from ..tools.pixpin_tools import _to_pinnable
        a = get_agent(body.get("session"))
        try:
            paths = []
            for rel in body.get("files", []):
                paths += await asyncio.to_thread(_to_pinnable, a.ctx, safe_path(rel))
            await asyncio.to_thread(PB.pin_files, paths, settings.pixpin_path, ws_root / ".tmp")
            return {"ok": True, "pinned": [p.relative_to(ws_root).as_posix() for p in paths]}
        except PB.PixPinNotFound as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    @app.post("/api/pixpin/capture")
    async def capture(body: dict):
        region = body.get("region", "last")
        target = ws_root / "inbox" / f"captura_{datetime.now():%Y%m%d_%H%M%S}.png"
        try:
            got = await asyncio.to_thread(PB.capture, target, region, settings.pixpin_path, 8.0, ws_root / ".tmp")
        except PB.PixPinNotFound as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        if not got:
            return JSONResponse({"ok": False, "error": "PixPin no devolvió la captura."}, status_code=504)
        state["inbox_seen"].add(got.name)
        return {"ok": True, "file": got.relative_to(ws_root).as_posix()}

    @app.post("/api/pixpin/install")
    async def install_scripts():
        from ..tools.pixpin_tools import install_scripts as inst
        r = inst(get_agent(None).ctx)
        return {"ok": True, "text": r.text}

    # ------------------------------------------------------------- mini apps
    MINIAPPS = Path(__file__).resolve().parents[1] / "miniapps"

    def app_dirs():
        for builtin, root in ((True, MINIAPPS), (False, ws_root / "apps")):
            if root.exists():
                for d in sorted(root.iterdir()):
                    if d.is_dir() and (d / "manifest.json").exists():
                        yield builtin, d

    @app.get("/api/apps")
    async def list_apps():
        out = []
        for builtin, d in app_dirs():
            try:
                m = json.loads((d / "manifest.json").read_text("utf-8"))
            except Exception:  # noqa: BLE001
                continue
            out.append({"slug": d.name, "name": m.get("name", d.name), "description": m.get("description", ""),
                        "icon": m.get("icon", "🧩"), "category": m.get("category", "Mis apps" if not builtin else "General"),
                        "kind": m.get("kind", "web"), "uses_ai": m.get("uses_ai", False), "builtin": builtin,
                        "url": f"/apps/{d.name}/" if m.get("kind", "web") == "web" else None,
                        "entry": m.get("entry", "index.html")})
        return out

    @app.get("/apps/{slug}/{rel:path}")
    async def serve_app(slug: str, rel: str = ""):
        for _b, d in app_dirs():
            if d.name == slug:
                p = (d / (rel or "index.html")).resolve()
                if d.resolve() not in p.parents or not p.is_file():
                    raise HTTPException(404)
                return FileResponse(p, headers={"Cache-Control": "no-cache"})
        raise HTTPException(404)

    @app.get("/apps/{slug}")
    async def app_root(slug: str):
        return RedirectResponse(f"/apps/{slug}/")

    @app.post("/api/files/save")
    async def files_save(file: UploadFile = File(...), folder: str = Form("")):
        sub = re.sub(r"[^\w\-/]+", "_", folder).strip("/") or "miniapps"
        dest_dir = safe_path(f"outputs/{sub}")
        p = await asyncio.to_thread(save_upload, file, dest_dir)
        return {"ok": True, "path": p.relative_to(ws_root).as_posix()}

    @app.get("/api/files/list")
    async def files_list(folder: str = ""):
        base = safe_path(folder or ".")
        if not base.is_dir():
            return {"files": []}
        res = []
        for p in sorted(base.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True)[:500]:
            if p.is_file() and not p.name.startswith("."):
                st = p.stat()
                res.append({"path": p.relative_to(ws_root).as_posix(), "size": st.st_size,
                            "mtime": st.st_mtime, "kind": guess_kind(p)})
        return {"files": res}

    @app.post("/api/photo-panel")
    async def photo_panel_api(spec: dict):
        from ..tools.panel import build_photo_panel
        from ..tools.base import ToolError
        try:
            out, pages = await asyncio.to_thread(build_photo_panel, get_agent(None).ctx, spec)
        except ToolError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)
        return {"ok": True, "path": out.relative_to(ws_root).as_posix(), "pages": pages}

    @app.post("/api/ai/quick")
    async def ai_quick(body: dict):
        from ..quick_ai import quick_ai
        try:
            return await asyncio.to_thread(quick_ai, settings, body)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)

    # ------------------------------------------------------------- informes estructurados
    from ..reports import engine as RE
    report_jobs: dict[str, "RE.ReportGenerator"] = {}

    def project_or_404(rid: str):
        p = RE.ReportProject(ws_root, rid)
        if not p.data:
            raise HTTPException(404, "Informe no encontrado")
        return p

    def project_payload(p):
        st = p.status()
        job = report_jobs.get(p.id)
        return {**{k: v for k, v in p.data.items() if k != "units"}, **st,
                "running": bool(job and getattr(job, "_thread", None) and job._thread.is_alive()),
                "estimate": p.estimate()}

    @app.get("/report")
    @app.get("/reports")
    async def reports_page():
        f = STATIC / "reports.html"
        if not f.exists():
            raise HTTPException(404, "La interfaz de informes aún no está instalada")
        return HTMLResponse(f.read_text("utf-8").replace("{{V}}", static_version), headers={"Cache-Control": "no-cache"})

    @app.get("/api/report-templates")
    async def rt_list():
        return RE.Templates(ws_root).list()

    @app.get("/api/report-templates/{tid}")
    async def rt_get(tid: str):
        try:
            return RE.Templates(ws_root).get(tid)
        except KeyError:
            raise HTTPException(404)

    @app.post("/api/report-templates")
    async def rt_save(body: dict):
        try:
            return {"ok": True, "template": RE.Templates(ws_root).save(body)}
        except ValueError as e:
            return JSONResponse({"ok": False, "error": str(e)}, status_code=400)

    @app.delete("/api/report-templates/{tid}")
    async def rt_delete(tid: str):
        RE.Templates(ws_root).delete(tid)
        return {"ok": True}

    @app.get("/api/reports")
    async def rp_list():
        return await asyncio.to_thread(RE.list_projects, ws_root)

    @app.post("/api/reports")
    async def rp_create(body: dict):
        try:
            tpl = RE.Templates(ws_root).get(body.get("template_id", ""))
        except KeyError:
            return JSONResponse({"ok": False, "error": "Plantilla no encontrada"}, status_code=400)
        p = RE.ReportProject.create(ws_root, tpl, body.get("title") or tpl["name"], body.get("fields"),
                                    body.get("notes", ""), body.get("photos"), body.get("target_pages"),
                                    body.get("model") or settings.model)
        return {"ok": True, "report": project_payload(p)}

    @app.get("/api/reports/{rid}")
    async def rp_get(rid: str):
        return project_payload(project_or_404(rid))

    @app.put("/api/reports/{rid}")
    async def rp_update(rid: str, body: dict):
        p = project_or_404(rid)
        p.update(**body)
        return {"ok": True, "report": project_payload(p)}

    @app.delete("/api/reports/{rid}")
    async def rp_delete(rid: str):
        p = project_or_404(rid)
        shutil.rmtree(p.dir, ignore_errors=True)
        return {"ok": True}

    @app.get("/api/reports/{rid}/sections/{uid}")
    async def rp_section(rid: str, uid: str):
        p = project_or_404(rid)
        f = p.section_file(uid)
        return {"id": uid, "markdown": f.read_text("utf-8") if f.exists() else ""}

    @app.put("/api/reports/{rid}/sections/{uid}")
    async def rp_section_save(rid: str, uid: str, body: dict):
        p = project_or_404(rid)
        p.section_file(uid).write_text(body.get("markdown", ""), "utf-8")
        p.set_unit(uid, status="done", edited=True, words=len(body.get("markdown", "").split()), error=None)
        return {"ok": True}

    @app.post("/api/reports/{rid}/generate")
    async def rp_generate(rid: str, body: dict | None = None):
        body = body or {}
        p = project_or_404(rid)
        job = report_jobs.get(rid)
        if job and job._thread.is_alive():
            return JSONResponse({"ok": False, "error": "Ya se está generando"}, status_code=409)
        if body.get("unlock"):  # permitir regenerar partes editadas a mano
            for uid in body.get("sections") or []:
                p.set_unit(uid, edited=False)
        kw = {"writer": report_writer_factory(settings, p)} if report_writer_factory else {}
        gen = RE.ReportGenerator(settings, p, emit=hub.publish_threadsafe, **kw)
        gen._thread = threading.Thread(target=gen.run, kwargs={"only": body.get("sections"), "force": bool(body.get("force"))},
                                       daemon=True)
        report_jobs[rid] = gen
        gen._thread.start()
        return {"ok": True}

    @app.post("/api/reports/{rid}/cancel")
    async def rp_cancel(rid: str):
        job = report_jobs.get(rid)
        if job:
            job.cancelled = True
        return {"ok": True}

    @app.post("/api/reports/{rid}/build")
    async def rp_build(rid: str):
        p = project_or_404(rid)
        try:
            out = await asyncio.to_thread(RE.build_report_pdf, settings, p)
        except Exception as e:  # noqa: BLE001
            return JSONResponse({"ok": False, "error": str(e)}, status_code=500)
        from .thumbs import pdf_page_count
        return {"ok": True, "path": out.relative_to(ws_root).as_posix(), "pages": pdf_page_count(out),
                "warnings": p.data.get("outputs", {}).get("warnings", [])}

    # ------------------------------------------------------------- WebSocket
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        if settings.require_token:
            tok = sock.cookies.get(COOKIE) or sock.query_params.get("token")
            if not authorized(tok):
                await sock.close(code=4401)
                return
        await sock.accept()
        q: asyncio.Queue = asyncio.Queue()
        hub.queues[sock] = q

        async def writer():
            while True:
                ev = await q.get()
                await sock.send_json(ev)
        wtask = asyncio.create_task(writer())
        try:
            while True:
                msg = await sock.receive_json()
                t = msg.get("type")
                if t == "hello":
                    # reanudar: reenviar lo que el cliente se perdió (salvo aprobaciones ya resueltas)
                    for ev in hub.since(int(msg.get("after") or 0)):
                        if ev["type"] == "approval_request" and ev["id"] not in approvals:
                            continue
                        q.put_nowait(ev)
                    q.put_nowait({"type": "hello_ok", "seq": hub.seq})
                elif t == "chat":
                    a = get_agent(msg.get("session"))
                    if a.session_id in running and running[a.session_id].is_alive():
                        q.put_nowait({"type": "error", "session": a.session_id,
                                      "text": "El agente sigue trabajando en esta sesión."})
                        continue
                    atts = []
                    for r in msg.get("attachments", []):
                        p = safe_path(r)
                        if p.exists():
                            atts.append(p)
                    hub.publish({"type": "session", "session": a.session_id, "client": msg.get("client")})
                    th = threading.Thread(target=a.run, args=(msg.get("text", ""), atts), daemon=True)
                    running[a.session_id] = th
                    th.start()
                elif t == "approve":
                    ap = approvals.get(msg.get("id"))
                    if ap:
                        ap["ok"] = bool(msg.get("ok"))
                        ap["event"].set()
                elif t == "cancel":
                    a = agents.get(msg.get("session"))
                    if a:
                        a.cancel()
                elif t == "ping":
                    q.put_nowait({"type": "pong"})
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            wtask.cancel()
            hub.queues.pop(sock, None)

    app.state.hub = hub
    return app


# ============================================================ utilidades
class SelectiveGZip:
    """Middleware ASGI: comprime HTML/JS/CSS/JSON pero no imágenes, PDFs ni descargas."""

    def __init__(self, app, minimum_size: int = 800):
        self.app = app
        self.gz = GZipMiddleware(app, minimum_size=minimum_size)

    async def __call__(self, scope, receive, send):
        path = scope.get("path", "") if scope["type"] == "http" else ""
        if path == "/" or path.startswith(("/static/", "/api/")) or path in ("/sw.js", "/manifest.webmanifest"):
            if not path.endswith((".png", ".jpg", ".webp")):
                await self.gz(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _consteq(a: str, b: str) -> bool:
    import hmac
    return hmac.compare_digest(a.encode(), b.encode())


def _read_title(f: Path) -> str:
    """Lee solo el principio del JSON de sesión para obtener el título (sin cargarlo entero)."""
    try:
        with f.open("r", encoding="utf-8") as fh:
            head = fh.read(600)
        m = re.search(r'"title":\s*"((?:[^"\\]|\\.)*)"', head)
        return json.loads(f'"{m.group(1)}"') if m else ""
    except Exception:  # noqa: BLE001
        return ""


def _static_version() -> str:
    import hashlib
    h = hashlib.sha1(__version__.encode())
    for p in sorted(STATIC.glob("*")):
        if p.is_file():
            h.update(p.read_bytes())
    return h.hexdigest()[:10]


LOCKED_HTML = """<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>PixAgent</title>
<style>body{font-family:system-ui,sans-serif;display:grid;place-items:center;min-height:100vh;margin:0;
background:#0f1117;color:#e6e8ef;padding:16px}form{max-width:360px;width:100%}input,button{width:100%;
padding:12px;font-size:16px;border-radius:10px;border:1px solid #2a2f3e;margin-top:10px;box-sizing:border-box}
button{background:#6366f1;color:#fff;border:0}</style></head><body><form method="get" action="/">
<h2>PixAgent</h2><p>Escanea el código QR que muestra el anfitrión o escribe el token de acceso.</p>
<input name="token" placeholder="Token de acceso" autocomplete="off"><button>Entrar</button></form></body></html>"""


# ============================================================ arranque
def lan_ip() -> str:
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def print_pairing(url: str) -> None:
    print(f"\n  Abre en el móvil/tablet: {url}")
    try:
        import qrcode
        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.print_ascii(invert=True)
    except ImportError:
        print("  (pip install qrcode para ver un código QR aquí)")


def open_app_window(url: str) -> None:
    """Abre la interfaz como ventana de aplicación (Edge/Chrome --app) si es posible: sensación de app
    nativa sin el coste de Electron. Si no, usa el navegador por defecto."""
    import subprocess
    import webbrowser
    from ..tools.browser import find_browser
    exe = find_browser()
    if exe and "pw-browsers" not in exe:
        try:
            subprocess.Popen([exe, f"--app={url}", "--window-size=1400,900"],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return
        except OSError:
            pass
    webbrowser.open(url)


def serve(settings: Settings, open_browser: bool = True) -> None:
    import uvicorn
    from ..config import ensure_token
    remote = settings.host not in ("127.0.0.1", "localhost", "::1")
    if remote:
        settings.require_token = True
    token = ensure_token(settings) if settings.require_token else ""
    scheme = "https" if settings.ssl_certfile else "http"
    local = f"{scheme}://127.0.0.1:{settings.port}/" + (f"?token={token}" if token else "")
    print(f"PixAgent {__version__} · workspace: {settings.ws}")
    print(f"  En este equipo: {local}")
    if remote:
        print_pairing(f"{scheme}://{lan_ip()}:{settings.port}/?token={token}")
        if scheme == "http":
            print("  Nota: para INSTALAR la app (PWA) en Android/iOS se necesita HTTPS; ver README (Tailscale).")
    app = create_app(settings)
    if open_browser:
        threading.Timer(1.0, lambda: open_app_window(local)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning",
                ssl_certfile=settings.ssl_certfile or None, ssl_keyfile=settings.ssl_keyfile or None,
                ws_ping_interval=25, ws_ping_timeout=30, timeout_keep_alive=30)
