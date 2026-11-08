"""Preguntar al usuario (como AskUserQuestion de Claude Code): opciones sugeridas + respuesta libre."""
from __future__ import annotations

from .base import ToolContext, ToolError, ToolResult, tool


@tool("ask_user",
      """Haz al usuario UNA pregunta breve cuando su petición sea ambigua y la respuesta cambie de verdad
      lo que vas a hacer (qué entregable, formato de salida, alcance, datos que faltan), o para que
      apruebe un plan antes de un trabajo grande. Ofrece 2-4 opciones concretas (la recomendada primero,
      con "(recomendado)") con una descripción corta de cada una; el usuario también puede escribir otra
      respuesta. Espera su respuesta y continúa. NO preguntes lo que puedas deducir, ni por cortesía, ni
      varias cosas a la vez; si hay un valor por defecto razonable, úsalo y dilo.""",
      {"properties": {
          "question": {"type": "string", "description": "La pregunta, clara y autocontenida."},
          "options": {"type": "array", "minItems": 2, "maxItems": 4, "items": {
              "type": "object",
              "properties": {"label": {"type": "string", "description": "1-5 palabras"},
                             "description": {"type": "string"}},
              "required": ["label"]}},
          "multi_select": {"type": "boolean", "description": "Permitir elegir varias opciones."}},
       "required": ["question", "options"]})
def ask_user(ctx: ToolContext, question: str, options: list, multi_select: bool = False) -> ToolResult:
    opts = [o if isinstance(o, dict) else {"label": str(o)} for o in options][:4]
    if len(opts) < 2:
        raise ToolError("Ofrece al menos 2 opciones.")
    answer = ctx.ask(question, opts, bool(multi_select))
    if answer is None or not str(answer).strip():
        return ToolResult("El usuario no respondió (o no hay interfaz). Continúa con la opción más razonable "
                          "(la recomendada) y dilo claramente en tu respuesta.")
    return ToolResult(f"Respuesta del usuario: {answer}", data={"answer": answer})
