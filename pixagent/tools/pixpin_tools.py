"""Herramientas de integración con PixPin y creación de mini apps."""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

from .. import pixpin_bridge as PB
from .base import ToolContext, ToolError, ToolResult, guess_kind, tool


def _to_pinnable(ctx: ToolContext, p: Path) -> list[Path]:
    """PixPin fija imágenes: convierte HTML/PDF en PNG antes de enviarlos."""
    kind = guess_kind(p)
    if kind == "image" and p.suffix.lower() != ".svg":
        return [p]
    if kind == "html":
        from .browser import screenshot
        out = p.with_suffix(".pin.png")
        screenshot(p.as_uri(), out, 1100, 760, full_page=False)
        return [out]
    if kind == "pdf":
        import pymupdf as fitz
        doc = fitz.open(p)
        outs = []
        for i in range(min(doc.page_count, 4)):
            o = p.with_name(f"{p.stem}_p{i + 1}.pin.png")
            doc[i].get_pixmap(dpi=100).save(o)
            outs.append(o)
        return outs
    raise ToolError(f"No puedo fijar {p.name} en PixPin (tipo {kind}).")


@tool("pixpin",
      """Integración directa con PixPin (la app de capturas/pines del usuario):
      - pin: fija en pantalla imágenes, planos, diagramas; HTML y PDF se convierten a imagen antes.
      - capture: pide a PixPin una captura (region: last = última zona capturada, window = ventana
        activa, screen = pantalla bajo el ratón, all = todas) y te la muestra.
      - run_script: ejecuta JavaScript de PixPin (API 'pixpin.*'; sin async/fetch/require).
      - install_scripts: genera los scripts para que el usuario envíe capturas desde PixPin al agente.""",
      {"properties": {
          "action": {"type": "string", "enum": ["pin", "capture", "run_script", "install_scripts"]},
          "files": {"type": "array", "items": {"type": "string"}},
          "region": {"type": "string", "enum": ["last", "window", "screen", "all", "under_mouse"]},
          "script": {"type": "string"}},
       "required": ["action"]},
      needs_approval=lambda s: s.permission_mode == "ask")
def pixpin(ctx: ToolContext, action: str, files: list | None = None, region: str = "last",
           script: str | None = None) -> ToolResult:
    s = ctx.settings
    tmp = ctx.ws / ".tmp"
    if action == "install_scripts":
        return install_scripts(ctx)
    try:
        if action == "pin":
            if not files:
                raise ToolError("pin necesita 'files'.")
            pinnable = []
            for f in files:
                pinnable += _to_pinnable(ctx, ctx.resolve(f, must_exist=True))
            PB.pin_files(pinnable, exe=s.pixpin_path, keep_dir=tmp)
            return ToolResult("Enviado a PixPin para fijar: " + ", ".join(ctx.rel(p) for p in pinnable),
                              data={"pinned": [ctx.rel(p) for p in pinnable]})
        if action == "capture":
            target = ctx.ws / "inbox" / f"agente_{datetime.now():%Y%m%d_%H%M%S}.png"
            got = PB.capture(target, region, exe=s.pixpin_path, keep_dir=tmp)
            if not got:
                raise ToolError("PixPin no guardó la captura a tiempo (¿está abierto? ¿hay una captura previa para 'last'?).")
            return ToolResult(f"Captura de PixPin: {ctx.rel(got)}", images=[got], files=[got])
        if action == "run_script":
            if not script:
                raise ToolError("run_script necesita 'script'.")
            if "?." in script or re.search(r"\b(async|await|require|fetch|setTimeout)\b", script):
                raise ToolError("El motor de PixPin no admite ?., async/await, require, fetch ni setTimeout.")
            sp = PB.run_script(script, exe=s.pixpin_path, keep_dir=tmp)
            return ToolResult(f"Script enviado a PixPin ({ctx.rel(sp)}). PixPin no devuelve resultado.")
    except PB.PixPinNotFound as e:
        raise ToolError(str(e) + " (Si estás probando en otro equipo, entrega los archivos sin fijarlos.)")
    raise ToolError(f"Acción desconocida: {action}")


def install_scripts(ctx: ToolContext) -> ToolResult:
    d = ctx.ws / "pixpin_scripts"
    d.mkdir(exist_ok=True)
    files = []
    st = ctx.settings
    token = st.access_token if st.require_token else ""
    for name, code in PB.generate_user_scripts(ctx.ws, st.port, token, "https" if st.ssl_certfile else "http").items():
        f = d / name
        f.write_text(code, encoding="utf-8-sig")
        files.append(f)
    guide = d / "LEEME.txt"
    guide.write_text(INSTALL_GUIDE.format(dir=d), encoding="utf-8")
    files.append(guide)
    return ToolResult("Scripts de integración generados en " + ctx.rel(d) + ":\n" +
                      "\n".join(ctx.rel(f) for f in files), files=files)


