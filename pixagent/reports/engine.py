"""Motor de informes estructurados y extensos.

Cómo genera informes largos (p. ej. 100 páginas) sin perder calidad ni desbordar el contexto,
con el patrón de los agentes de escritura larga (Claude Code con subagentes, LongWriter/AgentWrite,
STORM):

1. PLANTILLA: estructura definida por el usuario (secciones, campos, instrucciones, extensión).
2. EXPANSIÓN en UNIDADES de trabajo: una por sección de IA, una por zona/grupo de fotos (per_group),
   o un ÍNDICE generado por IA (auto_outline) que luego se divide en un apartado por unidad.
3. REDACCIÓN por unidad en llamadas SEPARADAS y en paralelo. Cada llamada solo recibe lo que
   necesita: datos del proyecto, notas, instrucciones, SUS fotos y resúmenes de las secciones de las
   que depende. Así cada parte se escribe con calidad y el coste no crece con el tamaño del informe.
4. ESTADO EN DISCO: cada unidad se guarda al terminar en sections/*.md; se puede reanudar, editar a
   mano o regenerar una sola parte.
5. ENSAMBLADO determinista a Markdown → PDF (portada, índice, tablas, fotos, panel fotográfico).
   Las partes sin IA (tabla de datos, panel fotográfico, firma) no gastan tokens.
"""
from __future__ import annotations

import json
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import date
from pathlib import Path
from typing import Callable

BUILTIN_TEMPLATES = Path(__file__).parent / "templates"
WORDS_PER_PAGE = 450          # página A4 de texto técnico (10,5 pt) con títulos y tablas
PHOTOS_PER_GROUP = 6
PRICES = {  # USD por millón de tokens (entrada, salida), referencia para estimaciones
    "claude-fable-5-1": (10.0, 50.0), "claude-opus-5-5": (4.0, 20.0), "claude-opus-5": (5.0, 25.0),
    "claude-sonnet-5-5": (2.0, 10.0), "claude-haiku-5-5": (0.10, 0.50),
}

WRITER_SYSTEM = """Eres un redactor técnico profesional que escribe UNA parte de un informe más grande.
Reglas:
- Escribe en español formal y técnico, claro y concreto. Respeta la extensión pedida.
- Devuelve SOLO el contenido en Markdown de esta parte: párrafos, listas, tablas con | ... |,
  y subtítulos de nivel ### o inferior. NO repitas el título de la parte (ya lo pone el sistema)
  ni uses # o ##.
- Cita las fotos como "Foto N" usando la numeración indicada. No insertes imágenes.
- No inventes datos (medidas, fechas, nombres, cifras). Si falta algo, escribe
  [POR COMPLETAR: qué falta]. Puedes describir lo que se ve en las fotos.
- Mantén coherencia con los resúmenes de otras secciones que se te den."""

OUTLINE_SYSTEM = """Eres un editor técnico. Diseñas el índice detallado de un informe extenso.
Devuelve SOLO JSON válido con esta forma:
{"chapters":[{"title":"...","sections":[{"title":"...","brief":"qué debe cubrir (2-3 frases)","words":N,"photos":[números de foto relevantes]}]}]}
La suma de "words" debe aproximarse al objetivo indicado. Apartados de 300 a 1500 palabras.
Asigna cada foto al apartado donde más aporte (puede quedar sin asignar)."""


# ============================================================ modelos de datos
@dataclass
class Unit:
    id: str
    section_id: str
    title: str
    kind: str                       # ai | per_group | auto_part | fields_table | photo_grid | static
    level: int = 1                  # 1 = título de capítulo, 2 = subapartado
    chapter: str = ""               # título del capítulo padre (para level 2)
    instructions: str = ""
    words: int = 400
    photos: list[int] = field(default_factory=list)   # índices 0-based en project.photos
    depends_on: list[str] = field(default_factory=list)
    uses_ai: bool = True


