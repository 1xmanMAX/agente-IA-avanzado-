"""Ejecución de código: Python (con cualquier librería instalada), shell y gestión de tareas."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import uuid
from pathlib import Path

from .base import ToolContext, ToolError, ToolResult, guess_kind, tool, truncate

SHELL_LIMIT = 12_000
_SNAPSHOT_SKIP = {".sessions", ".tmp", "node_modules", ".git", "__pycache__"}


def _snapshot(root: Path) -> dict[Path, float]:
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _SNAPSHOT_SKIP]
        for f in filenames:
            p = Path(dirpath) / f
            try:
                snap[p] = p.stat().st_mtime
            except OSError:
                pass
    return snap


def _changed(before: dict[Path, float], after: dict[Path, float]) -> list[Path]:
    return [p for p, m in after.items() if before.get(p) != m]


def _run(ctx: ToolContext, cmd, timeout: int, shell: bool, cwd: Path) -> ToolResult:
    before = _snapshot(ctx.ws)
    env = {**os.environ, "MPLBACKEND": "Agg", "PYTHONIOENCODING": "utf-8",
           "PIXAGENT_WORKSPACE": str(ctx.ws)}
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, shell=shell, cwd=cwd, capture_output=True, text=True,
                              timeout=timeout, env=env, encoding="utf-8", errors="replace")
    except subprocess.TimeoutExpired as e:
        out = (e.stdout or "") if isinstance(e.stdout, str) else ""
        raise ToolError(f"Tiempo agotado tras {timeout}s.\n{truncate(out, 5000)}")
    dt = time.time() - t0
    new_files = [p for p in _changed(before, _snapshot(ctx.ws))]
    parts = [f"exit_code={proc.returncode}  ({dt:.1f}s)"]
    if proc.stdout.strip():
        parts.append("STDOUT:\n" + proc.stdout.rstrip())
    if proc.stderr.strip():
        parts.append("STDERR:\n" + proc.stderr.rstrip())
    if new_files:
        parts.append("Archivos creados/modificados:\n" + "\n".join(ctx.rel(p) for p in new_files[:50]))
    images = [p for p in new_files if guess_kind(p) == "image" and p.suffix.lower() != ".svg"][:4]
    text = "\n\n".join(parts)
    if len(text) > SHELL_LIMIT:
        # Salida larga: se guarda completa y al modelo le llegan cabeza y cola (patrón Codex/Gemini CLI)
        full = ctx.ws / ".tmp" / f"salida_{uuid.uuid4().hex[:6]}.txt"
        full.write_text(text, "utf-8")
        lines = text.count("\n") + 1
        text = (truncate(text, SHELL_LIMIT) + f"\n\n[Salida completa ({lines} líneas) en {ctx.rel(full)}: "
                "léela por partes con read_file(path, offset, limit) si la necesitas.]")
    return ToolResult(text, images=images, files=new_files[:50], is_error=proc.returncode != 0)


@tool("run_python",
      """Ejecuta código Python en un proceso aparte con el directorio de trabajo = workspace.
      Puedes usar cualquier librería instalada (PIL/Pillow, matplotlib, numpy, pandas, reportlab,
      pymupdf, openpyxl, python-docx, networkx, etc.). Imprime lo que necesites ver con print().
      Las imágenes que el script guarde dentro del workspace se te muestran automáticamente
      (hasta 4) para que verifiques el resultado. matplotlib usa el backend Agg (guarda con savefig).
      Si falta una librería, puedes instalarla con run_shell: pip install <paquete>.""",
      {"properties": {
          "code": {"type": "string", "description": "Código Python completo."},
          "timeout": {"type": "integer", "description": "Segundos (por defecto 180)."},
          "save_as": {"type": "string", "description": "Opcional: guardar el script en esta ruta para reutilizarlo."}},
       "required": ["code"]},
      needs_approval=lambda s: s.permission_mode == "ask")
def run_python(ctx: ToolContext, code: str, timeout: int = 180, save_as: str | None = None) -> ToolResult:
    if save_as:
        script = ctx.resolve(save_as)
        script.parent.mkdir(parents=True, exist_ok=True)
    else:
        script = ctx.ws / ".tmp" / f"run_{uuid.uuid4().hex[:8]}.py"
    script.write_text(code, "utf-8")
    res = _run(ctx, [sys.executable, str(script)], timeout, shell=False, cwd=ctx.ws)
    if save_as:
        res.files.append(script)
    return res


@tool("run_shell",
      """Ejecuta un comando de shell en el workspace (cmd en Windows, bash en Linux/macOS).
      Útil para pip install, git, conversiones con herramientas de línea de comandos, etc.""",
      {"properties": {
          "command": {"type": "string"},
          "timeout": {"type": "integer", "description": "Segundos (por defecto 120)."},
          "cwd": {"type": "string", "description": "Carpeta (relativa al workspace)."}},
       "required": ["command"]},
      needs_approval=lambda s: s.permission_mode != "full")
def run_shell(ctx: ToolContext, command: str, timeout: int = 120, cwd: str = ".") -> ToolResult:
    return _run(ctx, command, timeout, shell=True, cwd=ctx.resolve(cwd, must_exist=True))


@tool("todo_write",
      """Mantén una lista de tareas para trabajos de varios pasos (planos, informes, apps).
      Envía la lista COMPLETA cada vez. Marca exactamente una tarea 'in_progress' mientras trabajas
      y 'completed' en cuanto la termines.""",
      {"properties": {
          "todos": {"type": "array", "items": {
              "type": "object",
              "properties": {
                  "content": {"type": "string"},
                  "status": {"type": "string", "enum": ["pending", "in_progress", "completed"]}},
              "required": ["content", "status"]}}},
       "required": ["todos"]})
def todo_write(ctx: ToolContext, todos: list) -> ToolResult:
    ctx.state["todos"] = todos
    icons = {"pending": "[ ]", "in_progress": "[~]", "completed": "[x]"}
    text = "\n".join(f"{icons.get(t.get('status'), '[ ]')} {t.get('content')}" for t in todos)
    return ToolResult("Lista actualizada:\n" + text, data={"todos": todos})
