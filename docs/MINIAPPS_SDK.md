# Mini apps y SDK de PixAgent

Una **mini app** es una herramienta pequeña y autocontenida (HTML/CSS/JS) que hace su trabajo en el
navegador, **sin gastar tokens**, y llama a la IA solo cuando aporta valor (redactar pies de foto,
revisar un diseño...). Funciona en escritorio, móvil y tablet, se abre dentro de PixAgent o suelta,
y se puede lanzar desde PixPin con un atajo.

- Integradas: `pixagent/miniapps/<slug>/` (vienen con PixAgent).
- Del usuario o creadas por el agente: `<workspace>/apps/<slug>/`.
- URL: `/apps/<slug>/` (sirve `index.html` y sus recursos relativos).
- Cada carpeta lleva un `manifest.json`:

```json
{"name": "Diseñador de graderías", "description": "Escaleras y graderías con 3D, isométrico y medidas",
 "icon": "🏟️", "category": "Construcción", "entry": "index.html", "kind": "web", "uses_ai": true}
```

## SDK (`<script src="/static/pixagent-sdk.js"></script>`)

| Función | Descripción |
|---|---|
| `PixAgent.upload(files)` | Sube `File`/`Blob`; devuelve rutas del workspace |
| `PixAgent.save(name, data, {folder})` | Guarda `Blob`/texto/objeto en `outputs/<folder>/<name>`; devuelve la ruta |
| `PixAgent.list(folder)` | Lista archivos `[{path, size, mtime, kind}]` |
| `PixAgent.pin(paths)` | Fija en PixPin (imágenes; PDF y HTML se rasterizan) |
| `PixAgent.ai(prompt, {images, system, json, maxTokens, quality})` | IA rápida. `quality: "fast"` (modelo económico, por defecto) o `"best"`. Con `json: true` devuelve un objeto |
| `PixAgent.photoPanel(spec)` | Genera un panel fotográfico PDF en el servidor (ver abajo) |
| `PixAgent.sendToAgent(text, attachments)` | Pasa una tarea grande al agente principal |
| `PixAgent.toast(msg)` | Aviso en la interfaz anfitriona |
| `PixAgent.fileUrl(path)` / `PixAgent.thumbUrl(path, w)` | URLs del archivo / miniatura WebP |
| `PixAgent.embedded` | `true` si se abrió dentro de PixAgent |

## API HTTP (la usa el SDK)

| Método y ruta | Cuerpo / respuesta |
|---|---|
| `POST /api/upload` (multipart `files`) | `{files: [ruta]}` |
| `POST /api/files/save` (multipart `file`, `folder`) | `{ok, path}` |
| `GET /api/files/list?folder=` | `{files: [{path, size, mtime, kind}]}` |
| `POST /api/ai/quick` | `{prompt, images: [ruta], system, json, max_tokens, quality}` → `{ok, text, data}` |
| `POST /api/photo-panel` | spec → `{ok, path, pages}` |
| `GET /api/apps` | `[{slug, name, description, icon, category, url, builtin, uses_ai}]` |
| `POST /api/pixpin/pin` | `{files: [ruta]}` |

### Especificación del panel fotográfico

```json
{
  "output": "outputs/paneles/panel_obra.pdf",
  "title": "Panel fotográfico", "subtitle": "Obra: Vivienda Pérez",
  "fields": {"Proyecto": "…", "Ubicación": "…", "Fecha": "2026-11-07", "Responsable": "…"},
  "logo": "uploads/logo.png",
  "layout": "2x3",            // columnas x filas por página: 1x1, 1x2, 2x2, 2x3, 3x3, 3x4
  "page": "A4", "orientation": "portrait",   // o "landscape"
  "photos": [{"path": "uploads/f1.jpg", "caption": "Fachada principal"}],
  "numbering": true, "theme_color": "#1f4e79", "fit": "cover"   // o "contain"
}
```