def slug(s: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")[:40] or "x"


# ============================================================ plantillas
class Templates:
    def __init__(self, ws: Path):
        self.user_dir = ws / "report_templates"
        self.user_dir.mkdir(parents=True, exist_ok=True)

    def list(self) -> list[dict]:
        out = {}
        for builtin, d in ((True, BUILTIN_TEMPLATES), (False, self.user_dir)):
            for f in sorted(d.glob("*.json")):
                try:
                    t = json.loads(f.read_text("utf-8"))
                except json.JSONDecodeError:
                    continue
                t["builtin"] = builtin
                out[t.get("id", f.stem)] = t
        return list(out.values())

    def get(self, tid: str) -> dict:
        for t in self.list():
            if t.get("id") == tid:
                return t
        raise KeyError(f"Plantilla no encontrada: {tid}")

    def save(self, t: dict) -> dict:
        validate_template(t)
        t = {k: v for k, v in t.items() if k != "builtin"}
        t["id"] = t.get("id") or slug(t["name"])
        if (BUILTIN_TEMPLATES / f"{t['id']}.json").exists():
            t["id"] = t["id"] + "-mia"   # no sobrescribir una integrada: se guarda como copia
        (self.user_dir / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=2), "utf-8")
        return t

    def delete(self, tid: str) -> None:
        f = self.user_dir / f"{tid}.json"
        if f.exists():
            f.unlink()


KINDS = {"ai", "per_group", "auto_outline", "fields_table", "photo_grid", "static", "table"}


def validate_template(t: dict) -> None:
    if not t.get("name"):
        raise ValueError("La plantilla necesita 'name'.")
    secs = t.get("sections") or []
    if not secs:
        raise ValueError("La plantilla necesita al menos una sección.")
    ids = set()
    for s in secs:
        if s.get("kind") not in KINDS:
            raise ValueError(f"Tipo de sección no válido: {s.get('kind')} (válidos: {', '.join(sorted(KINDS))})")
        s.setdefault("id", slug(s.get("title") or s["kind"]))
        if s["id"] in ids:
            raise ValueError(f"Id de sección repetido: {s['id']}")
        ids.add(s["id"])


# ============================================================ escritor (LLM)
class ClaudeWriter:
    """Una llamada por unidad. Sin herramientas: barato y paralelizable."""

    def __init__(self, settings, model: str | None = None):
        self.s = settings
        self.model = model or settings.model
        self._client = None

    @property
    def client(self):
        if self._client is None:
            import anthropic
            from ..anthropic_client import make_client
            self._client = make_client(self.s)
        return self._client

    def write(self, system: str, content: list[dict], max_tokens: int) -> tuple[str, dict]:
        params = dict(model=self.model, max_tokens=max_tokens, system=system,
                      messages=[{"role": "user", "content": content}],
                      output_config={"effort": "medium"})
        if self.s.server_fallbacks and self.model.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")):
            with self.client.beta.messages.stream(**params, fallbacks="default",
                                                  betas=["server-side-fallback-2026-07-01"]) as st:
                resp = st.get_final_message()
        else:
            with self.client.messages.stream(**params) as st:
                resp = st.get_final_message()
        if resp.stop_reason == "refusal":
            raise RuntimeError("El modelo rechazó redactar esta parte.")
        text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
        return text, {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}


