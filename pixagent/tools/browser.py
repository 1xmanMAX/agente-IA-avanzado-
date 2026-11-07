"""Navegador sin interfaz: capturas de páginas/mini apps y HTML -> PDF.

Usa Playwright si está instalado; si no, recurre a Chrome/Edge en modo --headless (Edge viene con
Windows, así que normalmente funciona sin instalar nada).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from .base import ToolContext, ToolError, ToolResult, tool

BROWSER_CANDIDATES = [
    os.environ.get("PIXAGENT_CHROMIUM", ""),
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "/opt/pw-browsers/chromium",
]


def find_browser() -> str | None:
    for c in BROWSER_CANDIDATES:
        if c and Path(c).exists():
            p = Path(c)
            if p.is_dir():  # carpeta de playwright
                for exe in p.rglob("chrome"):
                    if exe.is_file() and os.access(exe, os.X_OK):
                        return str(exe)
                continue
            return c
    for name in ("msedge", "google-chrome", "chromium", "chromium-browser", "chrome"):
        w = shutil.which(name)
        if w:
            return w
    return None


def _sandbox_flags() -> list[str]:
    # Chrome se niega a arrancar como root en Linux sin --no-sandbox
    return ["--no-sandbox"] if hasattr(os, "geteuid") and os.geteuid() == 0 else []


def _target_url(ctx: ToolContext, target: str) -> str:
    if target.startswith(("http://", "https://", "file://", "data:")):
        return target
    return ctx.resolve(target, must_exist=True).as_uri()


def screenshot(url: str, out: Path, width=1280, height=800, full_page=True, wait_ms=800) -> None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            kw = {}
            exe = os.environ.get("PIXAGENT_CHROMIUM")
            if exe:
                kw["executable_path"] = exe
            try:
                b = p.chromium.launch(**kw)
            except Exception:  # noqa: BLE001
                exe = find_browser()
                if not exe:
                    raise
                b = p.chromium.launch(executable_path=exe)
            page = b.new_page(viewport={"width": width, "height": height}, device_scale_factor=1)
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(wait_ms)
            page.screenshot(path=str(out), full_page=full_page)
            b.close()
            return
    except ImportError:
        pass
    exe = find_browser()
    if not exe:
        raise ToolError("No hay Playwright ni Chrome/Edge disponibles. Instala: pip install playwright && playwright install chromium")
    subprocess.run([exe, "--headless=new", "--disable-gpu", *_sandbox_flags(), "--hide-scrollbars", f"--window-size={width},{height}",
                    f"--virtual-time-budget={max(wait_ms, 1500)}", f"--screenshot={out}", url],
                   capture_output=True, timeout=90)
    if not out.exists():
        raise ToolError("El navegador no generó la captura.")


def print_pdf(url: str, out: Path, landscape=False, page_format="A4") -> None:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            exe = os.environ.get("PIXAGENT_CHROMIUM")
            try:
                b = p.chromium.launch(**({"executable_path": exe} if exe else {}))
            except Exception:  # noqa: BLE001
                b = p.chromium.launch(executable_path=find_browser())
            page = b.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(500)
            page.pdf(path=str(out), format=page_format, landscape=landscape, print_background=True,
                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
            b.close()
            return
    except ImportError:
        pass
    exe = find_browser()
    if not exe:
        raise ToolError("No hay Playwright ni Chrome/Edge para convertir HTML a PDF.")
    subprocess.run([exe, "--headless=new", "--disable-gpu", *_sandbox_flags(), "--no-pdf-header-footer",
                    f"--print-to-pdf={out}", url], capture_output=True, timeout=120)
    if not out.exists():
        raise ToolError("El navegador no generó el PDF.")


@tool("preview_page",
      """Abre un HTML local (mini app, informe HTML, diagrama Mermaid) o una URL en un navegador sin
      interfaz y te devuelve una CAPTURA para que verifiques visualmente cómo se ve. Úsalo siempre
      después de crear o modificar una mini app. También sirve para exportar a PNG.""",
      {"properties": {
          "target": {"type": "string", "description": "Ruta .html en el workspace o URL."},
          "output": {"type": "string", "description": "PNG de salida (opcional)."},
          "width": {"type": "integer"}, "height": {"type": "integer"},
          "full_page": {"type": "boolean"}},
       "required": ["target"]})
def preview_page(ctx: ToolContext, target: str, output: str | None = None, width: int = 1280,
                 height: int = 800, full_page: bool = True) -> ToolResult:
    url = _target_url(ctx, target)
    if output:
        out = ctx.resolve(output)
    elif not target.startswith(("http://", "https://")):
        out = ctx.resolve(target).with_suffix(".preview.png")
    else:
        out = ctx.ws / ".tmp" / "preview.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    screenshot(url, out, width, height, full_page)
    return ToolResult(f"Captura de {target}: {ctx.rel(out)}", images=[out], files=[out])


@tool("html_to_pdf",
      """Convierte un HTML (con CSS completo: grids, colores, @page, saltos de página) en PDF usando el
      motor del navegador. Ideal para informes con diseño muy cuidado, fichas, catálogos o
      presentaciones imprimibles. Escribe primero el HTML con write_file.""",
      {"properties": {
          "html_path": {"type": "string"},
          "output": {"type": "string"},
          "landscape": {"type": "boolean"},
          "format": {"type": "string", "enum": ["A4", "Letter", "A3"]}},
       "required": ["html_path", "output"]})
def html_to_pdf(ctx: ToolContext, html_path: str, output: str, landscape: bool = False,
                format: str = "A4") -> ToolResult:
    url = _target_url(ctx, html_path)
    out = ctx.resolve(output)
    out.parent.mkdir(parents=True, exist_ok=True)
    print_pdf(url, out, landscape, format)
    return ToolResult(f"PDF creado: {ctx.rel(out)}. Revísalo con pdf_tools(action='to_images').", files=[out])
