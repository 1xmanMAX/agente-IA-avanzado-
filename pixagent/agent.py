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

# Herramientas de solo lectura: usadas por el modo plan y los subagentes de investigación
READ_ONLY_TOOLS = {"read_file", "list_files", "search_files", "view_image", "image_tools_info", "pdf_tools",
                   "preview_page", "local_ai", "load_skill"}
PLAN_TOOLS = READ_ONLY_TOOLS | {"ask_user", "todo_write", "delegate", "remember"}


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
                 emit: Emit | None = None, approve: Callable[[str, dict], bool] | None = None,
                 allowed_tools: set[str] | None = None, role: str = "", persist: bool = True):
        self.s = settings
        self.allowed_tools = allowed_tools   # None = todas (subagentes: subconjunto)
        self.persist = persist
        self.session_id = session_id or datetime.now().strftime("%Y%m%d_%H%M%S_") + uuid.uuid4().hex[:4]
        self.emit: Emit = emit or (lambda e: None)
        if llm is None:
            from .llm import ClaudeLLM
            llm = ClaudeLLM(settings)
        self.llm = llm
        if hasattr(llm, "memory"):
            # Memoria jerárquica (como AGENTS.md de codex/opencode): global del usuario + workspace.
            # Se carga una vez por sesión: estable, así se aprovecha la caché.
            from . import skills as SK
            llm.memory = SK.load_memory(self.s)
            llm.skills = SK.catalog_text(self.s)
            if role:
                llm.role = role
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
        if ev["type"] in ("user", "assistant", "tool_end", "error", "todos", "question", "answer") or \
                (ev["type"] == "status" and ev.get("persist")):
            self.transcript.append({k: v for k, v in ev.items() if k != "session"})
        try:
            self.emit(ev)
        except Exception:  # noqa: BLE001
            pass

    def cancel(self) -> None:
        self._cancel = True

    def tool_specs(self) -> list[dict]:
        return [t.spec() for t in REGISTRY.values() if self.allowed_tools is None or t.name in self.allowed_tools]

    @property
    def session_file(self) -> Path:
        return self.s.ws / ".sessions" / f"{self.session_id}.json"

    def save(self) -> None:
        if not self.persist:
            return
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
        self._sigs: list[str] = []
        self._err_streak: dict[str, int] = {}
        self._nudges = 0
        self._task_usd = 0.0
        self.ctx.agent = self   # para herramientas que necesitan al agente (delegate)
        if not self.title:
            self.title = (text or "Nueva sesión").strip().splitlines()[0][:60]
        marks = self.ctx.state.setdefault("marks", [])
        marks.append({"turn": self.ctx.state["turn"], "msg": len(self.messages), "tr": len(self.transcript),
                      "mode": self.ctx.state.get("mode", "normal")})
        self._emit({"type": "user", "text": text, "turn": self.ctx.state["turn"],
                    "attachments": [self.ctx.rel(Path(p)) for p in attachments or []]})
        handled = self._local_command(text)
        if handled is not None:
            if handled[0] == "reply":            # comando resuelto sin llamar al modelo
                self._emit({"type": "assistant", "text": handled[1]})
                self.save()
                self._emit({"type": "done", "text": handled[1], "usage": self.usage})
                return handled[1]
            text = handled[1]                    # comando que se convierte en un mensaje al modelo
        content = self.build_user_content(text, attachments)
        content += self._context_blocks(text)
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

    # ------------------------------------------------------------------ comandos, modos y habilidades
    def _local_command(self, text: str):
        """Comandos con barra (estilo Claude Code). Devuelve None, ('reply', texto) o ('prompt', texto)."""
        from . import skills as SK
        t = (text or "").strip()
        if not t.startswith("/"):
            return None
        cmd, _, rest = t.partition(" ")
        cmd, rest = cmd.lower(), rest.strip()
        if cmd == "/plan":
            self.ctx.state["mode"] = "plan"
            if not rest:
                return ("reply", "Modo plan activado: investigaré y te propondré un plan sin modificar nada. "
                                 "Cuéntame la tarea. Cuando estés de acuerdo, escribe /ejecutar.")
            return ("prompt", rest)
        if cmd in ("/ejecutar", "/act", "/actuar"):
            self.ctx.state["mode"] = "normal"
            return ("prompt", rest or "Adelante: ejecuta el plan acordado.")
        if cmd in ("/deshacer", "/undo"):
            restored = self.undo_last_turn()
            return ("reply", "Deshecho: " + ", ".join(restored) if restored else "No hay cambios de archivos que deshacer.")
        if cmd in ("/ayuda", "/help", "/recetas", "/comandos"):
            rc = SK.recipes(self.s)
            sk = SK.skills(self.s)
            lines = ["**Comandos**", "- `/plan <tarea>`: investigar y proponer un plan sin tocar nada",
                     "- `/ejecutar`: llevar a cabo el plan", "- `/deshacer`: revertir los cambios del último turno",
                     "- `/ayuda`: esta lista"]
            if rc:
                lines += ["", "**Recetas**"] + [f"- `/{d['name']}`: {d.get('description', '')}" for d in rc.values()]
            if sk:
                lines += ["", "**Habilidades** (se usan solas cuando hacen falta)"] + \
                         [f"- {d['name']}: {d.get('description', '')}" for d in sk.values()]
            lines += ["", "Tus recetas y habilidades: carpetas `recetas/` y `skills/` del workspace (Markdown)."]
            return ("reply", "\n".join(lines))
        exp = SK.expand_recipe(self.s, t)
        if exp:
            return ("prompt", exp[0])
        return None

    def _context_blocks(self, text: str) -> list[dict]:
        """Bloques extra del turno: modo plan y habilidades activadas por palabras clave (se adjuntan
        al mensaje y no al prompt de sistema, para no invalidar la caché)."""
        from . import skills as SK
        blocks = []
        if self.ctx.state.get("mode") == "plan":
            blocks.append({"type": "text", "text": "[MODO PLAN activo: investiga con herramientas de lectura, "
                           "pregunta lo necesario y presenta un plan concreto (pasos, entregables, supuestos). "
                           "No modifiques archivos hasta que el usuario escriba /ejecutar.]"})
        loaded = self.ctx.state.setdefault("skills_loaded", [])
        for d in SK.match_skills(self.s, text):
            if d["name"] in loaded:
                continue
            loaded.append(d["name"])
            blocks.append({"type": "text", "text": f"<habilidad nombre=\"{d['name']}\">\n{d['body']}\n</habilidad>"})
        return blocks

    def rewind(self, turn: int, restore_files: bool = True) -> dict:
        """Vuelve la conversación al momento ANTES del turno indicado (patrón de Cline: restaurar
        tarea, archivos o ambos). Solo se quita lo posterior: el prefijo no se edita."""
        marks = [m for m in self.ctx.state.get("marks", []) if m["turn"] == turn]
        if not marks:
            raise ValueError("No existe ese turno en esta sesión.")
        m = marks[0]
        restored = []
        if restore_files:
            for t in sorted({mm["turn"] for mm in self.ctx.state.get("marks", []) if mm["turn"] >= turn}, reverse=True):
                restored += self._undo_turn(t)
        self.messages = self.messages[:m["msg"]]
        self.transcript = self.transcript[:m["tr"]]
        self.ctx.state["marks"] = [mm for mm in self.ctx.state["marks"] if mm["turn"] < turn]
        self.ctx.state["turn"] = turn - 1
        self.ctx.state["mode"] = m.get("mode", "normal")   # el modo que había en ese momento
        self.save()
        return {"restored": restored, "messages": len(self.messages)}

    def _undo_turn(self, t: int) -> list[str]:
        import shutil
        d = self.s.ws / ".checkpoints" / self.session_id / str(t)
        man = d / "manifest.json"
        if not man.exists():
            return []
        data = json.loads(man.read_text("utf-8"))
        out = []
        for rel, backup in data.items():
            target = self.s.ws / rel
            if backup is None:
                if target.exists():
                    target.unlink()
                out.append(f"borrado {rel}")
            else:
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(d / backup, target)
                out.append(f"restaurado {rel}")
        shutil.rmtree(d, ignore_errors=True)
        return out

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
        """Llamada al modelo con recuperación: funciones beta opcionales que la API rechace se
        desactivan solas, y los fallos transitorios (red cortada a mitad del stream, sobrecarga 529,
        5xx) se reintentan con backoff exponencial y jitter (patrón de codex/opencode/Cline).
        El SDK ya reintenta 429/5xx antes de empezar a recibir; esto cubre los cortes a mitad."""
        import random

        import anthropic
        delay, attempt = 2.0, 0
        while True:
            try:
                return self.llm.turn(self.messages, tools, self._emit)
            except anthropic.BadRequestError as e:
                msg = str(getattr(e, "message", e)).lower()
                if "context_management" in msg or "compact" in msg or "clear_tool_uses" in msg:
                    if getattr(self.llm, "context_editing", False):
                        self.llm.context_editing = False     # primero se quita la limpieza…
                        continue
                    if getattr(self.llm, "compaction", False):
                        self.llm.compaction = False          # …y después la compactación
                        continue
                if getattr(self.llm, "progress_updates", False) and ("display" in msg or "thinking-display" in msg):
                    self.llm.progress_updates = False
                    continue
                raise
            except (anthropic.APIConnectionError, anthropic.InternalServerError) as e:
                attempt += 1
                if attempt > 5 or self._cancel:
                    raise
                self._emit({"type": "status", "text": f"Conexión inestable, reintentando ({attempt}/5)…"})
                time.sleep(delay * random.uniform(0.9, 1.1))
                delay = min(delay * 2, 30)
            except anthropic.APIStatusError as e:
                if getattr(e, "status_code", 0) == 529 and attempt < 5 and not self._cancel:   # sobrecarga
                    attempt += 1
                    self._emit({"type": "status", "text": f"Servicio saturado, reintentando ({attempt}/5)…"})
                    time.sleep(delay * random.uniform(0.9, 1.1))
                    delay = min(delay * 2, 30)
                    continue
                raise

    def _track_usage(self, resp) -> None:
        u = getattr(resp, "usage", None)
        if u is not None:
            self.usage["input"] += getattr(u, "input_tokens", 0) or 0
            self.usage["output"] += getattr(u, "output_tokens", 0) or 0
            self.usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
            for it in (getattr(u, "iterations", None) or []):   # tokens de la compactación (si la hubo)
                if getattr(it, "type", "") == "compaction":
                    self.usage["input"] += getattr(it, "input_tokens", 0) or 0
                    self.usage["output"] += getattr(it, "output_tokens", 0) or 0
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
        def safe(b):
            n, inp = _attr(b, "name"), _attr(b, "input") or {}
            return n in self.PARALLEL_SAFE or (n == "delegate" and isinstance(inp, dict) and inp.get("scope") != "escritura")
        if len(tool_uses) > 1 and not truncated and all(safe(b) for b in tool_uses):
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=min(6, len(tool_uses))) as ex:
                return list(ex.map(self._run_tool, tool_uses))   # map conserva el orden
        return [self._run_tool(b, truncated=truncated) for b in tool_uses]

    def _stuck_check(self, name: str, inp) -> str | None:
        """Detector de atascos (patrones de OpenHands stuck_detector y gemini-cli loopDetection):
        misma llamada repetida, ciclos A-B-A-B / A-B-C-A-B-C y errores seguidos de la misma herramienta.
        1.ª y 2.ª vez: aviso al modelo para que cambie de estrategia; 3.ª: se detiene la tarea."""
        if name in ("ask_user", "todo_write"):
            return None
        sig = name + json.dumps(inp, sort_keys=True, ensure_ascii=False)[:4000]
        sigs = getattr(self, "_sigs", [])
        sigs.append(sig)
        self._sigs = sigs
        calls = getattr(self, "_calls", {})
        calls[sig] = calls.get(sig, 0) + 1
        self._calls = calls
        reason = None
        for k in (2, 3):   # ciclos A-B-A-B-A-B / A-B-C x3 (más informativo que "misma llamada")
            tail = sigs[-3 * k:]
            if len(tail) == 3 * k and len(set(tail[:k])) == k and tail[:k] == tail[k:2 * k] == tail[2 * k:]:
                reason = f"Estás repitiendo un ciclo de {k} llamadas sin avanzar."
                break
        if not reason and calls[sig] >= 3:
            reason = "Es la tercera vez que haces exactamente esta misma llamada en esta tarea."
        if not reason and getattr(self, "_err_streak", {}).get(name, 0) >= 3:
            reason = f"'{name}' ha fallado 3 veces seguidas."
        if not reason:
            return None
        self._nudges = getattr(self, "_nudges", 0) + 1
        if self._nudges >= 3:
            self._cancel = True
            self._emit({"type": "error", "text": "El agente parecía atascado repitiendo acciones y se detuvo. "
                                                 "Prueba a reformular la petición o a dar más detalles."})
            return reason + " Tarea detenida por posible bucle."
        return (reason + " No sigas por ese camino: cambia de estrategia (otros parámetros, otra "
                "herramienta, revisa el error) o, si te falta información, pregunta con ask_user.")

    def _run_tool(self, block, truncated: bool = False) -> dict:
        name, tid, inp = _attr(block, "name"), _attr(block, "id"), _attr(block, "input")
        self._emit({"type": "tool_start", "id": tid, "name": name, "input": _preview_input(inp)})
        t0 = time.time()
        tool = REGISTRY.get(name)
        try:
            if tool is None:
                raise ToolError(f"Herramienta desconocida: {name}")
            if self.allowed_tools is not None and name not in self.allowed_tools:
                raise ToolError(f"La herramienta '{name}' no está disponible para este agente.")
            if self.ctx.state.get("mode") == "plan" and name not in PLAN_TOOLS:
                raise ToolError("MODO PLAN: solo puedes investigar (leer, ver, buscar) y preguntar. Presenta el "
                                "plan al usuario; cuando lo apruebe (él escribirá /ejecutar) podrás modificar archivos.")
            stuck = self._stuck_check(name, inp)
            if stuck:
                raise ToolError(stuck)
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

        streak = self._err_streak if hasattr(self, "_err_streak") else {}
        streak[name] = streak.get(name, 0) + 1 if result.is_error else 0
        self._err_streak = streak
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
