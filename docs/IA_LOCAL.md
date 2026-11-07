# IA local: modelos pequeños como herramientas

PixAgent puede usar **modelos pequeños (0,8–9 B parámetros) en tu propio equipo**. Son gratuitos,
privados y rápidos para trabajo masivo, como describir cientos de fotos, leer texto de documentos y
planos (OCR) o narrar un vídeo fotograma a fotograma. Claude se reserva para lo que requiere
razonar. El agente decide solo cuándo delegar (herramienta `local_ai`), y las mini apps los usan
con `PixAgent.local`.

## 1. Instalar un motor

| Plataforma | Motor recomendado | Cómo |
|---|---|---|
| Windows / macOS | **Ollama** | Instalador de [ollama.com](https://ollama.com). Arranca solo |
| Linux | Ollama | `curl -fsSL https://ollama.com/install.sh \| sh` |
| Cualquiera | **llama.cpp** (`llama-server`) | `llama-server -hf <repo-gguf> --port 8080` (descarga el modelo y su `mmproj`) |
| Cualquiera | **LM Studio** | Activa el servidor local (puerto 1234) |
| Android / iPhone | — | Usa el anfitrión (PC/Mac) desde la app web. La IA en el propio móvil por WebGPU está en evaluación |

PixAgent detecta solo Ollama (11434), llama.cpp (8080 y 9931) y LM Studio (1234). Si usas otro
servidor compatible con OpenAI (vLLM, LocalAI, Jan…), añádelo en la mini app **IA local → Avanzado**.

## 2. Modelos recomendados (noviembre de 2026)

| Equipo | Visión / vídeo | OCR | Texto |
|---|---|---|---|
| PC sin GPU, 8 GB RAM | `qwen3.5:2b` (ultraligero: `qwen3.5:0.8b`, `minicpm-v4.6:1b`) | `glm-ocr:q8_0` | `qwen3.5:2b` |
| PC o Mac de 16 GB | `qwen3.5:4b` | `glm-ocr:q8_0` | `qwen3.5:4b` |
| GPU de 8 GB / Mac M de 16 GB o más | `qwen3.5:9b` (alternativas: `qwen3-vl:8b`, `gemma4:e4b`) | `glm-ocr` | `qwen3.5:9b` |

Descárgalos desde la mini app **IA local** o con `ollama pull <modelo>`. PixAgent elige el mejor
modelo instalado para cada tarea (visión, OCR, texto). Puedes fijar otro en la mini app.

Ajustes automáticos según el modelo:

- **Razonamiento desactivado** en tareas de visión y OCR de los modelos que lo tienen (Qwen3.5,
  Qwen3, Gemma 4), para responder más rápido.
- **Prompts propios de los modelos de OCR**: `Text Recognition:` para GLM-OCR y `<|grounding|>…`
  para DeepSeek-OCR.
- **Imágenes reducidas** antes de enviarlas: 768 px para describir y 1280 px para OCR.

## 3. Lo que aprendimos al probar con un modelo real

La prueba se hizo con Qwen2.5-VL-3B en llama.cpp, solo con CPU (4 núcleos):

- **OCR**: transcripción exacta del documento de prueba, con acentos y cifras.
- **Prompts**: los modelos pequeños **inventan lo que el prompt sugiere**. Si el prompt menciona
  "personas", describe personas que no existen. Por eso los prompts de PixAgent piden solo lo
  visible.
- **Comparar fotogramas**: lo hacen mal. Si se les pide decir si un fotograma "cambió", responden
  "sin cambios" aunque haya cambiado. PixAgent detecta los fotogramas casi idénticos midiendo la
  diferencia de píxeles, sin IA, y no los envía al modelo. Es más rápido y más fiable.
- **Velocidad**: 12–20 s por fotograma y 45–80 s por imagen grande, con solo CPU y 4 núcleos. Con
  GPU o un Mac M baja a unos pocos segundos.
- **Calidad**: describen bien lo general y pueden inventar detalles. Úsalos para volumen y deja que
  Claude verifique lo importante.

## 4. Vídeo fotograma a fotograma

Usa la mini app **Analizador de vídeo** o la herramienta `local_ai(action="video")`. Pasos:

1. **Fuente**: un archivo, una URL (requiere `pip install yt-dlp`; solo contenido propio o con
   permiso) o en directo desde la cámara o la pantalla.
2. **Fotogramas**: uno cada N segundos o en cada cambio de escena (filtro `scene` de ffmpeg).
   Los vídeos se descargan a 480p o menos.
3. **Descripción** de cada fotograma con el modelo de visión. Los resultados aparecen en cuanto
   salen.
4. **Transcripción** opcional con Whisper local (`pip install faster-whisper`).
5. **Resumen** con el modelo de texto local, o pídeselo a Claude con "Enviar al agente".

Resultados: `outputs/video/<id>/analisis.md`, `analisis.json` y la carpeta `frames/`.

Dependencias opcionales: `pip install -e ".[local]"` (faster-whisper, yt-dlp, imageio-ffmpeg).

## 5. SDK para mini apps

```js
await PixAgent.local.status();                          // motores, modelos, asignaciones
await PixAgent.local.caption(fileOrPath);               // describir
await PixAgent.local.ocr(fileOrPath);                   // leer texto
await PixAgent.local.ask("¿Hay fisuras?", [img1, img2]);
await PixAgent.local.frame(videoElement, "¿Qué hace la máquina?");  // fotograma en directo
await PixAgent.local.video({source: "uploads/obra.mp4", every: 5}, job => pintar(job.items));
```
