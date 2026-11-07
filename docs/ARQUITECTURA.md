# Arquitectura y decisiones de diseño

PixAgent sigue el patrón que comparten los agentes de código abierto más sólidos (Claude Code y su
Agent SDK según su documentación pública, OpenHands, Aider, smolagents, Open Interpreter) y lo
especializa en planos, documentos y mini apps.

> No se usó código filtrado ni propietario. El diseño se basa en documentación pública y en
> patrones conocidos de proyectos open source.

## 1. El bucle

```
usuario ──► modelo ──► ¿pide herramientas? ──no──► respuesta final
              ▲              │ sí
              │              ▼
              └──── resultados (texto + IMÁGENES) ◄── ejecutar herramientas (con permisos)
```

Lo que copiamos de esos agentes y por qué:

| Patrón | Origen | Implementación |
|---|---|---|
| Herramientas pequeñas y componibles (leer, escribir, editar por reemplazo exacto, listar, buscar, shell) | Claude Code / Agent SDK | `tools/files.py`, `tools/execution.py` |
| Lista de tareas visible que el modelo mantiene al día | Claude Code (TodoWrite) | `todo_write` y panel "Plan" en la UI |
| Ejecución de código como acción principal | smolagents, Open Interpreter | `run_python`: proceso aparte, workspace como cwd, detecta archivos e imágenes nuevos |
| Flujo de eventos entre agente y UI | OpenHands | Eventos `tool_start`, `tool_end`, `text_delta`, `todos`, `approval_request` por WebSocket |
| Modos de permiso y aprobación humana | Claude Code | `permission_mode` = `auto`, `ask` o `full`; la shell siempre pide permiso salvo en `full` |
| Rutas confinadas al workspace | Varios | `ToolContext.resolve` y `allowed_dirs` |
| Historial solo-añadir | API de Claude | El turno del modelo se reenvía tal cual (con su pensamiento); nunca se reescribe el pasado |
| Resultados de herramientas juntos en un solo mensaje | API de Claude | Mantiene las llamadas paralelas del modelo |

## 2. Lo que añade PixAgent: verificación visual

La diferencia clave para planos y documentos es que **cada herramienta que produce algo visual le
devuelve la imagen al modelo**:

- `compose_plan` devuelve el plano renderizado.
- `create_miniapp` y `preview_page` devuelven una captura del navegador.
- `pdf_tools(to_images)` devuelve las páginas del PDF.
- `run_python` devuelve las imágenes que guardó el script.

Así el agente se autocorrige: detecta flechas mal dirigidas, textos solapados o una mini app rota y
lo arregla antes de entregar.

## 3. Motor de planos declarativo

En lugar de que el modelo dibuje con código cada vez (frágil), `compose_plan` recibe una **escena JSON**:

```json
{"base": "uploads/plano.png", "scale": {"px_per_meter": 80},
 "elements": [
   {"type": "photo", "src": "uploads/f1.jpg", "anchor": [312, 220], "view_angle": -90, "caption": "Fachada"},
   {"type": "arrow", "from": [500, 400], "to": [620, 330], "label": "Fisura"},
   {"type": "room", "points": [[0,0],[400,0],[400,300],[0,300]], "name": "Sala"}],
 "title_block": {"title": "Reporte fotográfico"}}
```

- Las coordenadas son **píxeles del plano original**. El modelo los lee con
  `view_image(grid=true)`, que dibuja una cuadrícula con etiquetas numéricas sobre la imagen. Esto
  mejora mucho la precisión de un modelo de visión.
- Las fotos sin `position` se **colocan solas** en los márgenes: se elige el lado más cercano a
  su anclaje, se ordenan para que las flechas no se crucen y se resuelven los solapes.
- La escena se guarda como `*.scene.json`. Para editar basta con `scene_path` y los cambios, sin
  rehacer nada.
- Tipos disponibles: foto, flecha, marcador, texto, nota con flecha (callout), rectángulo,
  resaltado, elipse, habitación (con área), polígono, línea, muro, cota, puerta, ventana, imagen,
  leyenda y cajetín.

