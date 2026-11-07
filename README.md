# PixAgent: IA avanzada para PixPin

PixAgent es un agente de IA que funciona como el modo avanzado de [PixPin](https://pixpin.com).
PixPin se encarga de lo básico (capturas, pines, OCR, traducción). Lo que necesita varios pasos lo
envías aquí, y el resultado vuelve a PixPin fijado en pantalla.

![Plano con fotos generado por el agente](examples/demo_plano_con_fotos.png)

## Qué hace

| Especialidad | Ejemplo de petición |
|---|---|
| **Planos con fotos** | "Te paso el plano y 12 fotos: ubica cada una donde se tomó, con flechas, números y cono de visión; leyenda y cajetín." |
| **Editar o crear planos** | "Marca las fisuras en rojo, añade cotas (1 m = 80 px) y calcula el área de cada habitación." |
| **Diagramas** | "Diagrama de flujo del proceso de aprobación de obra" (genera PNG, SVG y PDF) |
| **Informes PDF** | "Informe de inspección con portada, índice, tabla de hallazgos y el plano anotado." |
| **Mini apps** | "Una mini app para calcular metrados" (HTML o Python, lista para abrir con un atajo de PixPin) |
| **Python** | Cualquier librería: Pillow, pandas, matplotlib, reportlab, pymupdf, openpyxl... |

### Cómo trabaja (comportamiento agéntico)

1. **Planifica**: para tareas largas crea una lista de pasos visible en la interfaz.
2. **Mira**: lee el plano con una **cuadrícula de coordenadas** y revisa cada foto para deducir dónde se tomó.
3. **Actúa** con herramientas especializadas: `compose_plan`, `render_diagram`, `create_pdf`, `create_miniapp`, `run_python`...
4. **Verifica**: cada herramienta le devuelve una **imagen del resultado** (el plano renderizado, la captura de la mini app, las páginas del PDF) y corrige hasta que quede bien.
5. **Entrega**: guarda los archivos ordenados y, si lo pides, los fija en PixPin.

## Integración con PixPin

La integración usa la [API de scripts oficial de PixPin](https://pixpin.com/docs/configuration/script)
(`PixPin.exe -f script.js`) en las dos direcciones:

- **PixPin → agente**: atajos de PixPin que envían la última captura, la ventana activa o el
  portapapeles a la bandeja `inbox/`. La interfaz los recibe al instante como adjuntos.
- **Agente → PixPin**: el agente fija en pantalla planos, diagramas, páginas de PDF o capturas de
  mini apps (`pixpin.pinFromFiles`). También puede pedir capturas a PixPin.
- **Mini apps**: cada mini app trae `abrir_en_pixpin.js` para abrirla con un atajo de PixPin.

Detalles en [pixpin_scripts/README.md](pixpin_scripts/README.md).

## Instalación

Requisitos: Python 3.10+ y una clave de API de Anthropic.

**Windows**

```bat
instalar.bat
setx ANTHROPIC_API_KEY "tu_clave"
iniciar.bat
```

**macOS / Linux**

```bash
export ANTHROPIC_API_KEY="tu_clave"
./iniciar.sh
```

Después:

```bash
python -m pixagent install-pixpin      # genera los scripts para PixPin con tus rutas
python -m pixagent config pixpin_path="C:/Program Files/PixPin/PixPin.exe"   # si no se autodetecta
```

## Uso

| Comando | Para qué |
|---|---|
| `python -m pixagent` | Interfaz web (chat, visor de planos/PDF/apps, biblioteca, botones de PixPin) |
| `python -m pixagent chat` | Chat en la terminal (`/adjuntar ruta…` para adjuntar) |
| `python -m pixagent run "tarea" -a plano.png foto1.jpg` | Ejecuta una tarea y termina |
| `python -m pixagent send archivo.png` | Envía archivos a la bandeja del agente |
| `python -m pixagent send-clipboard` | Envía la imagen o el texto del portapapeles |
| `python -m pixagent config clave=valor` | Cambia la configuración (`~/.pixagent/config.json`) |

En la interfaz puedes arrastrar archivos, pegar capturas con Ctrl+V y usar los botones de plantilla
(Plano con fotos, Diagrama, Informe PDF, Mini app, Python).

### Configuración principal

| Clave | Por defecto | Notas |
|---|---|---|
| `workspace` | `~/PixAgent` | Carpeta de trabajo: `uploads/ inbox/ plans/ diagrams/ reports/ apps/ outputs/` |
| `model` | `claude-opus-5-5` | Modelo de Claude |
| `effort` | `high` | `low`, `medium`, `high`, `xhigh` o `max` |
| `permission_mode` | `auto` | `auto`: pide permiso solo para la shell. `ask`: también para Python y PixPin. `full`: sin preguntas ni límites de carpeta |
| `enable_web` | `true` | Búsqueda y lectura web del lado del servidor |
| `server_fallbacks` | `true` | Si el modelo rechaza una petición, se reintenta en el modelo de respaldo |
| `progress_updates` | `true` | Muestra notas de progreso entre herramientas |
| `allowed_dirs` | `[]` | Carpetas extra a las que puede acceder (separadas por `;`) |

## Arquitectura

```
pixagent/
  agent.py          bucle agéntico (historial solo-añadir, resultados en paralelo, permisos, sesiones)
  llm.py            Claude: streaming, pensamiento adaptativo, esfuerzo, caché de prompts, fallbacks
  prompts.py        prompt de sistema especializado
  pixpin_bridge.py  puente con PixPin (scripts JS, pinFromFiles, capturas, lanzadores)
  tools/
    files.py        read_file, write_file, edit_file, list_files, search_files
    execution.py    run_python, run_shell, todo_write
    vision.py       view_image (cuadrícula de coordenadas y zoom), image_tools (hoja de contactos...)
    plan.py         compose_plan: motor de planos declarativo (escena JSON reeditable)
    diagram.py      render_diagram: disposición automática por capas, PNG + SVG + PDF, Mermaid
    documents.py    create_pdf (Markdown → PDF profesional), pdf_tools
    browser.py      preview_page (captura de HTML), html_to_pdf (Playwright, o Edge/Chrome)
    pixpin_tools.py pixpin (pin/capture/run_script), create_miniapp
  web/              FastAPI + WebSocket + interfaz (HTML/CSS/JS sin dependencias)
```

Más detalle sobre las decisiones de diseño en [docs/ARQUITECTURA.md](docs/ARQUITECTURA.md).

## Tests

```bash
pip install -e ".[dev]"
pytest
```

Los tests no usan red: ejecutan las herramientas reales y simulan el modelo para probar el bucle
del agente y el servidor web.
