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


# ----------------------------------------------------------------- informes estructurados / extensos
class FakeWriter:
    """Redactor simulado: devuelve texto de la longitud pedida y registra las llamadas."""

    def __init__(self):
        import threading
        self.calls = []
        self.lock = threading.Lock()

    def write(self, system, content, max_tokens):
        prompt = content[-1]["text"]
        with self.lock:
            self.calls.append({"system": system, "n_images": sum(1 for b in content if b["type"] == "image"),
                               "prompt": prompt})
        if "índice" in system.lower():
            import re as _re
            per = int(_re.search(r"~(\d+) palabras", prompt).group(1)) // 40
            chapters = [{"title": f"Capítulo {c}", "sections": [
                {"title": f"Apartado {c}.{s}", "brief": "Cubre el tema.", "words": per, "photos": [1] if c == 1 and s == 1 else []}
                for s in range(1, 5)]} for c in range(1, 11)]
            return json.dumps({"chapters": chapters}), {"input": 100, "output": 50}
        import re as _re
        words = int(_re.search(r"~(\d+) palabras", prompt).group(1))
        para = ("Texto técnico de prueba con ñ y acentos sobre la inspección realizada. " * 12).strip()
        body = "\n\n".join([para] * max(1, words // 120)) + "\n\n| Foto | Hallazgo |\n|---|---|\n| 1 | Fisura |"
        return body, {"input": 1000, "output": words * 2}


def _photos(settings, n, groups=("Fachada", "Cocina")):
    out = []
    for i in range(n):
        p = settings.ws / "uploads" / f"r{i}.jpg"
        Image.new("RGB", (1600, 1200), (40 * i % 255, 120, 200)).save(p)
        out.append({"path": f"uploads/r{i}.jpg", "caption": f"Vista {i + 1}", "group": groups[i % len(groups)]})
    return out


def test_report_template_pipeline(settings):
    from pixagent.reports.engine import ReportGenerator, ReportProject, Templates, build_report_pdf
    from pixagent.web.thumbs import pdf_page_count
    T = Templates(settings.ws)
    assert {"inspeccion-tecnica", "avance-obra", "informe-extenso"} <= {t["id"] for t in T.list()}
    tpl = T.get("inspeccion-tecnica")
    p = ReportProject.create(settings.ws, tpl, "Inspección Vivienda Pérez",
                             {"proyecto": "Vivienda Pérez", "inspector": "Ing. Max", "fecha": "2026-11-07"},
                             "Fisuras en fachada y humedad en cocina.", _photos(settings, 6))
    units = p.units()
    per_group = [u for u in units if u.kind == "per_group"]
    assert [u.title for u in per_group] == ["Fachada", "Cocina"] and all(len(u.photos) == 3 for u in per_group)
    est = p.estimate()
    assert est["calls"] == 7 and est["usd"] > 0
    w = FakeWriter()
    events = []
    res = ReportGenerator(settings, p, writer=w, emit=events.append).run()
    assert res["errors"] == 0 and len(w.calls) == 7
    # cada zona solo recibe SUS fotos; el resumen ('*') se escribe al final con contexto de las demás
    assert sorted(c["n_images"] for c in w.calls if "Parte:" in c["prompt"]) == [3, 3]
    assert "RESÚMENES DE OTRAS SECCIONES" in w.calls[-1]["prompt"] and "Resumen ejecutivo" in w.calls[-1]["prompt"]
    # reanudable: una segunda ejecución no vuelve a llamar al modelo
    ReportGenerator(settings, p, writer=w).run()
    assert len(w.calls) == 7
    out = build_report_pdf(settings, p)
    assert out.exists() and pdf_page_count(out) >= 6
    md = (p.dir / "informe.md").read_text("utf-8")
    assert "# Hallazgos por zona" in md and "## Fachada" in md and ":::photos" in md and "Ing. Max" in md


def test_long_report_100_pages(settings):
    """Plantilla de estructura automática: índice + 40 apartados en paralelo → ~100 páginas."""
    import time as _t
    from pixagent.reports.engine import ReportGenerator, ReportProject, Templates, build_report_pdf
    from pixagent.web.thumbs import pdf_page_count
    tpl = Templates(settings.ws).get("informe-extenso")
    p = ReportProject.create(settings.ws, tpl, "Memoria descriptiva extensa", {"autor": "Max"},
                             "Proyecto de edificio de 5 pisos.", _photos(settings, 4), target_pages=100)
    assert p.status()["needs_outline"]
    w = FakeWriter()
    t0 = _t.time()
    res = ReportGenerator(settings, p, writer=w, workers=4).run()
    assert res["errors"] == 0 and len(w.calls) == 41      # 1 índice + 40 apartados
    out = build_report_pdf(settings, p)
    pages = pdf_page_count(out)
    assert pages >= 90, pages
    assert out.stat().st_size < 15_000_000
    assert _t.time() - t0 < 120


def test_report_api_and_tool(settings):
    from fastapi.testclient import TestClient
    from pixagent.web.server import create_app
    from pixagent.tools import REGISTRY, ToolContext
    app = create_app(settings, llm_factory=lambda s: FakeLLM([]), report_writer_factory=lambda s, p: FakeWriter())
    photos = _photos(settings, 2)
    with TestClient(app) as c:
        assert any(t["id"] == "avance-obra" for t in c.get("/api/report-templates").json())
        r = c.post("/api/report-templates", json={"name": "Mi plantilla", "sections": [
            {"id": "a", "title": "Intro", "kind": "ai", "instructions": "x", "words": 150},
            {"id": "f", "title": "Fotos", "kind": "photo_grid"}]}).json()
        assert r["ok"] and r["template"]["id"] == "mi-plantilla"
        assert c.post("/api/report-templates", json={"name": "Mala", "sections": [{"kind": "nada"}]}).status_code == 400
        rep = c.post("/api/reports", json={"template_id": "mi-plantilla", "title": "Prueba", "photos": photos}).json()["report"]
        rid = rep["id"]
        assert rep["estimate"]["calls"] == 1
        assert c.post(f"/api/reports/{rid}/generate", json={}).json()["ok"]
        import time as _t
        for _ in range(50):
            if c.get(f"/api/reports/{rid}").json()["units"][0]["status"] == "done":
                break
            _t.sleep(0.1)
        assert c.put(f"/api/reports/{rid}/sections/a", json={"markdown": "Editado a mano."}).json()["ok"]
        assert c.get(f"/api/reports/{rid}/sections/a").json()["markdown"] == "Editado a mano."
        b = c.post(f"/api/reports/{rid}/build").json()
        assert b["ok"] and b["pages"] >= 2
        assert c.get("/api/reports").json()[0]["id"] == rid
    ctx = ToolContext(settings=settings)
    assert "inspeccion-tecnica" in REGISTRY["report_builder"].func(ctx, action="templates").text
    r = REGISTRY["report_builder"].func(ctx, action="create", template_id="avance-obra", title="Avance 1", photos=photos)
    assert "Estimación" in r.text


def test_photo_panel_and_miniapp_api(settings):
    from fastapi.testclient import TestClient
    from pixagent.web.server import create_app
    from pixagent.web.thumbs import pdf_page_count
    photos = _photos(settings, 7)
    app = create_app(settings, llm_factory=lambda s: FakeLLM([]))
    with TestClient(app) as c:
        r = c.post("/api/photo-panel", json={"title": "Panel", "fields": {"Proyecto": "X"}, "layout": "2x3",
                                              "photos": [{"path": p["path"], "caption": p["caption"]} for p in photos]}).json()
        assert r["ok"] and r["pages"] == 2 and pdf_page_count(settings.ws / r["path"]) == 2
        s = c.post("/api/files/save", data={"folder": "graderio"}, files={"file": ("d.json", b"{}", "application/json")}).json()
        assert s["path"] == "outputs/graderio/d.json"
        assert c.get("/api/files/list?folder=outputs/graderio").json()["files"][0]["path"] == s["path"]
        assert isinstance(c.get("/api/apps").json(), list)
        assert c.get("/static/pixagent-sdk.js").status_code == 200


# ----------------------------------------------------------------- mejoras del harness
def test_undo_loop_detection_and_memory(settings):
    from pixagent.agent import Agent
    from pixagent.tools import REGISTRY
    (settings.ws / "outputs" / "nota.txt").write_text("original", "utf-8")
    llm = FakeLLM([
        ([tu("1", "edit_file", {"path": "outputs/nota.txt", "old_string": "original", "new_string": "cambiado"}),
          tu("2", "write_file", {"path": "outputs/nuevo.txt", "content": "x"})], "tool_use"),
        ([txt("hecho")], "end_turn"),
        ([tu("a", "list_files", {"pattern": "*.zz"}), tu("b", "list_files", {"pattern": "*.zz"}),
          tu("c", "list_files", {"pattern": "*.zz"})], "tool_use"),
        ([txt("ok")], "end_turn"),
    ])
    a = Agent(settings, llm=llm)
    a.run("edita")
    assert (settings.ws / "outputs" / "nota.txt").read_text("utf-8") == "cambiado"
    restored = a.undo_last_turn()
    assert len(restored) == 2
    assert (settings.ws / "outputs" / "nota.txt").read_text("utf-8") == "original"
    assert not (settings.ws / "outputs" / "nuevo.txt").exists()
    a.run("lista")  # el próximo mensaje informa al modelo del deshacer
    assert "deshizo" in a.messages[-4]["content"][-1]["text"]
    third = a.messages[-2]["content"][2]
    assert third.get("is_error") and "misma llamada" in third["content"][0]["text"]
    # memoria del proyecto
    from pixagent.tools import ToolContext
    ctx = ToolContext(settings=settings)
    REGISTRY["remember"].func(ctx, note="Los informes llevan el logo de Constructora Max", section="Empresa")
    assert "Constructora Max" in (settings.ws / "PIXAGENT.md").read_text("utf-8")
    from pixagent.llm import ClaudeLLM
    llm2 = ClaudeLLM(settings, client=object())
    Agent(settings, llm=llm2)
    p = llm2._params([], [])
    assert "Constructora Max" in p["system"][1]["text"]
    assert p["context_management"]["edits"][0]["type"] == "clear_tool_uses_20250919"
    assert "context-management-2025-06-27" in p["betas"]


def test_edit_file_tolerant_and_closest_hint(ctx):
    from pixagent.tools import REGISTRY, ToolError
    REGISTRY["write_file"].func(ctx, path="outputs/c.py", content="def f():   \r\n    return 1\r\n")
    r = REGISTRY["edit_file"].func(ctx, path="outputs/c.py", old_string="def f():\n    return 1", new_string="def f():\n    return 2")
    assert "ignorando" in r.text and "return 2" in (ctx.ws / "outputs" / "c.py").read_text("utf-8")
    with pytest.raises(ToolError) as e:
        REGISTRY["edit_file"].func(ctx, path="outputs/c.py", old_string="def g():\n  pass", new_string="")
    assert "línea 1" in str(e.value)


def test_long_shell_output_saved_to_file(ctx):
    from pixagent.tools import REGISTRY
    r = REGISTRY["run_python"].func(ctx, code="for i in range(5000): print('línea', i)")
    assert "Salida completa" in r.text and len(r.text) < 14000


def test_report_evidence_check_and_cells(settings, ctx):
    from pixagent.reports.engine import ReportProject, Templates, check_evidence
    from pixagent.tools import REGISTRY
    tpl = {"id": "t", "name": "T", "sections": [{"id": "a", "title": "A", "kind": "ai", "words": 100}]}
    p = ReportProject.create(settings.ws, tpl, "X", photos=_photos(settings, 3))
    p.section_file("a").write_text("Se ve en la Foto 1 y la Foto 7. [POR COMPLETAR: fecha]", "utf-8")
    w = " | ".join(check_evidence(p))
    assert "Foto 7" in w and "Foto 2, Foto 3" in w and "POR COMPLETAR" in w
    r = REGISTRY["view_image"].func(ctx, path="uploads/plano.png", cells=True)
    assert "Columnas x: A=0–100" in r.text and r.images


# ----------------------------------------------------------------- IA local (servidor compatible OpenAI simulado)
@pytest.fixture()
def fake_openai_server():
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    calls = []

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj):
            b = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

        def do_GET(self):
            self._send({"data": [{"id": "qwen3.5-4b-q4"}]})

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            calls.append(body)
            content = body["messages"][-1]["content"]
            n_img = sum(1 for c in content if isinstance(c, dict) and c.get("type") == "image_url") if isinstance(content, list) else 0
            text = '{"ok": true}' if body.get("response_format") else f"<think>x</think>Descripción con {n_img} imagen(es)."
            self._send({"choices": [{"message": {"content": text}}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}})

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", calls
    srv.shutdown()


def test_local_ai_engine_tasks_and_video(settings, fake_openai_server):
    import subprocess
    from pixagent.local import catalog
    from pixagent.local.service import LocalAI, ffmpeg_exe
    url, calls = fake_openai_server
    settings.local_engines = [{"name": "Prueba", "url": url, "kind": "openai"}]
    svc = LocalAI(settings)
    st = svc.status(refresh=True)
    assert any(e["name"] == "Prueba" and e["online"] for e in st["engines"])
    assert st["assigned"]["vision"] == ("Prueba", "qwen3.5-4b-q4")
    r = svc.run("caption", images=[settings.ws / "uploads" / "foto1.jpg"])
    assert r["text"] == "Descripción con 1 imagen(es)."          # <think> eliminado
    assert calls[-1]["messages"][-1]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert svc.run("ask", "x", [settings.ws / "uploads" / "foto1.jpg"], json_mode=True)["data"] == {"ok": True}
    assert catalog.score("glm-ocr:q8_0", "ocr") > catalog.score("qwen3.5:4b", "ocr")
    assert catalog.score("glm-ocr:q8_0", "vision") == 0
    if not ffmpeg_exe():
        pytest.skip("sin ffmpeg")
    vid = settings.ws / "uploads" / "v.mp4"
    subprocess.run([ffmpeg_exe(), "-loglevel", "error", "-y", "-f", "lavfi", "-i", "color=c=red:s=320x240:d=3",
                    "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=3", "-filter_complex", "[0:v][1:v]concat=n=2:v=1",
                    str(vid)], check=True)
    job = svc.start_video({"source": "uploads/v.mp4", "every": 1, "max_frames": 6, "summary": False}, lambda e: None)
    job.thread.join(60)
    assert job.status == "done" and len(job.items) == 6
    described = [it for it in job.items if not it.get("same")]
    assert len(described) == 2          # rojo y azul; los fotogramas idénticos no llaman al modelo
    assert (settings.ws / "outputs" / "video" / job.id / "analisis.md").exists()


# ----------------------------------------------------------------- preguntas al usuario y clave de API
def test_ask_user_tool_and_web_flow(settings):
    from fastapi.testclient import TestClient
    from pixagent.web.server import create_app
    script = [([txt("Necesito saber el formato."),
                tu("q1", "ask_user", {"question": "¿En qué formato lo quieres?",
                                      "options": [{"label": "Mini app (recomendado)"}, {"label": "PDF"}]})], "tool_use"),
              ([txt("Perfecto, haré un PDF.")], "end_turn")]
    llm = FakeLLM(script)
    app = create_app(settings, llm_factory=lambda s: llm)
    with TestClient(app) as c:
        with c.websocket_connect("/ws") as ws:
            ws.send_json({"type": "chat", "text": "hazme algo para escaleras", "client": "x"})
            q = None
            for _ in range(60):
                ev = ws.receive_json()
                if ev["type"] == "question":
                    q = ev
                    break
            assert q and q["options"][0]["label"].startswith("Mini app")
            # escribir en el chat mientras hay pregunta pendiente = responder
            ws.send_json({"type": "chat", "session": q["session"], "text": "PDF"})
            types = []
            for _ in range(60):
                ev = ws.receive_json()
                types.append(ev["type"])
                if ev["type"] == "done":
                    break
            assert "answer" in types and "question_resolved" in types
        res = llm.calls[-1]["content"][0]
        assert res["tool_use_id"] == "q1" and "Respuesta del usuario: PDF" in res["content"][0]["text"]
        tr = c.get(f"/api/sessions/{q['session']}").json()["transcript"]
        assert any(e["type"] == "question" for e in tr) and any(e["type"] == "answer" for e in tr)


def test_api_key_settings(settings, monkeypatch):
    from fastapi.testclient import TestClient
    from pixagent import anthropic_client
    from pixagent.web.server import create_app
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(anthropic_client, "verify_key", lambda k: (k.endswith("buena"), "La clave no es válida."))
    app = create_app(settings, llm_factory=lambda s: FakeLLM([]))
    with TestClient(app) as c:
        assert c.get("/api/status").json()["api_key"]["configured"] is False
        assert c.post("/api/apikey", json={"key": "hola"}).status_code == 400
        r = c.post("/api/apikey", json={"key": "sk-ant-api03-" + "x" * 30 + "mala"})
        assert r.status_code == 400 and "no es válida" in r.json()["error"]
        r = c.post("/api/apikey", json={"key": "sk-ant-api03-" + "x" * 30 + "buena"}).json()
        assert r["ok"] and r["source"] == "ajustes" and "xxxx" not in r["masked"][10:-4]
        st = c.get("/api/status").json()
        assert st["api_key"]["configured"] and "sk-ant-api03-" + "x" * 30 not in json.dumps(st)
        assert settings.anthropic_api_key.endswith("buena")
        assert c.delete("/api/apikey").json()["configured"] is False
