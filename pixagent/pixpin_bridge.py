"""Puente con PixPin usando su API oficial de scripts.

PixPin ejecuta JavaScript con:  PixPin.exe -f script.js   (o -r "código")
y la instancia que ya está abierta recibe el script. API usada (docs: pixpin.com/docs/configuration/script):
  pixpin.pinFromFiles([rutas])                 -> fija imágenes en pantalla
  pixpin.pinFromClipBoard()                    -> fija el portapapeles
  pixpin.directScreenShotAndSaveTo(rect, ruta) -> captura sin selección y guarda
  pixpin.getSpRect(PixConst.SpRectLastShotRect | SpRectActiveWindow | SpRectAllScreen ...)
  pixpin.runSystem("programa args")            -> lanza un programa (para llamar al agente desde PixPin)

Dirección AGENTE -> PIXPIN: este módulo genera un .js temporal y lo ejecuta.
Dirección PIXPIN -> AGENTE: los scripts de pixpin_scripts/ (se instalan como acciones/atajos en PixPin)
guardan capturas en <workspace>/inbox o llaman a `pixagent send-clipboard`; el servidor del agente
vigila la bandeja de entrada y muestra las capturas en la interfaz.
"""
from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path


class PixPinNotFound(RuntimeError):
    pass


def candidates() -> list[Path]:
    c = []
    if os.environ.get("PIXPIN_PATH"):
        c.append(Path(os.environ["PIXPIN_PATH"]))
    if platform.system() == "Windows":
        for base in filter(None, [os.environ.get("LOCALAPPDATA"), os.environ.get("ProgramFiles"),
                                  os.environ.get("ProgramFiles(x86)"), "D:/Apps", "D:/Program Files"]):
            c += [Path(base) / "PixPin" / "PixPin.exe", Path(base) / "Programs" / "PixPin" / "PixPin.exe"]
    elif platform.system() == "Darwin":
        c += [Path("/Applications/PixPin.app/Contents/MacOS/PixPin"),
              Path.home() / "Applications/PixPin.app/Contents/MacOS/PixPin"]
    w = shutil.which("PixPin") or shutil.which("pixpin")
    if w:
        c.append(Path(w))
    return c


def find_pixpin(configured: str = "") -> Path:
    for p in ([Path(configured)] if configured else []) + candidates():
        if p and p.exists():
            return p
    raise PixPinNotFound(
        "No encontré PixPin. Indica la ruta en la configuración (pixpin_path) o en la variable "
        "de entorno PIXPIN_PATH, p. ej. C:/Program Files/PixPin/PixPin.exe")


def js_str(s: str | Path) -> str:
    """Literal JS seguro; PixPin acepta barras '/' también en Windows."""
    return json.dumps(str(s).replace("\\", "/"), ensure_ascii=False)


