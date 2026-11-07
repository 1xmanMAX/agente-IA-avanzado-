"""Tests sin red: herramientas reales + bucle del agente con un LLM simulado + servidor web."""
from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
from PIL import Image, ImageDraw


@pytest.fixture()
def settings(tmp_path, monkeypatch):
    monkeypatch.setenv("PIXAGENT_HOME", str(tmp_path / "home"))
    monkeypatch.setenv("PIXAGENT_WORKSPACE", str(tmp_path / "ws"))
    import importlib
    import pixagent.config as cfg
    importlib.reload(cfg)
    s = cfg.load_settings()
    s.enable_web = False
    im = Image.new("RGB", (800, 500), "white")
    d = ImageDraw.Draw(im)
    d.rectangle([20, 20, 780, 480], outline="black", width=6)
    im.save(s.ws / "uploads" / "plano.png")
    Image.new("RGB", (640, 480), "#c33").save(s.ws / "uploads" / "foto1.jpg")
    return s


@pytest.fixture()
def ctx(settings):
    from pixagent.tools import ToolContext
    return ToolContext(settings=settings)


# ----------------------------------------------------------------- herramientas
def test_registry_specs_are_valid():
    from pixagent.tools import REGISTRY
    assert {"compose_plan", "render_diagram", "create_pdf", "create_miniapp", "pixpin", "run_python"} <= set(REGISTRY)
    for t in REGISTRY.values():
        spec = t.spec()
        assert spec["input_schema"]["type"] == "object"
        json.dumps(spec)


def test_paths_are_confined(ctx):
    from pixagent.tools import ToolError
    with pytest.raises(ToolError):
        ctx.resolve("../../etc/passwd")


def test_write_edit_read(ctx):
    from pixagent.tools import REGISTRY
    REGISTRY["write_file"].func(ctx, path="outputs/a.txt", content="hola mundo")
    REGISTRY["edit_file"].func(ctx, path="outputs/a.txt", old_string="mundo", new_string="PixPin")
    assert "hola PixPin" in REGISTRY["read_file"].func(ctx, path="outputs/a.txt").text


def test_compose_plan_with_photos(ctx):
    from pixagent.tools import REGISTRY
    r = REGISTRY["compose_plan"].func(
        ctx, output="plans/p.png", base="uploads/plano.png", scale={"px_per_meter": 50}, pdf=True,
        title_block={"title": "Prueba"},
        elements=[{"type": "photo", "src": "uploads/foto1.jpg", "anchor": [200, 200], "caption": "Foto",
                   "view_angle": 0},
                  {"type": "room", "points": [[20, 20], [400, 20], [400, 250], [20, 250]], "name": "Sala"},
                  {"type": "dimension", "from": [20, 480], "to": [780, 480]},
                  {"type": "arrow", "from": [500, 400], "to": [600, 300], "label": "x"}])
    assert not r.is_error
    out = ctx.ws / "plans" / "p.png"
    assert out.exists() and (ctx.ws / "plans" / "p.pdf").exists()
    scene = json.loads((ctx.ws / "plans" / "p.scene.json").read_text("utf-8"))
    assert scene["elements"][0]["number"] == 1
    # re-edición desde la escena guardada
    r2 = REGISTRY["compose_plan"].func(ctx, output="plans/p2.png", scene_path="plans/p.scene.json", theme_color="#1f77b4")
    assert not r2.is_error and (ctx.ws / "plans" / "p2.png").exists()


def test_diagram_and_pdf(ctx):
    from pixagent.tools import REGISTRY
    r = REGISTRY["render_diagram"].func(ctx, output="diagrams/d", nodes=[{"id": "a"}, {"id": "b", "shape": "diamond"}],
                                        edges=[{"from": "a", "to": "b"}, {"from": "b", "to": "a"}])
    assert (ctx.ws / "diagrams" / "d.png").exists() and (ctx.ws / "diagrams" / "d.svg").exists()
    r = REGISTRY["create_pdf"].func(ctx, output="reports/r.pdf", title="T", toc=True,
                                    markdown="# Uno\nTexto con ñ.\n\n| a | b |\n|---|---|\n| 1 | 2 |\n\n![p](diagrams/d.png)")
    assert not r.is_error and (ctx.ws / "reports" / "r.pdf").exists()
    r = REGISTRY["pdf_tools"].func(ctx, action="read_text", path="reports/r.pdf")
    assert "Uno" in r.text


