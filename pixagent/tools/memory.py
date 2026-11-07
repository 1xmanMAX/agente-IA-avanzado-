"""Memoria del proyecto: PIXAGENT.md en el workspace (como CLAUDE.md / AGENTS.md)."""
from __future__ import annotations

from datetime import date

from .base import ToolContext, ToolError, ToolResult, tool

HEADER = ("# Memoria de PixAgent\n\nPreferencias y datos estables del usuario y sus proyectos. "
          "El agente la lee al empezar cada sesión. Puedes editarla a mano.\n")


@tool("remember",
      """Guarda en la memoria del proyecto (PIXAGENT.md) un dato ESTABLE que convenga recordar en futuras
      sesiones: preferencias del usuario (formato de informes, empresa, logo, colores, normativa,
      unidades), datos recurrentes de obras, convenciones. Úsalo cuando el usuario diga "recuerda...",
      o cuando repita una preferencia. No guardes datos temporales ni información sensible.""",
      {"properties": {
          "note": {"type": "string", "description": "Una línea clara y autocontenida."},
          "section": {"type": "string", "description": "Preferencias | Empresa | Proyectos | Convenciones"}},
       "required": ["note"]})
def remember(ctx: ToolContext, note: str, section: str = "Preferencias") -> ToolResult:
    note = " ".join(note.split())
    if not note or len(note) > 500:
        raise ToolError("La nota debe tener entre 1 y 500 caracteres.")
    f = ctx.ws / "PIXAGENT.md"
    text = f.read_text("utf-8") if f.exists() else HEADER
    if note.lower() in text.lower():
        return ToolResult("Ya estaba en la memoria.")
    if len(text) > 11000:
        raise ToolError("La memoria está llena (~12 000 caracteres): pide al usuario que la revise.")
    head = f"## {section.strip() or 'Preferencias'}"
    line = f"- {note} _(añadido {date.today():%Y-%m-%d})_"
    if head in text:
        i = text.index(head) + len(head)
        j = text.find("\n## ", i)
        j = len(text) if j < 0 else j
        text = text[:j].rstrip() + "\n" + line + "\n" + text[j:]
    else:
        text = text.rstrip() + f"\n\n{head}\n{line}\n"
    f.write_text(text, "utf-8")
    return ToolResult(f"Guardado en la memoria ({head[3:]}). Se aplicará desde la próxima sesión.", files=[f])
