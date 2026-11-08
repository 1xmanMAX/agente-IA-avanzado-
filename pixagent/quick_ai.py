"""IA rápida y económica para mini apps: una sola llamada, sin herramientas ni historial."""
from __future__ import annotations

import json
import re
from pathlib import Path

QUICK_SYSTEM = ("Eres el asistente integrado en una mini app de PixAgent. Responde de forma breve, "
                "precisa y en el idioma del usuario.")


def quick_ai(settings, body: dict) -> dict:
    import anthropic

    from .tools.base import image_block

    prompt = str(body.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("Falta 'prompt'.")
    best = body.get("quality") == "best"
    model = settings.model if best else settings.quick_model
    max_tokens = max(64, min(int(body.get("max_tokens") or 1024), 8000))
    content: list[dict] = []
    ws = settings.ws
    for rel in (body.get("images") or [])[:20]:
        p = (ws / rel).resolve()
        if ws not in p.parents or not p.exists():
            raise ValueError(f"Imagen no válida: {rel}")
        content.append(image_block(p, max_side=1024))  # 1024 px: suficiente y barato
    want_json = body.get("json")
    text = prompt
    if want_json:
        text += ("\n\nResponde SOLO con JSON válido, sin texto adicional ni bloques de código."
                 + (f" Forma esperada: {want_json}" if isinstance(want_json, str) else ""))
    content.append({"type": "text", "text": text})
    system = QUICK_SYSTEM + ("\n" + body["system"] if body.get("system") else "")
    params = dict(model=model, max_tokens=max_tokens, system=system,
                  messages=[{"role": "user", "content": content}], output_config={"effort": "low"})
    from .anthropic_client import make_client
    client = make_client(settings)
    if best and settings.server_fallbacks and model.startswith(("claude-opus-5", "claude-fable-5", "claude-sonnet-5-5")):
        resp = client.beta.messages.create(**params, fallbacks="default", betas=["server-side-fallback-2026-07-01"])
    else:
        resp = client.messages.create(**params)
    if resp.stop_reason == "refusal":
        raise RuntimeError("El modelo rechazó la petición.")
    out = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text").strip()
    res = {"ok": True, "text": out, "model": model,
           "usage": {"input": resp.usage.input_tokens, "output": resp.usage.output_tokens}}
    if want_json:
        m = re.search(r"[\[{].*[\]}]", out, re.S)
        try:
            res["data"] = json.loads(m.group(0) if m else out)
        except json.JSONDecodeError:
            raise RuntimeError("La IA no devolvió JSON válido.")
    return res
