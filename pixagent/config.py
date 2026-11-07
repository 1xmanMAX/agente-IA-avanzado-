"""Configuración de PixAgent.

Orden de prioridad: variables de entorno > ~/.pixagent/config.json > valores por defecto.
"""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

CONFIG_DIR = Path(os.environ.get("PIXAGENT_HOME", Path.home() / ".pixagent"))
CONFIG_FILE = CONFIG_DIR / "config.json"


@dataclass
class Settings:
    # Carpeta de trabajo: aquí viven uploads, planos, informes, mini apps, sesiones...
    workspace: str = str(Path.home() / "PixAgent")
    # Modelo de Claude y esfuerzo de razonamiento (low|medium|high|xhigh|max)
    model: str = "claude-opus-5-5"
    effort: str = "high"
    # Modelo económico para la IA rápida de las mini apps (pies de foto, revisiones cortas...)
    quick_model: str = "claude-haiku-5-5"
    max_tokens: int = 64000
    # Reintento automático en otro modelo si el principal rechaza la petición
    server_fallbacks: bool = True
    # Mostrar notas de progreso entre llamadas a herramientas
    progress_updates: bool = True
    # Herramientas de servidor de Anthropic (búsqueda y lectura web)
    enable_web: bool = True
    # Ruta a PixPin.exe (vacío = autodetectar)
    pixpin_path: str = ""
    # "auto": todo dentro del workspace sin preguntar; shell pide permiso.
    # "ask": pide permiso para shell, python y scripts de PixPin.
    # "full": sin preguntas y acceso fuera del workspace (¡cuidado!).
    permission_mode: str = "auto"
    # Carpetas extra (fuera del workspace) a las que el agente puede acceder
    allowed_dirs: list[str] = field(default_factory=list)
    # Límite de turnos de herramienta por mensaje del usuario
    max_steps: int = 60
    # Tope de gasto estimado por petición (USD); 0 = sin tope
    max_usd_per_task: float = 5.0
    # Limpieza en servidor de resultados de herramientas antiguos (ahorra tokens en sesiones largas)
    context_editing: bool = True
    # Servidor web
    host: str = "127.0.0.1"
    port: int = 8765
    # Acceso desde otros dispositivos (móvil, tablet, otro PC): exige token si está activo.
    require_token: bool = False
    access_token: str = ""
    # HTTPS opcional (necesario para instalar la PWA en Android/iOS fuera de localhost).
    ssl_certfile: str = ""
    ssl_keyfile: str = ""
    # Las fotos se reducen EN EL DISPOSITIVO antes de subirlas (ahorra datos y memoria).
    upload_max_px: int = 3200

    # ------------------------------------------------------------------
    @property
    def ws(self) -> Path:
        p = Path(self.workspace).expanduser().resolve()
        return p

    def ensure_dirs(self) -> None:
        for sub in ("inbox", "uploads", "outputs", "apps", "plans", "reports",
                    "diagrams", ".sessions", ".tmp", ".thumbs", "pixpin_scripts"):
            (self.ws / sub).mkdir(parents=True, exist_ok=True)

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(asdict(self), indent=2, ensure_ascii=False), "utf-8")


_ENV_MAP = {
    "PIXAGENT_WORKSPACE": ("workspace", str),
    "PIXAGENT_MODEL": ("model", str),
    "PIXAGENT_EFFORT": ("effort", str),
    "PIXAGENT_PERMISSION_MODE": ("permission_mode", str),
    "PIXPIN_PATH": ("pixpin_path", str),
    "PIXAGENT_PORT": ("port", int),
    "PIXAGENT_HOST": ("host", str),
    "PIXAGENT_TOKEN": ("access_token", str),
    "PIXAGENT_REQUIRE_TOKEN": ("require_token", lambda v: v.lower() in ("1", "true", "yes", "si", "sí")),
    "PIXAGENT_ENABLE_WEB": ("enable_web", lambda v: v.lower() in ("1", "true", "yes", "si", "sí")),
    "PIXAGENT_FALLBACKS": ("server_fallbacks", lambda v: v.lower() in ("1", "true", "yes", "si", "sí")),
    "PIXAGENT_PROGRESS_UPDATES": ("progress_updates", lambda v: v.lower() in ("1", "true", "yes", "si", "sí")),
}


def load_settings(**overrides) -> Settings:
    data: dict = {}
    if CONFIG_FILE.exists():
        try:
            data = json.loads(CONFIG_FILE.read_text("utf-8"))
        except json.JSONDecodeError:
            data = {}
    known = Settings.__dataclass_fields__.keys()
    s = Settings(**{k: v for k, v in data.items() if k in known})
    for env, (attr, conv) in _ENV_MAP.items():
        if os.environ.get(env):
            setattr(s, attr, conv(os.environ[env]))
    for k, v in overrides.items():
        if v is not None and k in known:
            setattr(s, k, v)
    s.ensure_dirs()
    return s


def ensure_token(s: Settings) -> str:
    """Genera y guarda un token de acceso la primera vez que se abre a la red."""
    if not s.access_token:
        import secrets
        s.access_token = secrets.token_urlsafe(18)
        s.save()
    return s.access_token
