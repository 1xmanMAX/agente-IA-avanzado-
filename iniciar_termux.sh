#!/data/data/com.termux/files/usr/bin/bash
# PixAgent en Android con Termux (el teléfono hace de anfitrión; sin PC).
# Instala solo el núcleo ligero; las páginas de PDF como imagen y las capturas de mini apps
# no están disponibles aquí (el resto sí: planos, diagramas, informes PDF, Python, mini apps).
set -e
cd "$(dirname "$0")"
if [ ! -f .termux_ok ]; then
  pkg install -y python python-pillow libjpeg-turbo
  pip install anthropic reportlab pypdf fastapi uvicorn websockets python-multipart
  pip install -e . --no-deps
  touch .termux_ok
fi
termux-wake-lock 2>/dev/null || true   # evita que Android duerma el proceso
python -m pixagent serve --no-browser &
sleep 2
termux-open-url "http://127.0.0.1:8765/" 2>/dev/null || echo "Abre http://127.0.0.1:8765/ en el navegador"
wait