def test_run_python_reports_images(ctx):
    from pixagent.tools import REGISTRY
    r = REGISTRY["run_python"].func(ctx, code="from PIL import Image\nImage.new('RGB',(10,10)).save('outputs/x.png')\nprint('hecho')")
    assert "hecho" in r.text and any(p.name == "x.png" for p in r.images)


def test_pixpin_scripts_and_js(ctx, tmp_path):
    from pixagent import pixpin_bridge as PB
    from pixagent.tools.pixpin_tools import install_scripts
    js = PB.pin_files_js([tmp_path / "a b.png"])
    assert "pixpin.pinFromFiles" in js and "a b.png" in js and "\\" not in js
    r = install_scripts(ctx)
    names = {f.name for f in r.files}
    assert "01_enviar_ultima_captura.js" in names
    content = (ctx.ws / "pixpin_scripts" / "01_enviar_ultima_captura.js").read_text("utf-8-sig")
    assert "directScreenShotAndSaveTo" in content and "SpRectLastShotRect" in content


def test_miniapp_creates_launcher(ctx):
    from pixagent.tools import REGISTRY
    r = REGISTRY["create_miniapp"].func(ctx, name="Conversor Ñandú", kind="python",
                                        files={"main.py": "print('ok')"})
    root = ctx.ws / "apps" / "conversor_nandu"
    assert (root / "manifest.json").exists()
    assert "pixpin.runSystem" in (root / "abrir_en_pixpin.js").read_text("utf-8-sig")


