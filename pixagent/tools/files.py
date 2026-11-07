"""Herramientas de archivos: leer, escribir, editar, listar y buscar (estilo Claude Code)."""
from __future__ import annotations

import fnmatch
import re

from .base import ToolContext, ToolError, ToolResult, guess_kind, tool, truncate

IGNORED_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", ".sessions", ".tmp"}


@tool("read_file",
      """Lee un archivo de texto del workspace con números de línea. Para imágenes usa view_image;
      para PDFs usa pdf_tools. Usa offset/limit en archivos grandes.""",
      {"properties": {
          "path": {"type": "string", "description": "Ruta relativa al workspace o absoluta permitida."},
          "offset": {"type": "integer", "description": "Línea inicial (1-based)."},
          "limit": {"type": "integer", "description": "Número de líneas (por defecto 2000)."}},
       "required": ["path"]})
def read_file(ctx: ToolContext, path: str, offset: int = 1, limit: int = 2000) -> ToolResult:
    p = ctx.resolve(path, must_exist=True)
    if p.is_dir():
        raise ToolError(f"{ctx.rel(p)} es una carpeta; usa list_files.")
    if guess_kind(p) in ("image", "pdf"):
        raise ToolError("Es un archivo binario; usa view_image o pdf_tools.")
    lines = p.read_text("utf-8", errors="replace").splitlines()
    start = max(1, offset)
    chunk = lines[start - 1:start - 1 + limit]
    body = "\n".join(f"{i:>6}\t{line}" for i, line in enumerate(chunk, start))
    more = f"\n[... {len(lines) - (start - 1 + len(chunk))} líneas más]" if start - 1 + len(chunk) < len(lines) else ""
    return ToolResult(truncate(body + more) or "(archivo vacío)")


@tool("write_file",
      """Crea o sobrescribe un archivo de texto (crea carpetas intermedias). Úsalo para HTML, JS, CSS,
      Python, Markdown, JSON, SVG, etc.""",
      {"properties": {
          "path": {"type": "string"},
          "content": {"type": "string"}},
       "required": ["path", "content"]})
def write_file(ctx: ToolContext, path: str, content: str) -> ToolResult:
    p = ctx.resolve(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    existed = p.exists()
    p.write_text(content, "utf-8")
    return ToolResult(f"{'Sobrescrito' if existed else 'Creado'}: {ctx.rel(p)} ({len(content)} caracteres)",
                      files=[p])


@tool("edit_file",
      """Reemplazo exacto de texto en un archivo. old_string debe aparecer exactamente una vez
      (o usa replace_all). Lee el archivo antes de editar.""",
      {"properties": {
          "path": {"type": "string"},
          "old_string": {"type": "string"},
          "new_string": {"type": "string"},
          "replace_all": {"type": "boolean"}},
       "required": ["path", "old_string", "new_string"]})
def edit_file(ctx: ToolContext, path: str, old_string: str, new_string: str,
              replace_all: bool = False) -> ToolResult:
    p = ctx.resolve(path, must_exist=True)
    text = p.read_text("utf-8")
    count = text.count(old_string)
    if count == 0:
        raise ToolError("old_string no se encontró. Vuelve a leer el archivo y copia el texto exacto.")
    if count > 1 and not replace_all:
        raise ToolError(f"old_string aparece {count} veces; añade más contexto o usa replace_all.")
    text = text.replace(old_string, new_string) if replace_all else text.replace(old_string, new_string, 1)
    p.write_text(text, "utf-8")
    return ToolResult(f"Editado {ctx.rel(p)} ({count if replace_all else 1} reemplazo/s)", files=[p])


@tool("list_files",
      "Lista archivos del workspace (recursivo) filtrando por patrón glob, p. ej. '*.png' o 'apps/**'.",
      {"properties": {
          "path": {"type": "string", "description": "Carpeta base (por defecto el workspace)."},
          "pattern": {"type": "string", "description": "Patrón glob sobre la ruta relativa."}}})
def list_files(ctx: ToolContext, path: str = ".", pattern: str = "*") -> ToolResult:
    base = ctx.resolve(path, must_exist=True)
    out = []
    for p in sorted(base.rglob("*")):
        if any(part in IGNORED_DIRS for part in p.relative_to(base).parts):
            continue
        rel = p.relative_to(base).as_posix()
        if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(p.name, pattern):
            if p.is_file():
                out.append(f"{rel}  ({p.stat().st_size:,} B)")
            else:
                out.append(rel + "/")
        if len(out) >= 500:
            out.append("[... límite de 500 entradas]")
            break
    return ToolResult("\n".join(out) or "(sin resultados)")


@tool("search_files",
      "Busca una expresión regular en archivos de texto del workspace. Devuelve ruta:línea: texto.",
      {"properties": {
          "regex": {"type": "string"},
          "path": {"type": "string"},
          "glob": {"type": "string", "description": "Filtro de nombre, p. ej. '*.py'."},
          "ignore_case": {"type": "boolean"}},
       "required": ["regex"]})
def search_files(ctx: ToolContext, regex: str, path: str = ".", glob: str = "*",
                 ignore_case: bool = False) -> ToolResult:
    base = ctx.resolve(path, must_exist=True)
    try:
        rx = re.compile(regex, re.IGNORECASE if ignore_case else 0)
    except re.error as e:
        raise ToolError(f"Regex inválida: {e}")
    hits = []
    files = [base] if base.is_file() else base.rglob(glob)
    for p in files:
        if not p.is_file() or any(part in IGNORED_DIRS for part in p.parts):
            continue
        if guess_kind(p) not in ("text", "html", "file") or p.stat().st_size > 5_000_000:
            continue
        try:
            for i, line in enumerate(p.read_text("utf-8", errors="ignore").splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{ctx.rel(p)}:{i}: {line.strip()[:300]}")
                    if len(hits) >= 300:
                        break
        except OSError:
            continue
        if len(hits) >= 300:
            break
    return ToolResult("\n".join(hits) or "(sin coincidencias)")
