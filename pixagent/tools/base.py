"""Infraestructura común de herramientas: registro, contexto, resultados y rutas seguras."""
from __future__ import annotations

import base64
import io
import mimetypes
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PIL import Image

try:  # fotos HEIC de iPhone/iPad (opcional: pip install pillow-heif)
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

MAX_TEXT = 40_000          # caracteres máximos de texto devuelto al modelo por herramienta
MAX_IMAGE_SIDE = 1568      # lado máximo de imagen enviada al modelo (px)


class ToolError(Exception):
    """Error 'esperado' de una herramienta: se devuelve al modelo como is_error."""


@dataclass
class ToolResult:
    text: str = ""
    images: list[Path] = field(default_factory=list)   # imágenes que el modelo debe VER
    files: list[Path] = field(default_factory=list)    # archivos producidos (se muestran en la UI)
    is_error: bool = False
    data: dict[str, Any] = field(default_factory=dict)  # extra para la UI (p.ej. todos)


@dataclass
class ToolContext:
    settings: Any                                  # config.Settings
    emit: Callable[[dict], None] = lambda e: None  # eventos hacia la UI
    approve: Callable[[str, dict], bool] = lambda name, inp: True
    # Pregunta al usuario y espera su respuesta (la UI muestra opciones + texto libre). Devuelve el texto
    # de la respuesta o None si no hay interfaz/no respondió.
    ask: Callable[[str, list, bool], str | None] = lambda question, options, multi: None
    session_id: str = "default"
    state: dict[str, Any] = field(default_factory=dict)  # estado por sesión (todos, etc.)

    @property
    def ws(self) -> Path:
        return self.settings.ws

    # ---- rutas -----------------------------------------------------------
    def resolve(self, path: str | Path, *, must_exist: bool = False) -> Path:
        """Resuelve una ruta relativa al workspace y comprueba que esté permitida."""
        if path is None or str(path).strip() == "":
            raise ToolError("Ruta vacía.")
        p = Path(str(path)).expanduser()
        if not p.is_absolute():
            p = self.ws / p
        p = p.resolve()
        if self.settings.permission_mode != "full":
            roots = [self.ws] + [Path(d).expanduser().resolve() for d in self.settings.allowed_dirs]
            if not any(_is_relative_to(p, r) for r in roots):
                raise ToolError(
                    f"Ruta fuera del workspace no permitida: {p}. "
                    f"Usa rutas dentro de {self.ws} o añade la carpeta a allowed_dirs.")
        if must_exist and not p.exists():
            raise ToolError(f"No existe: {self.rel(p)}")
        return p

    # ---- puntos de control (deshacer) -----------------------------------
    def checkpoint(self, p: Path) -> None:
        """Guarda el estado previo de un archivo antes de modificarlo, por turno del usuario.
        'Deshacer' restaura los archivos de ese turno (y borra los que el turno creó)."""
        import json as _json
        import shutil as _shutil
        turn = self.state.get("turn", 0)
        d = self.ws / ".checkpoints" / self.session_id / str(turn)
        man = d / "manifest.json"
        try:
            data = _json.loads(man.read_text("utf-8")) if man.exists() else {}
            rel = self.rel(p)
            if rel in data:
                return  # ya guardado en este turno: conservar el estado ORIGINAL
            d.mkdir(parents=True, exist_ok=True)
            if p.exists() and p.is_file():
                if p.stat().st_size > 50_000_000:
                    return
                backup = d / f"{len(data):04d}_{p.name}"
                _shutil.copy2(p, backup)
                data[rel] = backup.name
            else:
                data[rel] = None  # archivo nuevo: deshacer = borrarlo
            man.write_text(_json.dumps(data, ensure_ascii=False), "utf-8")
        except OSError:
            pass

    def rel(self, p: Path) -> str:
        try:
            return p.resolve().relative_to(self.ws).as_posix()
        except ValueError:
            return str(p)


def _is_relative_to(p: Path, root: Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


@dataclass
class Tool:
    name: str
    description: str
    input_schema: dict
    func: Callable[..., ToolResult]
    needs_approval: Callable[[Any], bool] = lambda settings: False

    def spec(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema,
            # Las entradas grandes (código, HTML, markdown) se transmiten mientras se generan.
            "eager_input_streaming": True,
        }


REGISTRY: dict[str, Tool] = {}


def tool(name: str, description: str, schema: dict,
         needs_approval: Callable[[Any], bool] | None = None):
    """Decorador para registrar herramientas."""
    schema = {"type": "object", **schema}
    schema.setdefault("properties", {})

    def deco(fn: Callable[..., ToolResult]):
        REGISTRY[name] = Tool(name, description.strip(), schema, fn,
                              needs_approval or (lambda s: False))
        return fn
    return deco


def validate_input(t: Tool, inp: Any) -> str | None:
    """Validación mínima (eager streaming no valida en servidor). Devuelve mensaje de error o None."""
    if not isinstance(inp, dict):
        return "La entrada de la herramienta no es un objeto JSON válido (¿salida truncada?)."
    for req in t.input_schema.get("required", []):
        if req not in inp:
            return f"Falta el parámetro obligatorio '{req}'."
    props = t.input_schema.get("properties", {})
    pytypes = {"string": str, "integer": int, "number": (int, float), "boolean": bool,
               "array": list, "object": dict}
    for k, v in inp.items():
        typ = props.get(k, {}).get("type")
        if isinstance(typ, str) and typ in pytypes and v is not None:
            if typ in ("integer", "number") and isinstance(v, bool):
                return f"'{k}' debe ser {typ}."
            if not isinstance(v, pytypes[typ]):
                return f"'{k}' debe ser de tipo {typ}."
    return None


def truncate(text: str, limit: int = MAX_TEXT) -> str:
    if len(text) <= limit:
        return text
    half = limit // 2
    return text[:half] + f"\n\n[... {len(text) - limit} caracteres omitidos ...]\n\n" + text[-half:]


# ---- imágenes -------------------------------------------------------------
def image_block(path: Path, max_side: int = MAX_IMAGE_SIDE) -> dict:
    """Convierte una imagen local en un bloque 'image' (base64) redimensionado para el modelo."""
    with Image.open(path) as im:
        im.load()
        if im.mode in ("RGBA", "LA", "P"):
            bg = Image.new("RGB", im.size, "white")
            rgba = im.convert("RGBA")
            bg.paste(rgba, mask=rgba.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")
        im.thumbnail((max_side, max_side))
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return {"type": "image",
            "source": {"type": "base64", "media_type": "image/jpeg",
                       "data": base64.standard_b64encode(buf.getvalue()).decode()}}


def document_block(path: Path) -> dict:
    return {"type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                       "data": base64.standard_b64encode(path.read_bytes()).decode()},
            "title": path.name}


def guess_kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp", ".svg", ".heic", ".heif"):
        return "image"
    if ext == ".pdf":
        return "pdf"
    if ext in (".html", ".htm"):
        return "html"
    mt = mimetypes.guess_type(path.name)[0] or ""
    if mt.startswith("text/") or ext in (".py", ".js", ".json", ".md", ".css", ".csv", ".txt"):
        return "text"
    return "file"
