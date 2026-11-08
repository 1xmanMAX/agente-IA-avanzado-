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
        mem = self.s.ws / "PIXAGENT.md"
        if hasattr(llm, "memory") and mem.exists():
            llm.memory = mem.read_text("utf-8")[:12000]  # memoria corta y estable (se cachea)
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
        if ev["type"] in ("user", "assistant", "tool_end", "error", "todos", "question", "answer", "status"):
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
        if getattr(self, "_pending_note", None):
            header += "\n" + self._pending_note
            self._pending_note = None
        if notes:
            header += "\n[Archivos adjuntos (rutas para usar en las herramientas):\n" + "\n".join(notes) + "]"
        blocks.append({"type": "text", "text": header + "\n\n" + (text or "(sin texto)")})
        return blocks

    # ------------------------------------------------------------------ bucle principal
    def run(self, text: str, attachments: list[Path] | None = None) -> str:
        import anthropic  # carga diferida: ~60 MB que no se gastan hasta el primer mensaje
        self._cancel = False
        self.ctx.state["turn"] = int(self.ctx.state.get("turn", 0)) + 1
        self._calls: dict[str, int] = {}
        self._task_usd = 0.0
        if not self.title:
            self.title = (text or "Nueva sesión").strip().splitlines()[0][:60]
        self._emit({"type": "user", "text": text,
                    "attachments": [self.ctx.rel(Path(p)) for p in attachments or []]})
        content = self.build_user_content(text, attachments)
        if self.messages and self.messages[-1]["role"] == "user":
            # p. ej. tras un error que dejó resultados de herramientas: un único turno de usuario
            prev = self.messages[-1]["content"]
            self.messages[-1]["content"] = (prev if isinstance(prev, list) else [{"type": "text", "text": prev}]) + content
        else:
            self.messages.append({"role": "user", "content": content})
        self.save()  # guardar ya: si el usuario recarga a mitad del turno, la sesión existe
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
                if self.s.max_usd_per_task and self._task_usd > self.s.max_usd_per_task:
                    self._emit({"type": "error", "text": f"Se alcanzó el tope de coste por tarea "
                                f"({self.s.max_usd_per_task} USD). Sube 'max_usd_per_task' o divide la tarea."})
                    break
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
                results = self._run_tools(tool_uses, truncated=(stop == "max_tokens"))
                self.messages.append({"role": "user", "content": results})
                self.save()
            else:
                self._emit({"type": "status", "text": f"Límite de {self.s.max_steps} pasos alcanzado."})
        except anthropic.AuthenticationError:
            self._emit({"type": "error", "text": "Falta o no es válida la clave de API. Añádela en Ajustes → Clave de API."})
        except anthropic.RateLimitError:
            self._emit({"type": "error", "text": "Límite de uso de la API alcanzado; espera un momento y reintenta."})
        except anthropic.BadRequestError as e:
            self._emit({"type": "error", "text": f"Petición rechazada por la API: {e.message}"})
        except anthropic.APIStatusError as e:
            self._emit({"type": "error", "text": f"Error de la API ({e.status_code}): {e.message}"})
        except anthropic.APIConnectionError:
            self._emit({"type": "error", "text": "No hay conexión con la API de Anthropic."})
        except Exception as e:  # noqa: BLE001  (p.ej. sin credenciales configuradas)
            msg = str(e)
            if "authentication" in msg.lower() or "api_key" in msg.lower():
                msg = "No hay clave de API configurada. Añádela en Ajustes → Clave de API."
            self._emit({"type": "error", "text": msg if msg.startswith("No hay") else f"Error: {msg}"})
        finally:
            self._repair_tail()
            self.save()
            self._emit({"type": "done", "text": final_text, "usage": self.usage})
        return final_text

    def undo_last_turn(self) -> list[str]:
        """Deshace los cambios de archivos del último turno con cambios (restaura copias, borra creados)."""
        import shutil
        base = self.s.ws / ".checkpoints" / self.session_id
        if not base.exists():
            return []
        turns = sorted((int(d.name) for d in base.iterdir() if d.is_dir() and d.name.isdigit()), reverse=True)
        for t in turns:
            d = base / str(t)
            man = d / "manifest.json"
            if not man.exists():
                continue
            data = json.loads(man.read_text("utf-8"))
            restored = []
            for rel, backup in data.items():
                target = (self.s.ws / rel)
                if backup is None:
                    if target.exists():
                        target.unlink()
                    restored.append(f"borrado {rel}")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(d / backup, target)
                    restored.append(f"restaurado {rel}")
            shutil.rmtree(d, ignore_errors=True)
            note = "[Nota del sistema: el usuario deshizo los cambios de archivos del turno anterior: " + "; ".join(restored[:30]) + "]"
            self.transcript.append({"type": "status", "text": "Cambios deshechos: " + ", ".join(restored[:10])})
            self._pending_note = note
            self.save()
            return restored
        return []

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
        import anthropic
        # reintento simple ante sobrecarga
        for attempt in range(3):
            try:
                return self.llm.turn(self.messages, tools, self._emit)
            except anthropic.BadRequestError as e:
                # Si la cuenta/modelo no admite una función beta opcional, se desactiva y se reintenta
                msg = str(getattr(e, "message", e)).lower()
                if getattr(self.llm, "context_editing", False) and "context_management" in msg:
                    self.llm.context_editing = False
                    continue
                if getattr(self.llm, "progress_updates", False) and ("display" in msg or "thinking-display" in msg):
                    self.llm.progress_updates = False
                    continue
                raise
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
            from .reports.engine import PRICES
            pin, pout = PRICES.get(self.s.model, PRICES["claude-opus-5-5"])
            cached = getattr(u, "cache_read_input_tokens", 0) or 0
            written = getattr(u, "cache_creation_input_tokens", 0) or 0
            usd = ((getattr(u, "input_tokens", 0) or 0) * pin + cached * pin * 0.1 + written * pin * 1.25
                   + (getattr(u, "output_tokens", 0) or 0) * pout) / 1e6
            self._task_usd = getattr(self, "_task_usd", 0.0) + usd
            self.usage["usd"] = round(self.usage.get("usd", 0.0) + usd, 4)

    # ------------------------------------------------------------------ ejecución de herramientas
    # Herramientas sin efectos secundarios: si TODAS las de un turno lo son, se ejecutan en paralelo
    # (patrón de Codex CLI / Gemini CLI / opencode). Las que escriben se ejecutan en orden.
    PARALLEL_SAFE = {"read_file", "list_files", "search_files", "view_image", "preview_page"}

    def _run_tools(self, tool_uses: list, truncated: bool = False) -> list[dict]:
        names = [_attr(b, "name") for b in tool_uses]
        if len(tool_uses) > 1 and not truncated and all(n in self.PARALLEL_SAFE for n in names):
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(6, len(tool_uses))) as ex:
                return list(ex.map(self._run_tool, tool_uses))   # map conserva el orden
        return [self._run_tool(b, truncated=truncated) for b in tool_uses]

    def _run_tool(self, block, truncated: bool = False) -> dict:
        name, tid, inp = _attr(block, "name"), _attr(block, "id"), _attr(block, "input")
        self._emit({"type": "tool_start", "id": tid, "name": name, "input": _preview_input(inp)})
        t0 = time.time()
        tool = REGISTRY.get(name)
        try:
            if tool is None:
                raise ToolError(f"Herramienta desconocida: {name}")
            key = name + json.dumps(inp, sort_keys=True, ensure_ascii=False)[:4000]
            calls = getattr(self, "_calls", {})
            calls[key] = calls.get(key, 0) + 1
            self._calls = calls
            if calls[key] >= 3:
                raise ToolError("Ya hiciste esta misma llamada 2 veces en esta tarea con el mismo resultado. "
                                "Cambia de estrategia (otros parámetros u otra herramienta) o pregunta al usuario.")
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
