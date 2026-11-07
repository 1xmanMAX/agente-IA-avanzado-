# PixAgent como servidor (PC de casa, NAS, Raspberry Pi o VPS) para usarlo desde cualquier
# dispositivo: iPhone, iPad, Android, Mac o Windows. Imagen ligera (python:slim, sin navegador).
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    PIXAGENT_WORKSPACE=/data/workspace PIXAGENT_HOME=/data/config
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY pyproject.toml README.md ./
COPY pixagent ./pixagent
RUN pip install ".[full]"
VOLUME /data
EXPOSE 8765
# --lan escucha en 0.0.0.0 y exige token; el token y el QR aparecen en los logs
CMD ["python", "-m", "pixagent", "serve", "--lan", "--no-browser", "--port", "8765"]
