"""Memoria jerárquica, habilidades (skills) y recetas (/comandos).

- MEMORIA: ~/.pixagent/PIXAGENT.md (global del usuario) + <workspace>/PIXAGENT.md, en ese orden
  (patrón AGENTS.md de codex/opencode; lo más específico al final manda).
- HABILIDADES: conocimiento experto en Markdown con cabecera (`---`): name, description, keywords.
  En el prompt solo va un catálogo de una línea por habilidad (divulgación progresiva). Si las
  palabras clave aparecen en el mensaje, el cuerpo se adjunta a ese mensaje (no al prompt de
  sistema: no rompe la caché); si no, el agente la pide con `load_skill` (OpenHands/Codewhale).
- RECETAS: tareas reutilizables con parámetros (Goose recipes) que se lanzan con `/nombre` en el
  chat. Si falta un dato obligatorio, el agente lo pregunta con ask_user.
Integradas: pixagent/library/{skills,recipes}; del usuario: <workspace>/skills y <workspace>/recetas.
"""
from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from .config import CONFIG_DIR

LIB = Path(__file__).parent / "library"


def _norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9/ ]+", " ", t)


def parse_md(path: Path) -> dict:
    text = path.read_text("utf-8")
    meta, body = {}, text
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if m:
        body = m.group(2)
        for line in m.group(1).splitlines():
            if ":" in line:
                k, _, v = line.partition(":")
                v = v.strip().strip("[]")
                meta[k.strip().lower()] = v
    meta.setdefault("name", path.stem)
    meta["body"] = body.strip()
    meta["path"] = str(path)
    for key in ("keywords", "parametros", "parameters"):
        if key in meta:
            meta[key] = [x.strip().strip("'\"") for x in meta[key].split(",") if x.strip()]
    return meta


def _collect(settings, kind: str) -> dict[str, dict]:
    sub = {"skills": ("skills", "skills"), "recipes": ("recipes", "recetas")}[kind]
    out: dict[str, dict] = {}
    for root in (LIB / sub[0], settings.ws / sub[1]):
        if root.exists():
            for f in sorted(root.glob("*.md")):
                try:
                    d = parse_md(f)
                except Exception:  # noqa: BLE001
                    continue
                d["builtin"] = root.is_relative_to(LIB)
                out[d["name"]] = d   # las del usuario sustituyen a las integradas con el mismo nombre
    return out


def skills(settings) -> dict[str, dict]:
    return _collect(settings, "skills")


def recipes(settings) -> dict[str, dict]:
    return _collect(settings, "recipes")


# ------------------------------------------------------------------ memoria
def load_memory(settings, limit: int = 16000) -> str:
    parts = []
    for label, f in (("Global del usuario", CONFIG_DIR / "PIXAGENT.md"), ("Proyecto", settings.ws / "PIXAGENT.md")):
        if f.exists():
            t = f.read_text("utf-8").strip()
            if t:
                parts.append(f"<!-- {label}: {f} -->\n{t}")
    return "\n\n".join(parts)[:limit]


# ------------------------------------------------------------------ habilidades
def catalog_text(settings) -> str:
    sk = skills(settings)
    rc = recipes(settings)
    lines = []
    if sk:
        lines.append("# Habilidades disponibles (cárgalas con load_skill cuando la tarea lo requiera)")
        lines += [f"- {d['name']}: {d.get('description', '')}" for d in sk.values()]
    if rc:
        lines.append("\n# Recetas del usuario (el usuario las lanza con /nombre)")
        lines += [f"- /{d['name']}: {d.get('description', '')}" for d in rc.values()]
    return "\n".join(lines)


def match_skills(settings, text: str, limit: int = 2) -> list[dict]:
    """Habilidades cuyas palabras clave aparecen como palabras completas en el mensaje."""
    words = f" {_norm(text)} "
    hits = []
    for d in skills(settings).values():
        for kw in d.get("keywords", []):
            if kw and f" {_norm(kw).strip()} " in words:
                hits.append(d)
                break
    return hits[:limit]


# ------------------------------------------------------------------ recetas (/comandos)
def expand_recipe(settings, text: str) -> tuple[str, dict] | None:
    """'/nombre resto clave=valor' → (prompt expandido, receta). None si no es una receta."""
    m = re.match(r"^/([\w\-áéíóúñ]+)\s*(.*)$", text.strip(), re.S)
    if not m:
        return None
    rc = recipes(settings).get(m.group(1))
    if not rc:
        return None
    rest = m.group(2)
    values = dict(re.findall(r"(\w+)=(\"[^\"]*\"|\S+)", rest))
    values = {k: v.strip('"') for k, v in values.items()}
    free = re.sub(r"(\w+)=(\"[^\"]*\"|\S+)", "", rest).strip()
    params = rc.get("parametros") or rc.get("parameters") or []
    names = [p.rstrip("*") for p in params]
    if free and names and names[0] not in values:
        values[names[0]] = free
    body = rc["body"]
    for k, v in values.items():
        body = body.replace("{{" + k + "}}", v)
    missing = [p.rstrip("*") for p in params if p.endswith("*") and p.rstrip("*") not in values]
    body = re.sub(r"\{\{(\w+)\}\}", lambda mm: f"[{mm.group(1)}: por definir]", body)
    if missing:
        body += ("\n\n(Faltan estos datos obligatorios: " + ", ".join(missing) +
                 ". Pregúntalos con ask_user antes de empezar, uno por pregunta si hace falta.)")
    if free and names and names[0] in values and values[names[0]] != free:
        body += f"\n\nIndicaciones adicionales del usuario: {free}"
    return f"[Receta /{rc['name']}]\n{body}", rc
