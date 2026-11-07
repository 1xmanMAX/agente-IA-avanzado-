"""Registro de herramientas de PixAgent. Importar este paquete registra todas las herramientas."""
from . import base  # noqa: F401
from . import files, execution, vision, plan, diagram, documents, browser, pixpin_tools, panel, reports_tool  # noqa: F401
from .base import REGISTRY, Tool, ToolContext, ToolError, ToolResult  # noqa: F401

__all__ = ["REGISTRY", "Tool", "ToolContext", "ToolError", "ToolResult"]
