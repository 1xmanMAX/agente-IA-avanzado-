# Instrucciones para Claude Code en este repositorio

## Preferencias del propietario
- **No usar nunca modelos Fable de Anthropic** (ni para subagentes, ni para diseño de interfaz, ni
  como modelo de PixAgent): son demasiado caros. Para subagentes usa el modelo actual o uno más
  económico (Sonnet/Haiku).
- No usar ni buscar código filtrado o propietario (p. ej. el de Claude Code). Solo código abierto
  con licencia compatible y documentación pública.
- Responder en español.

## Proyecto
PixAgent: agente de IA avanzado integrado con PixPin (Python + FastAPI + PWA sin frameworks).
- Código: `pixagent/` · Tests: `python3 -m pytest -q tests` (sin red; usan un LLM simulado)
- Arranque: `python -m pixagent serve` (ver README.md)
- Documentación: `docs/` (ARQUITECTURA, MEJORAS_HARNESS, IA_LOCAL, MINIAPPS_SDK)