# ============================================================ proyecto de informe
class ReportProject:
    def __init__(self, ws: Path, rid: str):
        self.ws = ws
        self.id = rid
        self.dir = ws / "reports" / rid
        self.file = self.dir / "project.json"
        self.lock = threading.RLock()
        self.data = json.loads(self.file.read_text("utf-8")) if self.file.exists() else {}

    # ---- persistencia
    @classmethod
    def create(cls, ws: Path, template: dict, title: str, fields: dict | None = None, notes: str = "",
               photos: list | None = None, target_pages: int | None = None, model: str | None = None) -> "ReportProject":
        rid = f"{date.today():%Y%m%d}-{slug(title)}-{uuid.uuid4().hex[:4]}"
        p = cls(ws, rid)
        p.dir.mkdir(parents=True, exist_ok=True)
        (p.dir / "sections").mkdir(exist_ok=True)
        p.data = {"id": rid, "title": title, "template": template, "fields": fields or {}, "notes": notes,
                  "photos": [_norm_photo(x) for x in photos or []], "target_pages": target_pages,
                  "model": model, "units": {}, "outline": None, "created": time.time(), "updated": time.time(),
                  "usage": {"input": 0, "output": 0}, "outputs": {}, "tables": {}, "anexos": []}
        p.save()
        return p

    def save(self) -> None:
        with self.lock:
            self.data["updated"] = time.time()
            tmp = self.file.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), "utf-8")
            tmp.replace(self.file)

    def update(self, **kw) -> None:
        with self.lock:
            for k in ("title", "fields", "notes", "target_pages", "model", "template", "tables", "anexos", "obra"):
                if k in kw and kw[k] is not None:
                    self.data[k] = kw[k]
            if kw.get("photos") is not None:
                self.data["photos"] = [_norm_photo(x) for x in kw["photos"]]
            if kw.get("outline") is not None:
                self.data["outline"] = kw["outline"]
            self.save()

    @property
    def template(self) -> dict:
        return self.data["template"]

    def section_file(self, uid: str) -> Path:
        return self.dir / "sections" / f"{uid}.md"

    # ---- expansión en unidades
    def groups(self) -> list[tuple[str, list[int]]]:
        photos = self.data["photos"]
        named: dict[str, list[int]] = {}
        loose = []
        for i, ph in enumerate(photos):
            g = (ph.get("group") or "").strip()
            (named.setdefault(g, []) if g else loose).append(i)
        out = list(named.items())
        for k in range(0, len(loose), PHOTOS_PER_GROUP):
            out.append((f"Grupo {len(out) + 1}", loose[k:k + PHOTOS_PER_GROUP]))
        return out

    def units(self) -> list[Unit]:
        res: list[Unit] = []
        for sec in self.template["sections"]:
            kind, sid = sec["kind"], sec["id"]
            title = sec.get("title", "")
            if kind == "ai":
                res.append(Unit(sid, sid, title, "ai", instructions=sec.get("instructions", ""),
                                words=int(sec.get("words", 400)), depends_on=sec.get("depends_on", []),
                                photos=list(range(len(self.data["photos"]))) if sec.get("photos") else []))
            elif kind == "per_group":
                groups = self.groups()
                res.append(Unit(sid, sid, title, "heading", uses_ai=False))
                for gname, idx in groups:
                    res.append(Unit(f"{sid}__{slug(gname)}", sid, gname, "per_group", level=2, chapter=title,
                                    instructions=sec.get("instructions", ""), words=int(sec.get("words", 400)),
                                    photos=idx if sec.get("photos", True) else []))
            elif kind == "auto_outline":
                outline = self.data.get("outline")
                if not outline:
                    res.append(Unit(f"{sid}__outline", sid, "Índice propuesto", "outline",
                                    instructions=sec.get("instructions", "")))
                    continue
                for ci, ch in enumerate(outline.get("chapters", [])):
                    res.append(Unit(f"{sid}__c{ci + 1}", sid, ch["title"], "heading", uses_ai=False))
                    for si, s in enumerate(ch.get("sections", [])):
                        res.append(Unit(f"{sid}__c{ci + 1}s{si + 1}", sid, s["title"], "auto_part", level=2,
                                        chapter=ch["title"], instructions=s.get("brief", ""),
                                        words=int(s.get("words", 600)),
                                        photos=[n - 1 for n in s.get("photos", []) if 0 < n <= len(self.data["photos"])]))
            else:  # deterministas: no gastan tokens
                res.append(Unit(sid, sid, title, kind, uses_ai=False))
        return res

    def ai_units(self) -> list[Unit]:
        return [u for u in self.units() if u.uses_ai]

    def status(self) -> dict:
        units = self.units()
        st = self.data.get("units", {})
        return {"units": [{**asdict(u), "status": st.get(u.id, {}).get("status", "pending" if u.uses_ai else "auto"),
                           "error": st.get(u.id, {}).get("error"), "edited": st.get(u.id, {}).get("edited", False),
                           "words_written": st.get(u.id, {}).get("words", 0)} for u in units],
                "needs_outline": any(u.kind == "outline" for u in units)}

    def set_unit(self, uid: str, **kw) -> None:
        with self.lock:
            self.data.setdefault("units", {}).setdefault(uid, {}).update(kw)
            self.save()

    # ---- estimación de coste
    def estimate(self) -> dict:
        model = self.data.get("model") or "claude-opus-5-5"
        pin, pout = PRICES.get(model, PRICES["claude-opus-5-5"])
        calls, tin, tout = 0, 0, 0
        target_words = None
        for u in self.ai_units():
            if self.data["units"].get(u.id, {}).get("status") == "done":
                continue
            calls += 1
            if u.kind == "outline":
                target_words = (self.data.get("target_pages") or 20) * WORDS_PER_PAGE
                tin += 2500 + 200 * len(self.data["photos"])
                tout += 2500
                # además, las partes que saldrán del índice
                parts = max(1, target_words // 800)
                calls += parts
                tin += parts * 3500
                tout += int(target_words * 1.7)
            else:
                tin += 2500 + 1100 * len(u.photos) + (1500 if u.depends_on else 0)
                tout += int(u.words * 1.7) + 400
        # el razonamiento interno también se factura como salida: margen del 50 %
        tout = int(tout * 1.5)
        return {"model": model, "calls": calls, "input_tokens": tin, "output_tokens": tout,
                "usd": round(tin / 1e6 * pin + tout / 1e6 * pout, 2),
                "pages_estimate": round(self.estimated_words(target_words) / WORDS_PER_PAGE + len(self.data["photos"]) / 6, 1)}

    def estimated_words(self, target_words=None) -> int:
        if target_words:
            return target_words
        return sum(u.words for u in self.ai_units())


def _norm_photo(x) -> dict:
    if isinstance(x, str):
        return {"path": x, "caption": "", "group": "", "notes": "", "status": ""}
    return {"path": x["path"], "caption": x.get("caption", ""), "group": x.get("group", ""),
            "notes": x.get("notes", ""), "status": x.get("status", "")}


# ============================================================ generación
class ReportGenerator:
    def __init__(self, settings, project: ReportProject, writer=None,
                 emit: Callable[[dict], None] | None = None, workers: int = 3):
        self.s = settings
        self.p = project
        self.writer = writer or ClaudeWriter(settings, project.data.get("model"))
        self.emit = emit or (lambda e: None)
        self.workers = workers
        self.cancelled = False

    def _ev(self, **kw):
        self.emit({"type": "report_progress", "report": self.p.id, **kw})

    # ---- contexto común
    def _context_text(self) -> str:
        d = self.p.data
        fields = "\n".join(f"- {f.get('label', f['key'])}: {d['fields'].get(f['key'], '') or '[sin dato]'}"
                           for f in self.p.template.get("fields", []))
        photos = "\n".join(f"- Foto {i + 1}: {ph.get('caption') or '(sin pie)'}"
                           + (f" [zona: {ph['group']}]" if ph.get("group") else "")
                           + (f" [estado: {ph['status']}]" if ph.get("status") else "")
                           + (f" — nota: {ph['notes']}" if ph.get("notes") else "")
                           for i, ph in enumerate(d["photos"]))
        tables = ""
        for key, rows in (d.get("tables") or {}).items():
            if rows:
                tables += f"\n[{key}] " + " || ".join(" | ".join(map(str, r)) for r in rows[:15])
                tables += f" … ({len(rows) - 1} filas)" if len(rows) > 15 else ""
        anexos = "\n".join(f"- {a.get('title') or a['path']}" for a in d.get("anexos") or [])
        return (f"INFORME: {d['title']}\nTIPO: {self.p.template.get('name')}\n\nDATOS DEL PROYECTO:\n{fields or '-'}\n\n"
                f"NOTAS DEL USUARIO:\n{d.get('notes') or '-'}\n\nFOTOS DISPONIBLES:\n{photos or '-'}"
                + (f"\n\nCUADROS ENTREGADOS POR EL EQUIPO (extracto):{tables}" if tables else "")
                + (f"\n\nANEXOS ADJUNTOS AL FINAL DEL PDF:\n{anexos}" if anexos else ""))

    def _summaries(self, deps: list[str]) -> str:
        if not deps:
            return ""
        out = []
        for u in self.p.units():
            if not u.uses_ai or u.kind == "outline":
                continue
            if "*" in deps or u.section_id in deps:
                f = self.p.section_file(u.id)
                if f.exists():
                    txt = re.sub(r"\s+", " ", f.read_text("utf-8"))[:900]
                    out.append(f"[{u.chapter + ' › ' if u.chapter else ''}{u.title}] {txt}")
        return "\n\n".join(out)

    def _photo_blocks(self, idx: list[int]) -> list[dict]:
        from ..tools.base import image_block
        blocks = []
        for i in idx[:12]:  # máx. 12 fotos por llamada
            p = (self.p.ws / self.p.data["photos"][i]["path"]).resolve()
            if p.exists():
                blocks.append({"type": "text", "text": f"Foto {i + 1}:"})
                blocks.append(image_block(p, max_side=1024))
        return blocks

    # ---- unidades
    def _write_unit(self, u: Unit) -> None:
        if self.cancelled:
            return
        self.p.set_unit(u.id, status="running", error=None)
        self._ev(unit=u.id, status="running", title=u.title)
        try:
            if u.kind == "outline":
                self._write_outline(u)
            else:
                deps = u.depends_on
                summaries = self._summaries(deps)
                where = f"Parte: «{u.chapter} › {u.title}»" if u.chapter else f"Sección: «{u.title}»"
                fb = self.p.data.get("units", {}).get(u.id, {}).get("feedback")
                prompt = (f"{self._context_text()}\n\n{where}\nInstrucciones: {u.instructions or '-'}\n"
                          + (f"CORRECCIONES DEL USUARIO (obligatorias, prevalecen sobre lo anterior): {fb}\n" if fb else "")
                          + f"Extensión objetivo: ~{u.words} palabras.\n"
                          + (f"Fotos de esta parte: {', '.join(f'Foto {i + 1}' for i in u.photos)}\n" if u.photos else "")
                          + (f"\nRESÚMENES DE OTRAS SECCIONES (para coherencia):\n{summaries}\n" if summaries else "")
                          + "\nRedacta ahora esta parte.")
                content = self._photo_blocks(u.photos) + [{"type": "text", "text": prompt}]
                text, usage = self.writer.write(WRITER_SYSTEM, content, max_tokens=min(32000, max(2000, int(u.words * 3) + 1500)))
                text = re.sub(r"^\s*#{1,2}\s+.*\n", "", text)  # por si repite el título
                self.p.section_file(u.id).write_text(text, "utf-8")
                self._add_usage(usage)
                self.p.set_unit(u.id, status="done", words=len(text.split()), edited=False)
            self._ev(unit=u.id, status="done", title=u.title)
        except Exception as e:  # noqa: BLE001
            self.p.set_unit(u.id, status="error", error=str(e)[:500])
            self._ev(unit=u.id, status="error", title=u.title, error=str(e)[:300])

    def _write_outline(self, u: Unit) -> None:
        target = (self.p.data.get("target_pages") or 20) * WORDS_PER_PAGE
        prompt = (f"{self._context_text()}\n\nObjetivo de extensión total: ~{target} palabras "
                  f"(~{self.p.data.get('target_pages') or 20} páginas). Indicaciones: {u.instructions}\n"
                  "Diseña el índice ahora.")
        text, usage = self.writer.write(OUTLINE_SYSTEM, [{"type": "text", "text": prompt}], max_tokens=8000)
        m = re.search(r"\{.*\}", text, re.S)
        outline = json.loads(m.group(0) if m else text)
        if not outline.get("chapters"):
            raise ValueError("El índice generado está vacío.")
        self._add_usage(usage)
        self.p.update(outline=outline)
        self.p.set_unit(u.id, status="done")

    def _add_usage(self, usage: dict) -> None:
        with self.p.lock:
            for k in ("input", "output"):
                self.p.data["usage"][k] = self.p.data["usage"].get(k, 0) + usage.get(k, 0)
            self.p.save()

    # ---- orquestación
    def run(self, only: list[str] | None = None, force: bool = False) -> dict:
        t0 = time.time()
        # fase 0: índice automático (si la plantilla lo usa)
        for u in self.p.units():
            if u.kind == "outline" and (force or self.p.data["units"].get(u.id, {}).get("status") != "done"):
                self._write_outline_unit(u)
        if self.cancelled:
            return self._finish(t0)
        units = [u for u in self.p.ai_units()
                 if (only is None or u.id in only or u.section_id in only)
                 and (force or self.p.data["units"].get(u.id, {}).get("status") != "done"
                      or not self.p.section_file(u.id).exists())
                 and not self.p.data["units"].get(u.id, {}).get("edited")]
        independent = [u for u in units if not u.depends_on]
        dependent = [u for u in units if u.depends_on]
        total = len(units)
        self._ev(status="started", total=total)
        # fase 1: partes independientes en paralelo
        with ThreadPoolExecutor(max_workers=self.workers) as ex:
            list(ex.map(self._write_unit, independent))
        # fase 2: partes que dependen de otras (en el orden de la plantilla; '*' al final)
        dependent.sort(key=lambda u: 1 if "*" in u.depends_on else 0)
        for u in dependent:
            if self.cancelled:
                break
            self._write_unit(u)
        return self._finish(t0)

    def _write_outline_unit(self, u: Unit):
        self._ev(status="outline", title="Diseñando el índice…")
        self._write_unit(u)

    def _finish(self, t0) -> dict:
        st = self.p.status()
        errors = [u for u in st["units"] if u["status"] == "error"]
        res = {"type": "report_done", "report": self.p.id, "seconds": round(time.time() - t0, 1),
               "errors": len(errors), "usage": self.p.data["usage"], "cancelled": self.cancelled}
        self.emit(res)
        return res


# ============================================================ ensamblado
def assemble_markdown(p: ReportProject) -> str:
    d = p.data
    out: list[str] = []
    for u in p.units():
        if u.kind == "outline":
            continue
        if u.kind == "heading":
            out.append(f"\n# {u.title}\n")
            continue
        if u.level == 1 and u.title:
            out.append(f"\n# {u.title}\n")
        elif u.level == 2:
            out.append(f"\n## {u.title}\n")
        if u.kind == "fields_table":
            sec = next((s for s in p.template["sections"] if s["id"] == u.section_id), {})
            keys = sec.get("keys")
            rows = [f"| {f.get('label', f['key'])} | {_cell(d['fields'].get(f['key'], '')) or '—'} |"
                    for f in p.template.get("fields", []) if not keys or f["key"] in keys]
            out.append("| Dato | Valor |\n|---|---|\n" + "\n".join(rows))
        elif u.kind == "photo_grid":
            sec = next((s for s in p.template["sections"] if s["id"] == u.section_id), {})
            if d["photos"]:
                out.append(f":::photos {sec.get('layout', '2x3')}")
                for i, ph in enumerate(d["photos"]):
                    out.append(f"{ph['path']} | Foto {i + 1}. {ph.get('caption', '')}".rstrip())
                out.append(":::")
            else:
                out.append("_(Sin fotos)_")
        elif u.kind == "table":
            sec = next((s for s in p.template["sections"] if s["id"] == u.section_id), {})
            out.append(_table_md(p, sec))
        elif u.kind == "static":
            sec = next((s for s in p.template["sections"] if s["id"] == u.section_id), {})
            txt = sec.get("content", "")
            for k, v in d["fields"].items():
                txt = txt.replace("{{" + k + "}}", str(v))
            out.append(re.sub(r"\{\{\w+\}\}", "", txt))
        else:
            f = p.section_file(u.id)
            if f.exists():
                body = f.read_text("utf-8").strip()
                # fotos de la parte (per_group) en rejilla tras el texto
                if u.kind == "per_group" and u.photos:
                    body += "\n\n:::photos 2x2\n" + "\n".join(
                        f"{d['photos'][i]['path']} | Foto {i + 1}. {d['photos'][i].get('caption', '')}".rstrip() for i in u.photos) + "\n:::"
                out.append(body)
            else:
                out.append(f"_[Sección pendiente de redactar: {u.title}]_")
    return "\n".join(out).strip() + "\n"


def _cell(v) -> str:
    return str(v if v is not None else "").replace("|", "/").replace("\n", " ").strip()


def _table_md(p: ReportProject, sec: dict) -> str:
    """Cuadro con los datos entregados (CSV/Excel) o, si llegó en PDF/imagen, referencia al anexo."""
    d = p.data
    key = sec.get("table") or sec["id"]
    rows = (d.get("tables") or {}).get(key)
    if rows:
        cols = max(len(r) for r in rows[:300])
        body = [[_cell(c) for c in r] + [""] * (cols - len(r)) for r in rows[:300]]
        md = "| " + " | ".join(body[0]) + " |\n|" + "---|" * cols + "\n"
        md += "\n".join("| " + " | ".join(r) + " |" for r in body[1:])
        if len(rows) > 300:
            md += f"\n\n_(Se muestran 300 de {len(rows)} filas; el cuadro completo va en anexos.)_"
        return md
    anexos = [a for a in d.get("anexos") or [] if a.get("key") == key]
    if anexos:
        return "Ver en anexos: " + "; ".join(f"**{a.get('title') or a['path']}**" for a in anexos) + "."
    cols = sec.get("columns") or []
    resp = sec.get("responsable", "")
    return (f"_[CUADRO PENDIENTE{': lo entrega ' + resp if resp else ''}]_"
            + ("\n\n| " + " | ".join(cols) + " |\n|" + "---|" * len(cols) + "\n|" + " |" * len(cols) if cols else ""))


def _append_anexos(settings, pdf: Path, anexos: list[dict], warnings: list[str]) -> None:
    """Añade al final del PDF los entregables en PDF o imagen (escaneados), en el orden de los cuadros."""
    if not anexos:
        return
    try:
        import pymupdf as fitz
    except ImportError:
        warnings.append("Para unir anexos al PDF instala pymupdf; se listan pero no se adjuntan.")
        return
    doc = fitz.open(pdf)
    for a in anexos:
        f = (settings.ws / a["path"]).resolve()
        if not f.exists():
            warnings.append(f"Anexo no encontrado: {a['path']}")
            continue
        try:
            if f.suffix.lower() == ".pdf":
                doc.insert_pdf(fitz.open(f))
            elif f.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"):
                img = fitz.open(f)
                doc.insert_pdf(fitz.open("pdf", img.convert_to_pdf()))
        except Exception as e:  # noqa: BLE001
            warnings.append(f"Anexo {a['path']}: {e}")
    tmp = pdf.with_suffix(".tmp.pdf")
    doc.save(tmp, garbage=3, deflate=True)
    doc.close()
    tmp.replace(pdf)


def build_report_pdf(settings, p: ReportProject) -> Path:
    from ..tools.base import ToolContext
    from ..tools.documents import build_pdf
    md = assemble_markdown(p)
    (p.dir / "informe.md").write_text(md, "utf-8")
    style = p.template.get("style", {})
    d = p.data
    out = p.dir / f"{slug(d['title'])}.pdf"
    ctx = ToolContext(settings=settings)
    warnings: list[str] = []
    author = (d["fields"].get("inspector") or d["fields"].get("autor") or d["fields"].get("residente")
              or d["fields"].get("supervisor") or "")
    build_pdf(ctx, out, md, title=d["title"], subtitle=p.template.get("name", ""), author=author,
              date_text=d["fields"].get("fecha", ""), cover=style.get("cover", True), toc=style.get("toc", True),
              logo=d.get("logo"), cover_image=d["photos"][0]["path"] if d["photos"] and style.get("cover_photo", True) else None,
              header_text=d["title"], theme=style.get("theme_color", "#1f4e79"),
              page_size=style.get("page_size", "A4"), landscape_mode=False, warnings=warnings)
    _append_anexos(settings, out, d.get("anexos") or [], warnings)
    warnings += check_evidence(p)
    with p.lock:
        p.data["outputs"] = {"pdf": out.relative_to(settings.ws).as_posix(),
                             "md": (p.dir / "informe.md").relative_to(settings.ws).as_posix(),
                             "built": time.time(), "warnings": warnings}
        p.save()
    return out


def check_evidence(p: ReportProject) -> list[str]:
    """Comprobación de evidencias (sin IA): fotos citadas que no existen, fotos nunca citadas en el
    texto redactado y marcadores [POR COMPLETAR] pendientes."""
    n = len(p.data["photos"])
    cited: set[int] = set()
    pending = 0
    bad = set()
    for u in p.units():
        f = p.section_file(u.id)
        if u.uses_ai and f.exists():
            txt = f.read_text("utf-8")
            for m in re.finditer(r"[Ff]otos?\s+(?:n\.?º?\s*)?(\d+)", txt):
                k = int(m.group(1))
                (cited.add(k) if 1 <= k <= n else bad.add(k))
            pending += txt.count("[POR COMPLETAR")
    out = []
    if bad:
        out.append("Se citan fotos que no existen: " + ", ".join(f"Foto {k}" for k in sorted(bad)))
    unused = [k for k in range(1, n + 1) if k not in cited]
    if n and unused and len(unused) < n:
        out.append("Fotos no comentadas en el texto: " + ", ".join(f"Foto {k}" for k in unused[:30]))
    if pending:
        out.append(f"Quedan {pending} marcadores [POR COMPLETAR] por revisar")
    return out


def list_projects(ws: Path) -> list[dict]:
    base = ws / "reports"
    out = []
    if base.exists():
        for f in sorted(base.glob("*/project.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                d = json.loads(f.read_text("utf-8"))
                out.append({"id": d["id"], "title": d["title"], "template": d["template"].get("name"),
                            "updated": d.get("updated"), "photos": len(d.get("photos", [])),
                            "pdf": d.get("outputs", {}).get("pdf")})
            except Exception:  # noqa: BLE001
                continue
    return out
