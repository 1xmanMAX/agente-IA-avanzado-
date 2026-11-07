"""Catálogo de modelos pequeños recomendados y deducción de capacidades.

Las capacidades se deducen por familia del nombre del modelo, así funciona con cualquier etiqueta
instalada (qwen3-vl:4b, qwen2.5vl:7b-q4_K_M, moondream:latest, archivos GGUF de llama.cpp…).
"""
from __future__ import annotations

# (prefijo de familia en minúsculas, capacidades, prioridad por tarea: mayor = mejor)
FAMILIES = [
    ("qwen3.5", {"vision", "ocr", "video", "text"}, {"vision": 97, "ocr": 90, "video": 97, "text": 92}),
    ("qwen3-vl", {"vision", "ocr", "video"}, {"vision": 93, "ocr": 88, "video": 93}),
    ("qwen3vl", {"vision", "ocr", "video"}, {"vision": 93, "ocr": 88, "video": 93}),
    ("glm-ocr", {"ocr"}, {"ocr": 98}),
    ("deepseek-ocr", {"ocr"}, {"ocr": 94}),
    ("paddleocr", {"ocr"}, {"ocr": 92}),
    ("gemma4", {"vision", "video", "text"}, {"vision": 90, "ocr": 80, "video": 88, "text": 88}),
    ("minicpm-v4.6", {"vision", "video", "ocr"}, {"vision": 80, "ocr": 75, "video": 84}),
    ("minicpm-v", {"vision", "ocr", "video"}, {"vision": 82, "ocr": 80, "video": 80}),
    ("qwen2.5vl", {"vision", "ocr", "video"}, {"vision": 84, "ocr": 84, "video": 84}),
    ("qwen2.5-vl", {"vision", "ocr", "video"}, {"vision": 84, "ocr": 84, "video": 84}),
    ("gemma3n", {"vision", "text"}, {"vision": 74, "video": 60, "text": 70}),
    ("gemma3", {"vision", "text"}, {"vision": 78, "ocr": 70, "video": 70, "text": 75}),
    ("ministral-3", {"vision", "text"}, {"vision": 72, "text": 76}),
    ("granite3.2-vision", {"vision", "ocr"}, {"vision": 65, "ocr": 78}),
    ("llama3.2-vision", {"vision"}, {"vision": 68, "ocr": 60}),
    ("smolvlm", {"vision", "video"}, {"vision": 55, "video": 62}),
    ("moondream", {"vision"}, {"vision": 50, "ocr": 35, "video": 45}),
    ("llava", {"vision"}, {"vision": 45, "ocr": 30, "video": 40}),
    ("qwen3", {"text"}, {"text": 88}),
    ("granite4", {"text"}, {"text": 74}),
    ("qwen2.5", {"text"}, {"text": 72}),
    ("phi4-mini", {"text"}, {"text": 70}),
    ("llama3.2", {"text"}, {"text": 62}),
    ("lfm2", {"text"}, {"text": 66}),
]

# Familias con modo de razonamiento: para tareas de visión/OCR rápidas se desactiva
THINKING_FAMILIES = ("qwen3.5", "qwen3", "qwen3-vl", "lfm2.5-thinking", "deepseek-r1", "gemma4")
# Prompts especiales que exigen algunos modelos de OCR
OCR_PROMPTS = {"glm-ocr": "Text Recognition:", "deepseek-ocr": "<|grounding|>Convert the document to markdown."}


def _family(model_id: str):
    name = model_id.lower().split("/")[-1]
    for fam, caps, prio in FAMILIES:
        if name.startswith(fam) or f"/{fam}" in model_id.lower() or fam in name:
            return fam, caps, prio
    return None, set(), {}


def capabilities(model_id: str) -> list[str]:
    fam, caps, prio = _family(model_id)
    if not fam:
        caps = {"vision"} if any(k in model_id.lower() for k in ("vl", "vision", "llava", "ocr")) else {"text"}
    out = set(caps)
    if "vision" in out:
        out.add("vision")
    return sorted(out | {k for k in prio})