# ----------------------------------------------------------------- bucle del agente
class FakeLLM:
    """Simula a Claude: primero pide herramientas, luego responde con texto."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def turn(self, messages, tools, emit):
        self.calls.append(messages[-1])
        content, stop = self.script.pop(0)
        for b in content:
            if b.type == "text":
                emit({"type": "text_delta", "text": b.text})
        return NS(content=content, stop_reason=stop, usage=NS(input_tokens=10, output_tokens=5,
                                                              cache_read_input_tokens=0))


def tu(id_, name, inp):
    return NS(type="tool_use", id=id_, name=name, input=inp,
              model_dump=lambda **k: {"type": "tool_use", "id": id_, "name": name, "input": inp})


def txt(t):
    return NS(type="text", text=t, model_dump=lambda **k: {"type": "text", "text": t})


def test_agent_loop_executes_tools_and_feeds_images(settings):
    from pixagent.agent import Agent
    llm = FakeLLM([
        ([txt("Miro el plano."), tu("t1", "view_image", {"path": "uploads/plano.png", "grid": True}),
          tu("t2", "todo_write", {"todos": [{"content": "Ubicar fotos", "status": "in_progress"}]})], "tool_use"),
        ([tu("t3", "compose_plan", {"output": "plans/x.png", "base": "uploads/plano.png",
                                    "elements": [{"type": "photo", "src": "uploads/foto1.jpg", "anchor": [100, 100]}]})],
         "tool_use"),
        ([txt("Listo: plans/x.png")], "end_turn"),
    ])
    events = []
    a = Agent(settings, llm=llm, emit=events.append)
    out = a.run("Ubica la foto en el plano", [settings.ws / "uploads" / "plano.png"])
    assert out == "Listo: plans/x.png"
    # el primer mensaje incluye la imagen adjunta y la ruta
    first = a.messages[0]["content"]
    assert first[0]["type"] == "image" and "uploads/plano.png" in first[-1]["text"]
    # ambos resultados del primer turno van en UN solo mensaje de usuario, con imagen
    results = a.messages[2]["content"]
    assert [r["tool_use_id"] for r in results] == ["t1", "t2"]
    assert any(b["type"] == "image" for b in results[0]["content"])
    assert (settings.ws / "plans" / "x.png").exists()
    assert any(e["type"] == "todos" for e in events)
    # la sesión se guarda y se puede recargar
    b = Agent.load(settings, a.session_id, llm=llm)
    assert len(b.messages) == len(a.messages)


def test_agent_handles_bad_tool_input_and_denial(settings):
    from pixagent.agent import Agent
    settings.permission_mode = "auto"
    llm = FakeLLM([
        ([tu("a", "compose_plan", {}), tu("b", "run_shell", {"command": "echo hi"}),
          tu("c", "no_existe", {})], "tool_use"),
        ([txt("ok")], "end_turn"),
    ])
    a = Agent(settings, llm=llm, approve=lambda n, i: False)
    a.run("prueba")
    res = a.messages[2]["content"]
    assert all(r.get("is_error") for r in res)
    assert "output" in res[0]["content"][0]["text"]
    assert "no autorizó" in res[1]["content"][0]["text"]


def test_fallback_sanitizer():
    from pixagent.agent import sanitize_fallback
    content = [NS(type="thinking"), NS(type="tool_use", id="x"), NS(type="text", text="a"),
               NS(type="fallback"), NS(type="thinking"), NS(type="text", text="b")]
    kept = [b.type for b in sanitize_fallback(content)]
    assert kept == ["text", "fallback", "thinking", "text"]


def test_llm_params_shape(settings):
    from pixagent.llm import ClaudeLLM
    p = ClaudeLLM(settings, client=object())._params([], [{"name": "x"}])
    assert p["model"] == "claude-opus-5-5"
    assert p["thinking"]["type"] == "adaptive" and p["output_config"]["effort"] == settings.effort
    assert p["fallbacks"] == "default" and "server-side-fallback-2026-07-01" in p["betas"]
    assert "temperature" not in p


# ----------------------------------------------------------------- servidor web
def test_web_server_end_to_end(settings):
    from fastapi.testclient import TestClient
    from pixagent.web.server import create_app
    script = [([txt("Hola, soy PixAgent.")], "end_turn")]
    app = create_app(settings, llm_factory=lambda s: FakeLLM(script))
    with TestClient(app) as c:
        assert c.get("/").status_code == 200
        up = c.post("/api/upload", files=[("files", ("foto.png", open(settings.ws / "uploads" / "foto1.jpg", "rb"), "image/png"))])
        rel = up.json()["files"][0]
        assert c.get("/files/" + rel).status_code == 200
        assert c.get("/files/../../etc/passwd").status_code in (403, 404)
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"type": "chat", "text": "hola", "attachments": [rel]})
            seen = []
            for _ in range(50):
                ev = ws.receive_json()
                seen.append(ev["type"])
                if ev["type"] == "done":
                    break
            assert "session" in seen and "assistant" in seen and seen[-1] == "done"
        sessions = c.get("/api/sessions").json()
        assert sessions and c.get(f"/api/sessions/{sessions[0]['id']}").json()["transcript"]
        assert c.get("/api/library").status_code == 200


# ----------------------------------------------------------------- multiplataforma / rendimiento
def test_token_auth_and_pairing(settings):
    from fastapi.testclient import TestClient
    from starlette.websockets import WebSocketDisconnect
    from pixagent.web.server import create_app
    settings.require_token = True
    settings.access_token = "secreto123"
    app = create_app(settings, llm_factory=lambda s: FakeLLM([]))
    with TestClient(app) as c:
        assert c.get("/").status_code == 401
        assert c.get("/api/status").status_code == 401
        assert c.get("/manifest.webmanifest").status_code == 200  # el icono/manifest no exponen nada
        with pytest.raises(WebSocketDisconnect):
            with c.websocket_connect("/ws") as ws:
                ws.receive_json()
        r = c.get("/?token=malo", follow_redirects=False)
        assert r.status_code == 401
        r = c.get("/?token=secreto123", follow_redirects=False)
        assert r.status_code == 303 and "token" not in r.headers["location"]
        assert c.cookies.get("pixagent_token") == "secreto123"
        assert c.get("/api/status").status_code == 200
        assert c.get("/api/status", headers={"Authorization": "Bearer secreto123"}).status_code == 200
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"type": "ping"})
            assert ws.receive_json()["type"] == "pong"


def test_thumbnails_and_pdf_pages(settings):
    from fastapi.testclient import TestClient
    from pixagent.web.server import create_app
    big = settings.ws / "uploads" / "grande.jpg"
    Image.new("RGB", (4000, 3000), "#3a7").save(big, quality=95)
    from pixagent.tools import REGISTRY, ToolContext
    REGISTRY["create_pdf"].func(ToolContext(settings=settings), output="reports/t.pdf", markdown="# Hola\n\\pagebreak\n# Dos")
    app = create_app(settings, llm_factory=lambda s: FakeLLM([]))
    with TestClient(app) as c:
        r = c.get("/thumb/uploads/grande.jpg?w=300")
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
        assert len(r.content) < 20_000 and "immutable" in r.headers["cache-control"]
        assert Image.open(__import__("io").BytesIO(r.content)).width == 320  # tamaño redondeado
        assert c.get("/api/pdfinfo/reports/t.pdf").json()["pages"] == 2
        r = c.get("/thumb/reports/t.pdf?w=480&page=1")
        assert r.status_code == 200 and r.headers["content-type"] == "image/webp"
        # gzip para JSON/JS, nunca para imágenes
        assert c.get("/static/app.js", headers={"Accept-Encoding": "gzip"}).headers.get("content-encoding") == "gzip"
        assert "content-encoding" not in c.get("/thumb/uploads/grande.jpg?w=300", headers={"Accept-Encoding": "gzip"}).headers


def test_share_target_and_pwa(settings):
    from fastapi.testclient import TestClient
    from pixagent.web.server import create_app
    app = create_app(settings, llm_factory=lambda s: FakeLLM([]))
    with TestClient(app) as c:
        m = c.get("/manifest.webmanifest").json()
        assert m["share_target"]["action"] == "/share-target" and m["display"] == "standalone"
        assert "pixagent-" in c.get("/sw.js").text
        html = c.get("/").text
        assert "{{V}}" not in html and "apple-touch-icon" in html
        r = c.post("/share-target", data={"text": "nota"}, follow_redirects=False,
                   files=[("files", ("galeria.jpg", open(settings.ws / "uploads" / "foto1.jpg", "rb"), "image/jpeg"))])
        assert r.status_code == 303
        assert (settings.ws / "inbox" / "galeria.jpg").exists()
        assert any(p.name.startswith("compartido_") for p in (settings.ws / "inbox").iterdir())


def test_event_hub_coalesces_and_replays():
    import asyncio
    from pixagent.web.server import EventHub

    async def main():
        hub = EventHub()
        hub.loop = asyncio.get_running_loop()
        q = asyncio.Queue()
        hub.queues["c"] = q
        for ch in "Hola mundo":
            hub.publish({"type": "text_delta", "session": "s", "text": ch})
        hub.publish({"type": "tool_start", "session": "s", "id": "1", "name": "x"})
        got = [q.get_nowait() for _ in range(q.qsize())]
        assert [e["type"] for e in got] == ["text_delta", "tool_start"]  # 10 fragmentos -> 1 mensaje
        assert got[0]["text"] == "Hola mundo" and got[1]["seq"] == got[0]["seq"] + 1
        assert [e["seq"] for e in hub.since(got[0]["seq"])] == [got[1]["seq"]]
        hub.publish({"type": "text_delta", "session": "s", "text": "x"})
        await asyncio.sleep(0.1)  # el temporizador vacía el búfer
        assert q.get_nowait()["text"] == "x"
    asyncio.run(main())


def test_server_idle_does_not_load_heavy_modules():
    import subprocess
    import sys
    code = ("import sys; from pixagent.web.server import create_app; "
            "heavy=[m for m in ('anthropic','matplotlib','pymupdf','reportlab','playwright') if m in sys.modules]; "
            "print(heavy)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(__import__('pathlib').Path(__file__).parents[1]))
    assert out.stdout.strip() == "[]", out.stdout + out.stderr