INSTALL_GUIDE = """Integración PixPin -> PixAgent
================================
Carpeta: {dir}

1. Abre PixPin -> Configuración -> Script (o "Acciones personalizadas").
2. Crea una acción por cada archivo .js de esta carpeta (copia su contenido) y asígnale un atajo:
   - 01_enviar_ultima_captura.js : tras capturar con PixPin, envía esa zona al agente.
   - 02_enviar_ventana_activa.js : envía la ventana activa.
   - 03_enviar_portapapeles.js   : copia una captura (Ctrl+C en PixPin) y envíala.
   - 04_abrir_agente.js          : abre la interfaz avanzada de IA.
   - 05_enviar_pantalla.js       : envía la pantalla completa bajo el ratón.
3. También puedes ejecutarlos desde la línea de comandos:
   PixPin.exe -f "{dir}/01_enviar_ultima_captura.js"

Las capturas llegan a la carpeta inbox del workspace y aparecen en la interfaz web del agente.
Las mini apps creadas por el agente generan su propio script en apps/<nombre>/abrir_en_pixpin.js
para que las abras con un atajo de PixPin.
"""


@tool("create_miniapp",
      """Crea una MINI APP / mini funcionalidad integrada con PixPin:
      - kind='web': app HTML/CSS/JS autocontenida (calculadoras, conversores, checklists, visores,
        editores, dashboards...). Entry por defecto index.html. Puede usar librerías por CDN
        (cdnjs/jsdelivr) pero mejor que funcione offline.
      - kind='python': script con interfaz (tkinter) o utilidad que procesa el portapapeles o la bandeja
        inbox (p. ej. quitar fondo, OCR, redimensionar, generar PDF de capturas).
      Se guarda en apps/<name>/ con manifest.json y un script 'abrir_en_pixpin.js' para lanzarla desde
      PixPin con un atajo. Después de crearla, verifica con preview_page (web) o run_python (python).""",
      {"properties": {
          "name": {"type": "string", "description": "Nombre corto (se usa como carpeta)."},
          "kind": {"type": "string", "enum": ["web", "python"]},
          "description": {"type": "string"},
          "files": {"type": "object", "description": "{ruta_relativa: contenido} p.ej. {'index.html': '...'}"},
          "entry": {"type": "string"},
          "pin_preview": {"type": "boolean", "description": "Fijar una captura de la app en PixPin."}},
       "required": ["name", "kind", "files"]})
def create_miniapp(ctx: ToolContext, name: str, kind: str, files: dict, description: str = "",
                   entry: str | None = None, pin_preview: bool = False) -> ToolResult:
    import unicodedata
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", ascii_name.strip().lower()).strip("_") or f"app_{int(time.time())}"
    root = ctx.resolve(f"apps/{slug}")
    root.mkdir(parents=True, exist_ok=True)
    written = []
    for rel, content in files.items():
        p = (root / rel).resolve()
        if root not in p.parents and p != root:
            raise ToolError(f"Ruta inválida en files: {rel}")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, "utf-8")
        written.append(p)
    entry = entry or ("index.html" if kind == "web" else next((k for k in files if k.endswith(".py")), "main.py"))
    entry_path = root / entry
    if not entry_path.exists():
        raise ToolError(f"No existe el entry {entry} entre los archivos.")
    manifest = {"name": name, "slug": slug, "kind": kind, "entry": entry, "description": description,
                "created": datetime.now().isoformat(timespec="seconds")}
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False), "utf-8")
    launcher = root / "abrir_en_pixpin.js"
    launcher.write_text(PB.launcher_script_for_app(entry_path, kind), encoding="utf-8-sig")
    written += [root / "manifest.json", launcher]
    msg = (f"Mini app '{name}' creada en {ctx.rel(root)} (entry {entry}).\n"
           f"Lanzador PixPin: {ctx.rel(launcher)} (asígnale un atajo en PixPin -> Script).")
    images = []
    if kind == "web":
        try:
            from .browser import screenshot
            shot = root / "preview.png"
            screenshot(entry_path.as_uri(), shot, 1100, 760, full_page=False)
            images.append(shot)
            written.append(shot)
            msg += f"\nCaptura de verificación: {ctx.rel(shot)}"
            if pin_preview:
                try:
                    PB.pin_files([shot], exe=ctx.settings.pixpin_path, keep_dir=ctx.ws / ".tmp")
                    msg += "\nCaptura fijada en PixPin."
                except PB.PixPinNotFound as e:
                    msg += f"\n(No se fijó en PixPin: {e})"
        except Exception as e:  # noqa: BLE001
            msg += f"\n(No se pudo generar la captura automática: {e}. Usa preview_page.)"
    return ToolResult(msg, images=images, files=written, data={"app": manifest})