def score(model_id: str, task: str) -> int:
    fam, caps, prio = _family(model_id)
    if not fam:
        return 10 if task in capabilities(model_id) else 0
    if task == "vision" and "vision" not in caps and "ocr" in caps:
        return 0   # un modelo solo-OCR no sirve para describir
    s = prio.get(task, 0)
    # a igualdad de familia preferimos tamaños medios (4–8 B) para calidad, pero no gigantes
    low = model_id.lower()
    for tag, bonus in (("8b", 4), ("7b", 4), ("4b", 3), ("3b", 2), ("2b", 1), ("1b", -2), ("0.6b", -4)):
        if tag in low:
            s += bonus
            break
    return s


def rank_installed(pairs, task: str):
    scored = [(score(mid, task), e, mid) for e, mid in pairs]
    scored = [x for x in scored if x[0] > 0]
    scored.sort(key=lambda x: -x[0])
    return [(e, mid) for _, e, mid in scored]


# Recomendaciones (etiquetas de Ollama verificadas en ollama.com, nov. 2026). Ver docs/IA_LOCAL.md.
CATALOG = [
    {"id": "qwen3.5:4b", "task": ["vision", "ocr", "video", "text"], "size_gb": 3.3, "ram_gb": 6,
     "note": "Recomendado: describe fotos y fotogramas, lee texto y planos, resume. Mejor equilibrio."},
    {"id": "qwen3.5:2b", "task": ["vision", "ocr", "video", "text"], "size_gb": 2.7, "ram_gb": 4,
     "note": "Para PCs sin GPU (8 GB RAM) y análisis de vídeo rápido."},
    {"id": "qwen3.5:0.8b", "task": ["vision", "video", "text"], "size_gb": 1.2, "ram_gb": 3,
     "note": "Ultraligero: equipos muy modestos o miles de imágenes."},
    {"id": "qwen3.5:9b", "task": ["vision", "ocr", "video", "text"], "size_gb": 6.6, "ram_gb": 10,
     "note": "Máxima calidad local; GPU de 8 GB o Mac M de 16 GB."},
    {"id": "glm-ocr:q8_0", "task": ["ocr"], "size_gb": 1.8, "ram_gb": 3,
     "note": "OCR especializado (0,9 B): documentos, tablas y planos escaneados."},
    {"id": "minicpm-v4.6:1b", "task": ["vision", "video"], "size_gb": 1.6, "ram_gb": 3,
     "note": "1 B con vídeo, pensado para móviles y equipos modestos."},
    {"id": "gemma4:e2b", "task": ["vision", "video", "text"], "size_gb": 4.6, "ram_gb": 6,
     "note": "Google Gemma 4: visión, vídeo corto y audio."},
    {"id": "qwen3-vl:4b", "task": ["vision", "ocr", "video"], "size_gb": 3.3, "ram_gb": 6,
     "note": "Alternativa probada si Qwen3.5 no está disponible en tu versión de Ollama."},
    {"id": "qwen3:1.7b", "task": ["text"], "size_gb": 1.4, "ram_gb": 3,
     "note": "Solo texto, ultraligero: clasificar, extraer, resumir."},
]

PROFILES = {
    "pc_basico": {"label": "PC sin GPU (8 GB RAM)", "models": ["qwen3.5:2b", "glm-ocr:q8_0"]},
    "equilibrado": {"label": "PC o Mac de 16 GB", "models": ["qwen3.5:4b", "glm-ocr:q8_0"]},
    "pc_gpu": {"label": "GPU 8 GB / Mac M 16 GB+", "models": ["qwen3.5:9b", "glm-ocr"]},
}


def family_of(model_id: str) -> str | None:
    return _family(model_id)[0]


def suggest(task: str) -> str:
    for c in CATALOG:
        if task in c["task"]:
            return c["id"]
    return "qwen3.5:4b"
