"""Bucle agéntico de PixAgent.

Patrón (el mismo que usan Claude Code, OpenHands, Aider, smolagents...):
    mensaje del usuario -> modelo -> [herramientas -> resultados (texto + imágenes) -> modelo]* -> respuesta
Detalles importantes:
- El historial es SOLO-AÑADIR: se reenvía la respuesta del modelo tal cual (incluidos bloques de
  pensamiento), nunca se edita lo anterior; así funciona la caché y el pensamiento preservado.
- Todos los resultados de herramientas de un turno van juntos en un único mensaje de usuario.
- Las herramientas pueden devolver imágenes: el modelo VE lo que produjo y se auto-corrige.
- Permisos: las herramientas peligrosas piden aprobación según settings.permission_mode.
"""
from __future__ import annotations

import json
import time
import traceback
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

import anthropic

from .tools import REGISTRY, ToolContext, ToolError, ToolResult
from .tools.base import document_block, guess_kind, image_block, truncate, validate_input

Emit = Callable[[dict], None]


def _btype(b) -> str:
    return b.get("type") if isinstance(b, dict) else getattr(b, "type", "")


def _attr(b, k, default=None):
    return b.get(k, default) if isinstance(b, dict) else getattr(b, k, default)


def dump_block(b) -> dict:
    if isinstance(b, dict):
        return b
    if hasattr(b, "model_dump"):
        return b.model_dump(mode="json", exclude_none=True)
    return dict(b)


def sanitize_fallback(content: list) -> list:
    """Tras un fallback a mitad de respuesta, omitir pensamiento/herramientas previos al último bloque
    'fallback' (regla de la API para reenviar el turno)."""
    idx = [i for i, b in enumerate(content) if _btype(b) == "fallback"]
    if not idx:
        return list(content)
    last = idx[-1]
    drop = {"thinking", "redacted_thinking", "tool_use"}
    kept = []
    server_results = {_attr(b, "tool_use_id") for b in content if _btype(b).endswith("_tool_result")}
    for i, b in enumerate(content):
        t = _btype(b)
        if i < last and (t in drop or (t == "server_tool_use" and _attr(b, "id") not in server_results)):
            continue
        kept.append(b)
    return kept


