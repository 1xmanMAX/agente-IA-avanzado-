"""Cliente de Claude para el bucle del agente (streaming + pensamiento adaptativo + herramientas)."""
from __future__ import annotations

from typing import Callable

import anthropic

from .prompts import SYSTEM_PROMPT

BETA_FALLBACK = "server-side-fallback-2026-07-01"
BETA_UPDATES = "thinking-display-updates-2026-08-18"
BETA_CONTEXT = "context-management-2025-06-27"
# Modelos que admiten fallbacks del lado del servidor con el modo "default"
_FALLBACK_MODELS = ("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")


class ClaudeLLM:
    """Envuelve client.beta.messages.stream y traduce el streaming a eventos para la UI."""

    def __init__(self, settings, client: anthropic.Anthropic | None = None):
        self.s = settings
        self._client = client
        # Funciones beta opcionales: se desactivan solas si la API las rechaza
        self.context_editing = settings.context_editing
        self.progress_updates = settings.progress_updates
        self.memory = ""   # contenido de PIXAGENT.md (memoria del proyecto), fijo durante la sesión

    @property
    def client(self) -> anthropic.Anthropic:
        if self._client is None:  # se crea al primer uso: la UI arranca aunque falte la clave
            from .anthropic_client import make_client
            self._client = make_client(self.s)
        return self._client

    def _params(self, messages: list, tools: list[dict]) -> dict:
        s = self.s
        betas: list[str] = []
        params: dict = {
            "model": s.model,
            "max_tokens": s.max_tokens,
            "system": [{"type": "text", "text": SYSTEM_PROMPT}] + (
                [{"type": "text", "text": "# Memoria del proyecto (PIXAGENT.md)\n" + self.memory}] if self.memory else []),
            "messages": messages,
            "tools": list(tools),
            # caché automática del prefijo (herramientas + sistema + historial)
            "cache_control": {"type": "ephemeral"},
        }
        if not s.model.startswith("claude-haiku-4"):
            thinking = {"type": "adaptive"}
            if self.progress_updates:
                thinking["display"] = "updates"
                betas.append(BETA_UPDATES)
            params["thinking"] = thinking
            params["output_config"] = {"effort": s.effort}
        if s.server_fallbacks and s.model.startswith(_FALLBACK_MODELS):
            params["fallbacks"] = "default"
            betas.append(BETA_FALLBACK)
        if s.enable_web:
            params["tools"] += [{"type": "web_search_20260209", "name": "web_search", "max_uses": 8},
                                {"type": "web_fetch_20260209", "name": "web_fetch", "max_uses": 8}]
        if self.context_editing:
            # Limpia en el servidor los resultados de herramientas antiguos (capturas, salidas largas)
            # cuando el contexto crece; en bloques grandes para no invalidar la caché a menudo.
            params["context_management"] = {"edits": [{
                "type": "clear_tool_uses_20250919",
                "trigger": {"type": "input_tokens", "value": 60000},
                "keep": {"type": "tool_uses", "value": 6},
                "clear_at_least": {"type": "input_tokens", "value": 15000},
                "exclude_tools": ["todo_write", "remember"],
            }]}
            betas.append(BETA_CONTEXT)
        if betas:
            params["betas"] = betas
        return params

    def turn(self, messages: list, tools: list[dict], emit: Callable[[dict], None]):
        """Una llamada al modelo. Emite text_delta / status / tool_preparing y devuelve el mensaje final."""
        params = self._params(messages, tools)
        with self.client.beta.messages.stream(**params) as stream:
            for ev in stream:
                et = getattr(ev, "type", "")
                if et == "content_block_start":
                    blk = ev.content_block
                    bt = getattr(blk, "type", "")
                    if bt == "tool_use":
                        emit({"type": "tool_preparing", "name": blk.name})
                    elif bt == "server_tool_use":
                        emit({"type": "status", "text": f"Usando {blk.name}…"})
                    elif bt == "fallback":
                        emit({"type": "status", "text": "Reintentando con el modelo de respaldo…"})
                elif et == "content_block_delta":
                    d = ev.delta
                    dt = getattr(d, "type", "")
                    if dt == "text_delta":
                        emit({"type": "text_delta", "text": d.text})
                    elif dt == "thinking_delta" and d.thinking:
                        emit({"type": "thinking_delta", "text": d.thinking})
            return stream.get_final_message()
