"""Servidor web de PixAgent: interfaz especializada + WebSocket para el agente en tiempo real."""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse

from .. import pixpin_bridge as PB
from ..agent import Agent
from ..config import Settings
from ..tools.base import guess_kind

STATIC = Path(__file__).parent / "static"
OUTPUT_DIRS = ("plans", "diagrams", "reports", "apps", "outputs", "inbox", "uploads")


def create_app(settings: Settings, llm_factory=None) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(_app):
        state["loop"] = asyncio.get_running_loop()
        task = asyncio.create_task(watch_inbox())
        yield
        task.cancel()

    app = FastAPI(title="PixAgent", lifespan=lifespan)
    ws_root = settings.ws
    clients: set[WebSocket] = set()
    agents: dict[str, Agent] = {}
    running: dict[str, threading.Thread] = {}
    approvals: dict[str, dict] = {}
    state = {"loop": None, "inbox_seen": set(p.name for p in (ws_root / "inbox").glob("*"))}

    # ------------------------------------------------------------- utilidades
    def safe_path(rel: str) -> Path:
        p = (ws_root / rel).resolve()
        if ws_root not in p.parents and p != ws_root:
            raise HTTPException(403, "Ruta fuera del workspace")
        return p

    async def broadcast(ev: dict):
        dead = []
        for c in list(clients):
            try:
                await c.send_json(ev)
            except Exception:  # noqa: BLE001
                dead.append(c)
        for c in dead:
            clients.discard(c)

    def emit_threadsafe(ev: dict):
        loop = state["loop"]
        if loop:
            asyncio.run_coroutine_threadsafe(broadcast(ev), loop)

    def make_approver(session_id: str):
        def approve(name: str, inp: dict) -> bool:
            aid = uuid.uuid4().hex[:10]
            evt = threading.Event()
            approvals[aid] = {"event": evt, "ok": False}
            summary = inp.get("command") or inp.get("code") or inp.get("script") or json.dumps(inp, ensure_ascii=False)
            emit_threadsafe({"type": "approval_request", "id": aid, "session": session_id,
                             "name": name, "summary": str(summary)[:3000]})
            evt.wait(timeout=600)
            return approvals.pop(aid, {}).get("ok", False)
        return approve

    def get_agent(session_id: str | None) -> Agent:
        sid = session_id or ""
        if sid and sid in agents:
            return agents[sid]
        kw = dict(emit=emit_threadsafe)
        if llm_factory:
            kw["llm"] = llm_factory(settings)
        if sid and (ws_root / ".sessions" / f"{sid}.json").exists():
            a = Agent.load(settings, sid, **kw)
        else:
            a = Agent(settings, session_id=sid or None, **kw)
        a.ctx.approve = make_approver(a.session_id)
        agents[a.session_id] = a
        return a

    # ------------------------------------------------------------- vigilancia de la bandeja inbox
    async def watch_inbox():
        inbox = ws_root / "inbox"
        while True:
            await asyncio.sleep(1.0)
            try:
                new = []
                for p in sorted(inbox.glob("*"), key=lambda x: x.stat().st_mtime):
                    if p.is_file() and p.name not in state["inbox_seen"] and p.stat().st_size > 0 \
                            and time.time() - p.stat().st_mtime > 0.4:
                        state["inbox_seen"].add(p.name)
                        new.append(f"inbox/{p.name}")
                if new:
                    await broadcast({"type": "inbox", "files": new})
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------- rutas HTTP
    @app.get("/", response_class=HTMLResponse)
    async def index():
        return (STATIC / "index.html").read_text("utf-8")

    @app.get("/static/{name}")
    async def static(name: str):
        p = (STATIC / name).resolve()
        if STATIC not in p.parents or not p.exists():
            raise HTTPException(404)
        return FileResponse(p)

    @app.get("/files/{rel:path}")
    async def files(rel: str):
        p = safe_path(rel)
        if not p.is_file():
            raise HTTPException(404)
        return FileResponse(p, headers={"Cache-Control": "no-store"})

    @app.get("/api/status")
    async def status():
        try:
            pix = str(PB.find_pixpin(settings.pixpin_path))
        except PB.PixPinNotFound:
            pix = None
        return {"workspace": str(ws_root), "model": settings.model, "effort": settings.effort,
                "pixpin": pix, "permission_mode": settings.permission_mode}

    @app.post("/api/settings")
    async def update_settings(body: dict):
        for k in ("model", "effort", "permission_mode", "pixpin_path", "enable_web"):
            if k in body:
                setattr(settings, k, body[k])
        settings.save()
        return {"ok": True}

    @app.get("/api/sessions")
    async def sessions():
        out = []
        for f in sorted((ws_root / ".sessions").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)[:100]:
            try:
                d = json.loads(f.read_text("utf-8"))
                out.append({"id": d["id"], "title": d.get("title") or d["id"], "updated": d.get("updated")})
            except Exception:  # noqa: BLE001
                continue
        return out

    @app.get("/api/sessions/{sid}")
    async def session(sid: str):
        f = ws_root / ".sessions" / f"{sid}.json"
        if not f.exists():
            raise HTTPException(404)
        d = json.loads(f.read_text("utf-8"))
        return {"id": d["id"], "title": d.get("title"), "transcript": d.get("transcript", []),
                "todos": d.get("state", {}).get("todos", []), "running": sid in running}

    @app.delete("/api/sessions/{sid}")
    async def delete_session(sid: str):
        f = ws_root / ".sessions" / f"{sid}.json"
        if f.exists():
            f.unlink()
        agents.pop(sid, None)
        return {"ok": True}

    @app.post("/api/upload")
    async def upload(files: list[UploadFile] = File(...)):
        day = ws_root / "uploads" / datetime.now().strftime("%Y-%m-%d")
        day.mkdir(parents=True, exist_ok=True)
        saved = []
        for uf in files:
            name = re.sub(r"[^\w.\-() ]+", "_", Path(uf.filename or "archivo").name) or "archivo"
            dest = day / name
            i = 1
            while dest.exists():
                dest = day / f"{Path(name).stem}_{i}{Path(name).suffix}"
                i += 1
            with dest.open("wb") as fh:
                shutil.copyfileobj(uf.file, fh)
            saved.append(dest.relative_to(ws_root).as_posix())
        return {"files": saved}

    @app.get("/api/library")
    async def library():
        items = []
        for d in OUTPUT_DIRS:
            base = ws_root / d
            if not base.exists():
                continue
            for p in base.rglob("*"):
                if not p.is_file() or ".pin." in p.name or p.name.endswith(".scene.json"):
                    continue
                if d == "apps" and p.name not in ("index.html", "manifest.json") and not p.suffix == ".py":
                    continue
                items.append({"path": p.relative_to(ws_root).as_posix(), "kind": guess_kind(p),
                              "folder": d, "mtime": p.stat().st_mtime, "size": p.stat().st_size})
        items.sort(key=lambda x: x["mtime"], reverse=True)
        return items[:400]

    @app.post("/api/pixpin/pin")
    async def pin(body: dict):
        from ..tools.pixpin_tools import _to_pinnable
        a = get_agent(body.get("session"))
        try:
            paths = []
            for rel in body.get("files", []):
                paths += _to_pinnable(a.ctx, safe_path(rel))
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
        return {"ok": True, "file": got.relative_to(ws_root).as_posix()}

    @app.post("/api/pixpin/install")
    async def install_scripts():
        from ..tools.pixpin_tools import install_scripts as inst
        a = get_agent(None)
        r = inst(a.ctx)
        return {"ok": True, "text": r.text}

    # ------------------------------------------------------------- WebSocket del chat
    @app.websocket("/ws")
    async def ws(sock: WebSocket):
        await sock.accept()
        clients.add(sock)
        try:
            while True:
                msg = await sock.receive_json()
                t = msg.get("type")
                if t == "chat":
                    a = get_agent(msg.get("session"))
                    if a.session_id in running and running[a.session_id].is_alive():
                        await sock.send_json({"type": "error", "session": a.session_id,
                                              "text": "El agente sigue trabajando en esta sesión."})
                        continue
                    atts = [safe_path(r) for r in msg.get("attachments", []) if safe_path(r).exists()]
                    await sock.send_json({"type": "session", "session": a.session_id})
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
                    await sock.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            clients.discard(sock)

    return app


def serve(settings: Settings, open_browser: bool = True) -> None:
    import uvicorn
    app = create_app(settings)
    url = f"http://{settings.host}:{settings.port}"
    print(f"PixAgent en {url}  (workspace: {settings.ws})")
    if open_browser:
        import webbrowser
        threading.Timer(1.2, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=settings.host, port=settings.port, log_level="warning")
