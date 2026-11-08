"""Cliente de Anthropic único para toda la app: usa la clave guardada en Ajustes o, si no hay,
ANTHROPIC_API_KEY / el perfil de `ant auth login`."""
from __future__ import annotations

import os


def key_source(settings) -> str:
    if getattr(settings, "anthropic_api_key", ""):
        return "ajustes"
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "entorno"
    return ""


def make_client(settings, **kw):
    import anthropic
    key = getattr(settings, "anthropic_api_key", "") or None
    return anthropic.Anthropic(api_key=key, **kw) if key else anthropic.Anthropic(**kw)


def mask(key: str) -> str:
    return (key[:10] + "…" + key[-4:]) if key and len(key) > 16 else ("…" if key else "")


def verify_key(key: str) -> tuple[bool, str]:
    """Comprueba la clave sin gastar tokens (lista de modelos)."""
    import anthropic
    try:
        anthropic.Anthropic(api_key=key, max_retries=1, timeout=20).models.list(limit=1)
        return True, ""
    except anthropic.AuthenticationError:
        return False, "La clave no es válida o fue revocada."
    except anthropic.PermissionDeniedError:
        return False, "La clave no tiene permisos para usar la API."
    except anthropic.APIConnectionError:
        return False, "No se pudo conectar con la API de Anthropic (revisa tu conexión)."
    except Exception as e:  # noqa: BLE001
        return False, f"No se pudo comprobar la clave: {e}"