## 4. Puente con PixPin

PixPin no tiene API HTTP, pero sí un motor de scripts JavaScript que se invoca con
`PixPin.exe -f script.js`. La instancia abierta recibe el script.

- **Salida**: `pixpin.pinFromFiles([...])` fija los resultados. HTML y PDF se rasterizan antes.
- **Entrada**: `pixpin.directScreenShotAndSaveTo(rect, ruta)` guarda capturas en `inbox/` y
  `pixpin.runSystem(...)` lanza `pixagent send-clipboard` o abre la interfaz. Como los scripts
  vuelven antes de terminar la captura, el servidor **vigila la carpeta** en vez de esperar una
  respuesta.
- Los scripts se escriben en UTF-8 con BOM, como recomienda PixPin para textos con acentos.

## 5. Llamada al modelo (`llm.py`)

- Modelo por defecto `claude-opus-5-5` con pensamiento adaptativo y `effort` configurable.
- Streaming, para que el texto aparezca mientras se genera y las entradas grandes de herramientas
  (HTML, código) no agoten el tiempo de espera. Las entradas se validan en el cliente
  (`validate_input`).
- Caché automática de prompts: el prompt de sistema no contiene datos variables (la fecha va en
  el mensaje del usuario), así que el prefijo se reutiliza.
- Fallback del lado del servidor (`fallbacks: "default"`): si el modelo rechaza una petición, se
  reintenta en el modelo de respaldo. Si llega un bloque `fallback`, el historial se limpia según
  las reglas de la API (`sanitize_fallback`).
- Búsqueda y lectura web del lado del servidor, con manejo de `pause_turn`.

## 6. Multiplataforma y bajo consumo

El objetivo era que funcionara en Windows, macOS, Android, iOS e iPadOS, también en teléfonos
modestos, sin perder funciones. Se descartaron:

- **Apps nativas por plataforma**: cinco bases de código. Además, iOS no permite ejecutar Python ni
  procesos arbitrarios.
- **Electron**: 150–300 MB de RAM por ventana.
- **Flutter/React Native**: pesan más y necesitan las tiendas de apps.

La solución es un **anfitrión único + PWA**:

```
 iPhone/iPad ─┐                         ┌─ Claude (nube)
 Android ─────┼─ PWA (~70 KB) ◄─WS/HTTP─► anfitrión Python ─┼─ PixPin (scripts JS)
 Mac/Windows ─┘   (sin cálculo pesado)   (PC, Mac, Termux,  └─ Python, PDF, imágenes
                                          Docker/VPS)
```

Detalles en el README (sección *Optimización para dispositivos modestos*). Los puntos con más
impacto medido:

| Medida | Resultado |
|---|---|
| SDK de IA, PDF y matplotlib con import diferido | Anfitrión en reposo: ~90 MB → ~54 MB |
| Miniaturas WebP + `draft()` del decodificador JPEG | Foto de 4000×3000 en la lista: KB en vez de MB, poca RAM al generarla |
| Fragmentos de texto agrupados cada 60 ms | Un solo mensaje WebSocket por cada ráfaga de fragmentos (en el test, 10 → 1) |
| Reducir fotos en el cliente | Lado máximo de 3200 px en JPEG; una foto de 48 MP pesa una fracción del original (estimado, no medido en un teléfono real) |
| Primera carga de la interfaz | ~70 KB transferidos, ~10 MB de memoria JS (medido en emulación de iPhone 13, iPad y Moto G4) |

## 7. Ampliar

Añadir una herramienta es un decorador:

```python
from pixagent.tools.base import tool, ToolResult

@tool("mi_herramienta", "Qué hace y cuándo usarla.",
      {"properties": {"x": {"type": "string"}}, "required": ["x"]})
def mi_herramienta(ctx, x):
    return ToolResult(f"hecho con {x}", files=[...], images=[...])
```

Impórtala en `pixagent/tools/__init__.py` y el agente ya puede usarla.
