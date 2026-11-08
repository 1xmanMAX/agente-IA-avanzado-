# Mejoras tomadas de harnesses de agentes de código abierto

Se leyó el **código fuente público** (versión de noviembre de 2026) de estos proyectos, bajo
licencias que permiten estudiarlo y adaptarlo:

- **OpenAI Codex CLI** (Apache-2.0)
- **Google Gemini CLI** (Apache-2.0)
- **opencode** (MIT)
- **OpenHands SDK** (MIT)
- **Cline** (Apache-2.0)
- **Goose** (Apache-2.0)
- **DeepSeek-TUI / Codewhale** (MIT)

También se usó la documentación pública de Claude Code y de la API de Anthropic. **No se usó
código filtrado ni propietario.**

| Mejora en PixAgent | Inspirada en | Detalle |
|---|---|---|
| **Compactación de conversaciones largas** | opencode, gemini-cli, codex, OpenHands | Usa la compactación del servidor de Anthropic (`compact_20260112`), con un prompt propio por secciones: objetivo, requisitos, decisiones, estado, siguiente paso, archivos y contexto. Incluye una regla anti-inyección. Se hace en el servidor porque reescribir el historial en el cliente rompería el razonamiento preservado de los modelos Claude 5.x |
| **Reintentos robustos** | codex, opencode, Cline 4.1.26 | El SDK reintenta 6 veces 429 y 5xx respetando `retry-after`. Además se recuperan los cortes a mitad del stream y la sobrecarga 529, con backoff exponencial y jitter (2 s → 30 s) y aviso en la interfaz |
| **Detector de atascos** | OpenHands `stuck_detector`, gemini-cli `loopDetectionService` | Detecta ciclos A-B-A-B y A-B-C ×3, la misma llamada ×3 y 3 errores seguidos de una herramienta. Primero avisa al modelo para que cambie de estrategia; a la tercera detiene la tarea |
| **Subagentes** (`delegate`) | gemini-cli `local-executor`, Goose `summon`, codex `agent/role` | Trabajan con contexto limpio y herramientas restringidas (solo lectura por defecto) y no pueden delegar a su vez. El padre solo recibe el informe final. Comparten el tope de coste y se ejecutan en paralelo si son de lectura |
| **Herramientas en paralelo** | gemini-cli `scheduler`, codex `parallel.rs` | Las herramientas de solo lectura se ejecutan a la vez y los resultados se devuelven en el orden original |
| **Habilidades** | OpenHands skills/triggers, Codewhale `SKILL.md`, gemini-cli `activate-skill` | En el prompt solo va un catálogo de una línea. Se activan por palabra clave (palabras completas, sin tildes) o con `load_skill`. Se adjuntan al mensaje del turno, así no rompen la caché |
| **Recetas `/nombre`** | Goose recipes | Markdown con parámetros (`*` = obligatorio) y plantilla `{{param}}`. Si falta un dato obligatorio, el agente lo pregunta con `ask_user` |
| **Modo plan** (`/plan` → `/ejecutar`) | Cline Plan/Act, Codewhale modes, codex plan template | Las herramientas de escritura se rechazan en el despachador sin quitarlas del esquema, para no invalidar la caché |
| **Rebobinar** | Cline checkpoints (restaurar tarea, archivos o ambos) | Vuelve a antes del turno N. Solo se recorta lo posterior y el prefijo no se edita |
| **Memoria jerárquica** | codex `AGENTS.md`, gemini-cli `GEMINI.md`, opencode | Se cargan `~/.pixagent/PIXAGENT.md` (global) y el `PIXAGENT.md` del workspace |
| **Salidas largas** | codex, gemini-cli, opencode | Al modelo le llegan el principio y el final de la salida; la salida completa queda en un archivo con una pista para leerla por partes |

Pendiente (menor impacto para los casos de uso de PixAgent): hooks de usuario en eventos y
cliente MCP.

## Crear tus propias recetas y habilidades

`<workspace>/recetas/mi-receta.md`:
```markdown
---
name: acta-reunion
description: Acta de reunión de obra a partir de notas o audio
parametros: obra*, fecha, asistentes
---
Redacta el acta de la reunión de la obra "{{obra}}" del {{fecha}} con asistentes {{asistentes}}…
```
Úsala en el chat con `/acta-reunion Obra Pérez fecha=2026-11-10`.

`<workspace>/skills/mi-norma.md` (con `keywords:` para activarla sola) añade conocimiento propio:
la normativa de tu país, el formato de tu empresa, etc.
