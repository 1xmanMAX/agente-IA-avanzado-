"""Línea de comandos de PixAgent.

  python -m pixagent                 -> abre la interfaz web (por defecto)
  python -m pixagent serve --lan     -> también para móviles/tablets de tu wifi (QR + token)
  python -m pixagent chat            -> chat en la terminal
  python -m pixagent run "tarea" -a plano.png foto1.jpg
  python -m pixagent send archivo... -> envía archivos a la bandeja del agente
  python -m pixagent send-clipboard  -> envía la imagen/texto del portapapeles (para PixPin)
  python -m pixagent install-pixpin  -> genera los scripts de integración para PixPin
  python -m pixagent config [clave=valor ...]
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from .config import load_settings


def _console_emit(ev: dict) -> None:
    t = ev["type"]
    if t == "text_delta":
        print(ev["text"], end="", flush=True)
    elif t == "assistant":
        print()
    elif t == "tool_start":
        hint = {k: v for k, v in (ev.get("input") or {}).items() if k in ("path", "output", "command", "action", "name", "target")}
        print(f"\n  ⚙ {ev['name']} {json.dumps(hint, ensure_ascii=False) if hint else ''}", flush=True)
    elif t == "tool_end":
        mark = "✗" if ev["is_error"] else "✓"
        first = (ev.get("text") or "").splitlines()[0][:160] if ev.get("text") else ""
        print(f"    {mark} {first}")
        for f in ev.get("files", [])[:6]:
            print(f"      → {f}")
    elif t == "status":
        print(f"  … {ev['text']}")
    elif t == "error":
        print(f"\n  ⚠ {ev['text']}")
    elif t == "todos":
        for td in ev["todos"]:
            print("    " + {"completed": "☑", "in_progress": "▶"}.get(td["status"], "☐") + " " + td["content"])


def _console_approve(name: str, inp: dict) -> bool:
    summary = inp.get("command") or inp.get("code") or inp.get("script") or json.dumps(inp, ensure_ascii=False)
    print(f"\n  ¿Permitir {name}?\n" + "\n".join("    " + l for l in str(summary)[:2000].splitlines()))
    return input("  [s/N] ").strip().lower() in ("s", "si", "sí", "y", "yes")


def _copy_to_inbox(settings, paths: list[Path]) -> list[Path]:
    out = []
    for p in paths:
        dest = settings.ws / "inbox" / f"{datetime.now():%Y%m%d_%H%M%S}_{p.name}"
        shutil.copy2(p, dest)
        out.append(dest)
    return out


def _stage_attachments(settings, files: list[str]) -> list[Path]:
    """Copia adjuntos externos a uploads/ para que las herramientas puedan usarlos."""
    staged = []
    day = settings.ws / "uploads" / datetime.now().strftime("%Y-%m-%d")
    day.mkdir(parents=True, exist_ok=True)
    for f in files:
        p = Path(f).expanduser().resolve()
        if not p.exists():
            print(f"No existe: {p}")
            continue
        try:
            p.relative_to(settings.ws)
            staged.append(p)
        except ValueError:
            dest = day / p.name
            shutil.copy2(p, dest)
            staged.append(dest)
    return staged


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="pixagent", description="Agente de IA avanzado integrado con PixPin")
    ap.add_argument("--workspace", "-w")
    ap.add_argument("--model")
    ap.add_argument("--effort", choices=["low", "medium", "high", "xhigh", "max"])
    sub = ap.add_subparsers(dest="cmd")
    s_serve = sub.add_parser("serve", help="Interfaz web")
    s_serve.add_argument("--port", type=int)
    s_serve.add_argument("--host")
    s_serve.add_argument("--no-browser", action="store_true")
    s_serve.add_argument("--lan", action="store_true",
                         help="Accesible desde móviles/tablets de la misma red (pide token, muestra QR)")
    s_serve.add_argument("--remote", action="store_true",
                         help="Exige token aunque escuche en localhost (para túneles: Tailscale, Cloudflare)")
    s_serve.add_argument("--cert", help="Certificado HTTPS (PEM)")
    s_serve.add_argument("--key", help="Clave privada HTTPS (PEM)")
    s_chat = sub.add_parser("chat", help="Chat en la terminal")
    s_chat.add_argument("--session")
    s_run = sub.add_parser("run", help="Ejecuta una tarea y termina")
    s_run.add_argument("task")
    s_run.add_argument("-a", "--attach", nargs="*", default=[])
    s_send = sub.add_parser("send", help="Envía archivos a la bandeja del agente")
    s_send.add_argument("files", nargs="+")
    sub.add_parser("send-clipboard", help="Envía el portapapeles a la bandeja del agente")
    sub.add_parser("install-pixpin", help="Genera scripts de integración para PixPin")
    s_cfg = sub.add_parser("config", help="Ver o cambiar la configuración")
    s_cfg.add_argument("pairs", nargs="*")
    a = ap.parse_args(argv)

    settings = load_settings(workspace=a.workspace, model=a.model, effort=a.effort)
    cmd = a.cmd or "serve"

    if cmd == "serve":
        from .web.server import serve
        if a.cmd == "serve":
            settings.port = a.port or settings.port
            settings.host = a.host or ("0.0.0.0" if a.lan else settings.host)
            settings.require_token = settings.require_token or a.lan or a.remote
            settings.ssl_certfile = a.cert or settings.ssl_certfile
            settings.ssl_keyfile = a.key or settings.ssl_keyfile
        serve(settings, open_browser=not getattr(a, "no_browser", False))
        return 0

    if cmd in ("chat", "run"):
        from .agent import Agent
        kw = dict(emit=_console_emit, approve=_console_approve)
        agent = Agent.load(settings, a.session, **kw) if cmd == "chat" and a.session else Agent(settings, **kw)
        if cmd == "run":
            agent.run(a.task, _stage_attachments(settings, a.attach))
            print()
            return 0
        print(f"PixAgent · sesión {agent.session_id} · workspace {settings.ws}\n"
              "Escribe tu petición. '/adjuntar ruta1 ruta2' añade archivos al próximo mensaje; '/salir' termina.")
        pending: list[Path] = []
        while True:
            try:
                text = input("\n› ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                break
            if not text:
                continue
            if text in ("/salir", "/exit", "/quit"):
                break
            if text.startswith("/adjuntar"):
                pending += _stage_attachments(settings, text.split()[1:])
                print(f"  {len(pending)} adjunto(s) listos.")
                continue
            agent.run(text, pending)
            pending = []
        return 0

    if cmd == "send":
        for p in _copy_to_inbox(settings, [Path(f) for f in a.files if Path(f).exists()]):
            print(f"Enviado: {p}")
        return 0

    if cmd == "send-clipboard":
        from PIL import ImageGrab
        data = ImageGrab.grabclipboard()
        inbox = settings.ws / "inbox"
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if data is None:
            try:
                import tkinter
                r = tkinter.Tk(); r.withdraw()
                txt = r.clipboard_get(); r.destroy()
                (inbox / f"portapapeles_{stamp}.txt").write_text(txt, "utf-8")
                print("Texto del portapapeles enviado.")
                return 0
            except Exception:  # noqa: BLE001
                print("El portapapeles no contiene imagen ni texto.")
                return 1
        if isinstance(data, list):  # lista de archivos copiados
            for p in _copy_to_inbox(settings, [Path(x) for x in data if Path(x).is_file()]):
                print(f"Enviado: {p}")
            return 0
        out = inbox / f"portapapeles_{stamp}.png"
        data.save(out)
        print(f"Imagen enviada: {out}")
        return 0

    if cmd == "install-pixpin":
        from .agent import Agent
        from .tools.pixpin_tools import install_scripts
        print(install_scripts(Agent(settings, llm=object()).ctx).text)
        return 0

    if cmd == "config":
        if not a.pairs:
            print(json.dumps(asdict(settings), indent=2, ensure_ascii=False))
            return 0
        for pair in a.pairs:
            k, _, v = pair.partition("=")
            if not hasattr(settings, k):
                print(f"Clave desconocida: {k}")
                return 1
            cur = getattr(settings, k)
            if isinstance(cur, bool):
                v = v.lower() in ("1", "true", "yes", "si", "sí")
            elif isinstance(cur, int):
                v = int(v)
            elif isinstance(cur, list):
                v = [x for x in v.split(";") if x]
            setattr(settings, k, v)
        settings.save()
        print("Configuración guardada.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
