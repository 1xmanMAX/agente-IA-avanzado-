"""Motores de IA local: Ollama, llama.cpp (llama-server), LM Studio y cualquier servidor compatible
con la API de OpenAI (vLLM, LocalAI, Jan, KoboldCpp…).

Todos se usan con la misma interfaz:
    eng.models() -> [ModelInfo]
    eng.chat(model, prompt, images=[Path], system="", max_tokens=512, json_mode=False) -> str
    eng.pull(model, on_progress)   # solo Ollama
Las imágenes se reducen antes de enviarse (por defecto 768 px): los modelos pequeños van mucho más
rápido y casi no pierden calidad.
"""
from __future__ import annotations

import base64
import io
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import httpx

DEFAULT_ENDPOINTS = [
    ("ollama", "Ollama", "http://127.0.0.1:11434"),
    ("openai", "llama.cpp", "http://127.0.0.1:8080"),
    ("openai", "llama.cpp (9931)", "http://127.0.0.1:9931"),   # puerto por defecto en versiones recientes
    ("openai", "LM Studio", "http://127.0.0.1:1234"),
]


@dataclass
class ModelInfo:
    id: str
    engine: str
    size_gb: float | None = None
    family: str = ""
    vision: bool | None = None   # None = desconocido (se deduce del catálogo)


@dataclass
class Engine:
    kind: str          # "ollama" | "openai"
    name: str
    base_url: str
    api_key: str = ""
    online: bool = False
    version: str = ""
    error: str = ""
    _models: list[ModelInfo] = field(default_factory=list)

    # ---------------------------------------------------------------- utilidades
    def _client(self, timeout: float = 600) -> httpx.Client:
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        # trust_env=False: los motores locales nunca deben pasar por un proxy corporativo
        return httpx.Client(base_url=self.base_url.rstrip("/"), timeout=httpx.Timeout(timeout, connect=3),
                            headers=headers, trust_env=False)

    def probe(self) -> "Engine":
        try:
            with self._client(4) as c:
                if self.kind == "ollama":
                    r = c.get("/api/version")
                    r.raise_for_status()
                    self.version = r.json().get("version", "")
                else:
                    r = c.get("/v1/models")
                    r.raise_for_status()
            self.online = True
            self.error = ""
        except Exception as e:  # noqa: BLE001
            self.online = False
            self.error = type(e).__name__
        return self

    def models(self) -> list[ModelInfo]:
        if not self.online:
            return []
        with self._client(10) as c:
            if self.kind == "ollama":
                data = c.get("/api/tags").json().get("models", [])
                self._models = [ModelInfo(m["name"], self.name, round(m.get("size", 0) / 1e9, 2),
                                          (m.get("details") or {}).get("family", "")) for m in data]
            else:
                data = c.get("/v1/models").json().get("data", [])
                self._models = [ModelInfo(m["id"], self.name) for m in data]
        return self._models

    # ---------------------------------------------------------------- inferencia
    def chat(self, model: str, prompt: str, images: list[Path] | None = None, system: str = "",
             max_tokens: int = 512, json_mode: bool = False, temperature: float = 0.2,
             image_side: int = 768, timeout: float = 600, think: bool | None = None) -> tuple[str, dict]:
        imgs = [encode_image(p, image_side) for p in images or []]
        t0 = time.time()
        with self._client(timeout) as c:
            if self.kind == "ollama":
                msgs = ([{"role": "system", "content": system}] if system else []) + [
                    {"role": "user", "content": prompt, **({"images": imgs} if imgs else {})}]
                body = {"model": model, "messages": msgs, "stream": False, "keep_alive": "10m",
                        "options": {"temperature": temperature, "num_predict": max_tokens}}
                if json_mode:
                    body["format"] = "json"
                if think is not None:
                    body["think"] = think   # desactivar el razonamiento: respuestas rápidas
                r = c.post("/api/chat", json=body)
                if r.status_code == 400 and "think" in body:  # versiones/modelos sin soporte de 'think'
                    body.pop("think")
                    r = c.post("/api/chat", json=body)
                _raise(r)
                d = r.json()
                text = (d.get("message") or {}).get("content", "")
                usage = {"input": d.get("prompt_eval_count", 0), "output": d.get("eval_count", 0)}
            else:
                content: list | str = prompt
                if imgs:
                    content = [{"type": "text", "text": prompt}] + [
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b}"}} for b in imgs]
                msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": content}]
                body = {"model": model, "messages": msgs, "max_tokens": max_tokens, "temperature": temperature,
                        "stream": False}
                if json_mode:
                    body["response_format"] = {"type": "json_object"}
                r = c.post("/v1/chat/completions", json=body)
                if r.status_code == 400 and json_mode:  # algunos servidores no aceptan response_format
                    body.pop("response_format")
                    r = c.post("/v1/chat/completions", json=body)
                _raise(r)
                d = r.json()
                text = d["choices"][0]["message"].get("content") or ""
                u = d.get("usage") or {}
                usage = {"input": u.get("prompt_tokens", 0), "output": u.get("completion_tokens", 0)}
        usage["seconds"] = round(time.time() - t0, 2)
        return strip_think(text), usage

    def pull(self, model: str, on_progress: Callable[[dict], None] | None = None) -> None:
        """Descarga un modelo (solo Ollama) informando del progreso."""
        if self.kind != "ollama":
            raise RuntimeError("Este motor no descarga modelos: descárgalo desde su propia aplicación.")
        with self._client(None) as c, c.stream("POST", "/api/pull", json={"model": model, "stream": True}) as r:
            _raise(r)
            for line in r.iter_lines():
                if not line:
                    continue
                ev = json.loads(line)
                if ev.get("error"):
                    raise RuntimeError(ev["error"])
                if on_progress:
                    tot, done = ev.get("total") or 0, ev.get("completed") or 0
                    on_progress({"status": ev.get("status", ""), "pct": round(done / tot * 100, 1) if tot else None})

    def unload(self, model: str) -> None:
        if self.kind == "ollama":
            with self._client(10) as c:
                c.post("/api/generate", json={"model": model, "keep_alive": 0})


