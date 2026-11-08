"""Subagentes (delegate) y carga de habilidades (load_skill).

Diseño tomado del código abierto de gemini-cli (local-executor: registro de herramientas aislado,
sin recursión, tope de turnos), Goose (summon/delegate: contexto de referencia separado de la
tarea, el padre solo recibe el informe final) y codex (un rol solo puede RESTRINGIR al hijo).
"""
from __future__ import annotations

from .base import ToolContext, ToolError, ToolResult, tool

SUBAGENT_ROLE = """# Eres un SUBAGENTE de PixAgent
Otro agente te delegó UNA tarea concreta. Trabaja de forma autónoma con tus herramientas (no puedes
preguntar al usuario ni delegar). Sé eficiente: lee/mira solo lo necesario. Termina SIEMPRE con un
INFORME FINAL en texto: resultado, datos clave (rutas, cifras, hallazgos), dudas o límites y, si
procede, qué recomiendas hacer. Ese informe es lo único que verá el agente principal."""

SCOPES = {
    "lectura": {"read_file", "list_files", "search_files", "view_image", "pdf_tools", "preview_page",
                "local_ai", "load_skill"},
    "escritura": {"read_file", "list_files", "search_files", "view_image", "pdf_tools", "preview_page",
                  "local_ai", "load_skill", "write_file", "edit_file", "run_python", "image_tools",
                  "compose_plan", "render_diagram", "create_pdf", "photo_panel", "todo_write"},
}


@tool("delegate",
      """Delega una SUBTAREA autocontenida en un subagente con contexto limpio, que trabaja solo y te
      devuelve únicamente su informe final. Úsalo para: revisar muchas fotos/documentos y resumirlos,
      investigar varias alternativas en paralelo (varias llamadas delegate en el MISMO turno se
      ejecutan a la vez), o revisar críticamente un entregable (revisor de solo lectura). No lo uses
      para tareas cortas que puedes hacer tú. scope='lectura' (por defecto: no modifica nada) o
      'escritura' (crea/edita archivos: reparte archivos distintos a cada subagente para no pisarse).
      Da en 'task' el objetivo, el formato del informe y los criterios; en 'context' los datos que
      necesita (rutas, decisiones del usuario).""",
      {"properties": {
          "task": {"type": "string"},
          "context": {"type": "string", "description": "Contexto de referencia (rutas, datos, decisiones)."},
          "scope": {"type": "string", "enum": ["lectura", "escritura"]},
          "max_turns": {"type": "integer", "description": "Tope de pasos (def. 15, máx. 40)."}},
       "required": ["task"]})
def delegate(ctx: ToolContext, task: str, context: str = "", scope: str = "lectura", max_turns: int = 15) -> ToolResult:
    from copy import copy

    from ..agent import Agent
    from ..llm import ClaudeLLM
    parent = getattr(ctx, "agent", None)
    if ctx.state.get("_is_subagent"):
        raise ToolError("Un subagente no puede delegar.")
    allowed = SCOPES.get(scope, SCOPES["lectura"])
    sub_settings = copy(ctx.settings)
    sub_settings.max_steps = max(3, min(int(max_turns or 15), 40))
    if getattr(ctx.settings, "subagent_model", ""):
        sub_settings.model = ctx.settings.subagent_model
    llm = getattr(parent, "llm", None)
    if llm is None or not hasattr(llm, "_params"):   # en tests se reutiliza el LLM simulado
        llm_sub = llm
    else:
        llm_sub = ClaudeLLM(sub_settings, client=getattr(llm, "_client", None))
    label = task.strip().splitlines()[0][:60]

    def relay(ev: dict):  # al usuario solo le llega un resumen del progreso del subagente
        if ev.get("type") == "tool_start":
            ctx.emit({"type": "status", "text": f"Subagente «{label}»: {ev.get('name')}…"})

    sub = Agent(sub_settings, session_id=f"sub_{ctx.session_id}", llm=llm_sub, emit=relay,
                allowed_tools=allowed, role=SUBAGENT_ROLE, persist=False,
                approve=ctx.approve)
    sub.ctx.state["_is_subagent"] = True
    sub.ctx.state["turn"] = ctx.state.get("turn", 0)
    prompt = task + (f"\n\n## Contexto de referencia\n{context}" if context else "")
    report = sub.run(prompt)
    if parent is not None:   # el coste del subagente cuenta para el tope de la tarea principal
        parent._task_usd = getattr(parent, "_task_usd", 0.0) + sub.usage.get("usd", 0.0)
        for k in ("input", "output", "cache_read"):
            parent.usage[k] = parent.usage.get(k, 0) + sub.usage.get(k, 0)
        parent.usage["usd"] = round(parent.usage.get("usd", 0.0) + sub.usage.get("usd", 0.0), 4)
    if not report.strip():
        errs = [e.get("text") for e in sub.transcript if e.get("type") == "error"]
        raise ToolError("El subagente no devolvió informe." + (f" Error: {errs[-1]}" if errs else ""))
    return ToolResult(f"Informe del subagente ({scope}):\n{report}")


@tool("load_skill",
      """Carga el contenido completo de una HABILIDAD del catálogo (conocimiento experto y procedimientos:
      informes fotográficos, patologías, planos con fotos y las que añada el usuario). Hazlo antes de
      trabajos de ese tipo si no se cargó ya automáticamente.""",
      {"properties": {"name": {"type": "string"}}, "required": ["name"]})
def load_skill(ctx: ToolContext, name: str) -> ToolResult:
    from .. import skills as SK
    sk = SK.skills(ctx.settings)
    d = sk.get(name) or next((v for k, v in sk.items() if name.lower() in k.lower()), None)
    if not d:
        raise ToolError(f"No existe la habilidad '{name}'. Disponibles: {', '.join(sk) or 'ninguna'}.")
    return ToolResult(f"# Habilidad: {d['name']}\n{d['body']}")