class Agent:
    def __init__(self, settings, session_id: str | None = None, llm=None,
                 emit: Emit | None = None, approve: Callable[[str, dict], bool] | None = None):
        self.s = settings
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
        self.emit: Emit = emit or (lambda e: None)
        if llm is None:
            from .llm import ClaudeLLM
            llm = ClaudeLLM(settings)
        self.llm = llm
        self.messages: list[dict] = []
        self.transcript: list[dict] = []  # registro legible para la UI
        self.title = ""
        self.ctx = ToolContext(settings=settings, emit=self._emit, session_id=self.session_id,
                               approve=approve or (lambda n, i: True))
        self._cancel = False
        self.usage = {"input": 0, "output": 0, "cache_read": 0}

    # ------------------------------------------------------------------ utilidades
    def _emit(self, ev: dict) -> None:
        ev.setdefault("session", self.session_id)
        if ev["type"] in ("user", "assistant", "tool_end", "error", "todos"):
            self.transcript.append({k: v for k, v in ev.items() if k != "session"})
        try:
            self.emit(ev)
        except Exception:  # noqa: BLE001
            pass

    def cancel(self) -> None:
        self._cancel = True

    def tool_specs(self) -> list[dict]:
        return [t.spec() for t in REGISTRY.values()]

    @property
    def session_file(self) -> Path:
        return self.s.ws / ".sessions" / f"{self.session_id}.json"

    def save(self) -> None:
        data = {"id": self.session_id, "title": self.title, "updated": time.time(),
                "messages": [{"role": m["role"], "content": m["content"] if isinstance(m["content"], str)
                              else [dump_block(b) for b in m["content"]]} for m in self.messages],
                "transcript": self.transcript, "state": self.ctx.state, "usage": self.usage}
        self.session_file.write_text(json.dumps(data, ensure_ascii=False), "utf-8")

    @classmethod
    def load(cls, settings, session_id: str, **kw) -> "Agent":
        a = cls(settings, session_id=session_id, **kw)
        f = a.session_file
        if f.exists():
            data = json.loads(f.read_text("utf-8"))
            a.messages = data.get("messages", [])
            a.transcript = data.get("transcript", [])
            a.title = data.get("title", "")
            a.ctx.state.update(data.get("state", {}))
            a.usage.update(data.get("usage", {}))
        return a

    # ------------------------------------------------------------------ entrada del usuario
    def build_user_content(self, text: str, attachments: list[Path] | None = None) -> list[dict]:
        blocks: list[dict] = []
        notes = []
        for p in attachments or []:
            p = Path(p)
            kind = guess_kind(p)
            rel = self.ctx.rel(p)
            if kind == "image" and p.suffix.lower() != ".svg":
                try:
                    from PIL import Image
                    with Image.open(p) as im:
                        size = f"{im.width}x{im.height}px"
                    blocks.append(image_block(p))
                    notes.append(f"- {rel} (imagen {size})")
                except Exception as e:  # noqa: BLE001
                    notes.append(f"- {rel} (imagen ilegible: {e})")
            elif kind == "pdf" and p.stat().st_size < 25_000_000:
                blocks.append(document_block(p))
                notes.append(f"- {rel} (PDF)")
            else:
                notes.append(f"- {rel} ({kind})")
        header = f"[Contexto: fecha {datetime.now():%Y-%m-%d %H:%M}; workspace {self.s.ws}]"
        if notes:
            header += "\n[Archivos adjuntos (rutas para usar en las herramientas):\n" + "\n".join(notes) + "]"
        blocks.append({"type": "text", "text": header + "\n\n" + (text or "(sin texto)")})
        return blocks

    # ------------------------------------------------------------------ bucle principal
    def run(self, text: str, attachments: list[Path] | None = None) -> str:
        self._cancel = False
        if not self.title:
            self.title = (text or "Nueva sesión").strip().splitlines()[0][:60]
        self._emit({"type": "user", "text": text,
                    "attachments": [self.ctx.rel(Path(p)) for p in attachments or []]})
        self.messages.append({"role": "user", "content": self.build_user_content(text, attachments)})
        final_text = ""
        tools = self.tool_specs()
        try:
            for step in range(self.s.max_steps):
                if self._cancel:
                    self._emit({"type": "status", "text": "Cancelado por el usuario."})
                    break
                self._emit({"type": "turn_start", "step": step + 1})
                resp = self._call_model(tools)
                content = sanitize_fallback(list(resp.content))
                self.messages.append({"role": "assistant", "content": content})
                self._track_usage(resp)
                text_now = "".join(_attr(b, "text", "") for b in content if _btype(b) == "text")
                if text_now.strip():
                    final_text = text_now
                    self._emit({"type": "assistant", "text": text_now})
                stop = resp.stop_reason
                if stop == "refusal":
                    self._emit({"type": "error", "text": "El modelo rechazó la solicitud. Reformúlala."})
                    break
                if stop == "pause_turn":   # herramienta de servidor (web) en curso: continuar
                    continue
                tool_uses = [b for b in content if _btype(b) == "tool_use"]
                if not tool_uses:
                    if stop == "max_tokens":
                        self._emit({"type": "status", "text": "Respuesta cortada por longitud."})
                    break
                results = [self._run_tool(b, truncated=(stop == "max_tokens")) for b in tool_uses]
                self.messages.append({"role": "user", "content": results})
                self.save()
            else:
                self._emit({"type": "status", "text": f"Límite de {self.s.max_steps} pasos alcanzado."})
        except anthropic.AuthenticationError:
            self._emit({"type": "error", "text": "Falta o no es válida la clave de API (ANTHROPIC_API_KEY)."})
        except anthropic.RateLimitError:
            self._emit({"type": "error", "text": "Límite de uso de la API alcanzado; espera un momento y reintenta."})
        except anthropic.BadRequestError as e:
            self._emit({"type": "error", "text": f"Petición rechazada por la API: {e.message}"})
        except anthropic.APIStatusError as e:
            self._emit({"type": "error", "text": f"Error de la API ({e.status_code}): {e.message}"})
        except anthropic.APIConnectionError:
            self._emit({"type": "error", "text": "No hay conexión con la API de Anthropic."})
        except Exception as e:  # noqa: BLE001  (p.ej. sin credenciales configuradas)
            self._emit({"type": "error", "text": f"Error: {e}"})
        finally:
            self._repair_tail()
            self.save()
            self._emit({"type": "done", "text": final_text, "usage": self.usage})
        return final_text

    def _repair_tail(self) -> None:
        """Si el último turno del asistente pidió herramientas sin resultados (error/cancelación),
        añadimos resultados de error para que la conversación siga siendo válida."""
        if not self.messages or self.messages[-1]["role"] != "assistant":
            return
        pending = [b for b in self.messages[-1]["content"] if _btype(b) == "tool_use"]
        if pending:
            self.messages.append({"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": _attr(b, "id"), "is_error": True,
                 "content": "Interrumpido antes de ejecutar la herramienta."} for b in pending]})

    def _call_model(self, tools):
        # reintento simple ante sobrecarga
        for attempt in range(3):
            try:
                return self.llm.turn(self.messages, tools, self._emit)
            except anthropic.InternalServerError:
                if attempt == 2:
                    raise
                self._emit({"type": "status", "text": "Servidor ocupado, reintentando…"})
                time.sleep(2 * (attempt + 1))

    def _track_usage(self, resp) -> None:
        u = getattr(resp, "usage", None)
        if u is not None:
            self.usage["input"] += getattr(u, "input_tokens", 0) or 0
            self.usage["output"] += getattr(u, "output_tokens", 0) or 0
            self.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0

    # ------------------------------------------------------------------ ejecución de herramientas
    def _run_tool(self, block, truncated: bool = False) -> dict:
        name, tid, inp = _attr(block, "name"), _attr(block, "id"), _attr(block, "input")
        self._emit({"type": "tool_start", "id": tid, "name": name, "input": _preview_input(inp)})
        t0 = time.time()
        tool = REGISTRY.get(name)
        try:
            if tool is None:
                raise ToolError(f"Herramienta desconocida: {name}")
            err = validate_input(tool, inp)
            if err or truncated:
                raise ToolError((err or "") + (" La respuesta se cortó por longitud; divide el trabajo en partes más pequeñas." if truncated else ""))
            if tool.needs_approval(self.s) and not self.ctx.approve(name, inp):
                raise ToolError("El usuario no autorizó esta acción. Propón una alternativa o pregunta.")
            result = tool.func(self.ctx, **inp)
        except ToolError as e:
            result = ToolResult(f"Error: {e}", is_error=True)
        except TypeError as e:
            result = ToolResult(f"Error en los parámetros: {e}", is_error=True)
        except Exception as e:  # noqa: BLE001
            result = ToolResult(f"Error inesperado: {e}\n{traceback.format_exc(limit=3)}", is_error=True)

        if "todos" in result.data:
            self._emit({"type": "todos", "todos": result.data["todos"]})
        self._emit({"type": "tool_end", "id": tid, "name": name, "is_error": result.is_error,
                    "text": truncate(result.text, 3000), "seconds": round(time.time() - t0, 1),
                    "files": [self.ctx.rel(Path(f)) for f in result.files if Path(f).exists()],
                    "images": [self.ctx.rel(Path(f)) for f in result.images if Path(f).exists()]})
        content: list[dict] = [{"type": "text", "text": truncate(result.text) or "(ok)"}]
        for img in result.images[:6]:
            try:
                content.append(image_block(Path(img)))
            except Exception as e:  # noqa: BLE001
                content.append({"type": "text", "text": f"(no se pudo adjuntar {img}: {e})"})
        out = {"type": "tool_result", "tool_use_id": tid, "content": content}
        if result.is_error:
            out["is_error"] = True
        return out


def _preview_input(inp: Any) -> dict:
    if not isinstance(inp, dict):
        return {}
    prev = {}
    for k, v in inp.items():
        if isinstance(v, str) and len(v) > 400:
            prev[k] = v[:400] + f"… ({len(v)} caracteres)"
        elif isinstance(v, (list, dict)):
            s = json.dumps(v, ensure_ascii=False)
            prev[k] = json.loads(s) if len(s) < 1500 else s[:1500] + "…"
        else:
            prev[k] = v
    return prev