def _raise(r: httpx.Response) -> None:
    if r.status_code >= 400:
        try:
            msg = r.json().get("error") or r.text
        except Exception:  # noqa: BLE001
            msg = r.text
        if isinstance(msg, dict):
            msg = msg.get("message", str(msg))
        raise RuntimeError(f"{r.status_code}: {str(msg)[:300]}")


def strip_think(text: str) -> str:
    """Los modelos con razonamiento (Qwen3, DeepSeek-R1…) pueden incluir <think>…</think>."""
    import re
    return re.sub(r"<think>.*?</think>\s*", "", text, flags=re.S).strip()


def encode_image(p: Path, side: int = 768) -> str:
    from PIL import Image, ImageOps
    with Image.open(p) as im:
        im.draft("RGB", (side, side))
        im = ImageOps.exif_transpose(im).convert("RGB")
        im.thumbnail((side, side), Image.LANCZOS)
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=88)
    return base64.b64encode(buf.getvalue()).decode()


def discover(extra: list[dict] | None = None) -> list[Engine]:
    """Detecta motores locales en sus puertos habituales (+ los configurados por el usuario)."""
    from concurrent.futures import ThreadPoolExecutor
    cands = [Engine(k, n, u) for k, n, u in DEFAULT_ENDPOINTS]
    for e in extra or []:
        if e.get("url"):
            cands.append(Engine(e.get("kind", "openai"), e.get("name") or e["url"], e["url"], e.get("api_key", "")))
    with ThreadPoolExecutor(max_workers=len(cands)) as ex:
        list(ex.map(Engine.probe, cands))
    return cands