def run_script(js: str, *, exe: str = "", keep_dir: Path | None = None) -> Path:
    """Escribe el script (UTF-8 con BOM, como recomienda PixPin) y lo envía a la instancia abierta."""
    exe_path = find_pixpin(exe)
    d = keep_dir or Path(os.environ.get("TEMP", "/tmp"))
    d.mkdir(parents=True, exist_ok=True)
    script = d / f"pixagent_{uuid.uuid4().hex[:8]}.js"
    script.write_text(js, encoding="utf-8-sig")
    subprocess.Popen([str(exe_path), "-f", str(script)],
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return script


def pin_files_js(files: list[Path]) -> str:
    arr = ", ".join(js_str(Path(f).resolve()) for f in files)
    return ("(function () {\n"
            f"  var files = [{arr}];\n"
            "  var ok = pixpin.pinFromFiles(files);\n"
            "  if (!ok) { throw new Error('PixAgent: no se pudo fijar ningún archivo'); }\n"
            "})();\n")


def capture_js(target: Path, region: str = "last") -> str:
    const = {"last": "PixConst.SpRectLastShotRect", "window": "PixConst.SpRectActiveWindow",
             "screen": "PixConst.SpRectScreenUnderMouse", "all": "PixConst.SpRectAllScreen",
             "under_mouse": "PixConst.SpRectWindowUnderMouse"}[region]
    return ("(function () {\n"
            f"  var rect = pixpin.getSpRect({const});\n"
            f"  pixpin.directScreenShotAndSaveTo(rect, {js_str(target)});\n"
            "})();\n")


def pin_files(files: list[Path], exe: str = "", keep_dir: Path | None = None) -> Path:
    files = [Path(f) for f in files if Path(f).exists()]
    if not files:
        raise FileNotFoundError("No hay archivos para fijar.")
    return run_script(pin_files_js(files), exe=exe, keep_dir=keep_dir)


def capture(target: Path, region: str = "last", exe: str = "", timeout: float = 8.0,
            keep_dir: Path | None = None) -> Path | None:
    """Pide a PixPin una captura y espera a que aparezca el archivo (la API no devuelve resultado)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    run_script(capture_js(target, region), exe=exe, keep_dir=keep_dir)
    t0 = time.time()
    while time.time() - t0 < timeout:
        hits = sorted(target.parent.glob(target.stem + "*" + target.suffix), key=lambda p: p.stat().st_mtime)
        if hits and hits[-1].stat().st_size > 0:
            time.sleep(0.2)
            return hits[-1]
        time.sleep(0.25)
    return None


# --------------------------------------------------------------------------
# Scripts que el usuario instala en PixPin (Configuración -> Script / atajos de teclado)
def python_launcher() -> str:
    """Ejecutable de Python sin consola en Windows (pythonw) para usar desde runSystem."""
    exe = Path(sys.executable)
    if platform.system() == "Windows":
        w = exe.with_name("pythonw.exe")
        if w.exists():
            return str(w)
    return str(exe)


def generate_user_scripts(ws: Path, port: int, token: str = "", scheme: str = "http") -> dict[str, str]:
    """Genera los scripts de integración PixPin -> agente con las rutas reales de esta máquina."""
    inbox = (ws / "inbox").resolve()
    py = python_launcher()
    url = f"{scheme}://127.0.0.1:{port}/" + (f"?token={token}" if token else "")
    open_cmd = {"Windows": f'cmd /c start "" "{url}"', "Darwin": f"/usr/bin/open {url}"}.get(
        platform.system(), f"xdg-open {url}")

    def run(cmd: str) -> str:
        return f"pixpin.runSystem({js_str(cmd)});"

    send_clip = f'"{py}" -m pixagent send-clipboard'
    return {
        "01_enviar_ultima_captura.js":
            "// PixAgent: re-captura la ÚLTIMA zona seleccionada en PixPin y la envía al agente.\n"
            "(function () {\n"
            "  var rect = pixpin.getSpRect(PixConst.SpRectLastShotRect);\n"
            f"  pixpin.directScreenShotAndSaveTo(rect, {js_str(inbox / 'captura_$yyyy-MM-dd_HH-mm-ss$.png')});\n"
            "})();\n",
        "02_enviar_ventana_activa.js":
            "// PixAgent: captura la ventana activa y la envía al agente.\n"
            "(function () {\n"
            "  var rect = pixpin.getSpRect(PixConst.SpRectActiveWindow);\n"
            f"  pixpin.directScreenShotAndSaveTo(rect, {js_str(inbox / 'ventana_$yyyy-MM-dd_HH-mm-ss$.png')});\n"
            "})();\n",
        "03_enviar_portapapeles.js":
            "// PixAgent: envía al agente la imagen/texto del portapapeles (p. ej. tras copiar una captura).\n"
            f"{run(send_clip)}\n",
        "04_abrir_agente.js":
            "// PixAgent: abre la interfaz avanzada de IA en el navegador.\n"
            f"{run(open_cmd)}\n",
        "05_enviar_pantalla.js":
            "// PixAgent: captura la pantalla bajo el ratón y la envía al agente.\n"
            "(function () {\n"
            "  var rect = pixpin.getSpRect(PixConst.SpRectScreenUnderMouse);\n"
            f"  pixpin.directScreenShotAndSaveTo(rect, {js_str(inbox / 'pantalla_$yyyy-MM-dd_HH-mm-ss$.png')});\n"
            "})();\n",
    }


def launcher_script_for_app(entry: Path, kind: str) -> str:
    """Script de PixPin que abre una mini app (para asignarle un atajo en PixPin)."""
    entry = entry.resolve()
    if kind == "python":
        cmd = f'"{python_launcher()}" "{entry}"'
    elif platform.system() == "Windows":
        # Edge en modo app = ventana propia sin barra de direcciones (sensación de mini app)
        cmd = f'cmd /c start "" msedge --app="{entry.as_uri()}" --window-size=1100,780'
    elif platform.system() == "Darwin":
        cmd = f'/usr/bin/open "{entry}"'
    else:
        cmd = f'xdg-open "{entry}"'
    return f"// Mini app generada por PixAgent: {entry.parent.name}\npixpin.runSystem({js_str(cmd)});\n"
