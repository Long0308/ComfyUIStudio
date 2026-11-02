# VoiceStudio / OmniVoice - one shared service. Build context = the VoiceStudio runtime project
# (see docker-compose.yml: VS_SRC). Code is COPIED in; nothing from AppData is mounted.
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv UV_COMPILE_BYTECODE=0 UV_LINK_MODE=copy \
    PATH=/opt/venv/bin:$PATH

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg libsndfile1 libgomp1 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir uv

WORKDIR /app

# Layer 1: dependencies from the existing lockfile (wheels incl. torch 2.8.0+cu128, usable for CPU and GPU profile).
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Layer 2: code (backend + omnivoice package), same layout as the Windows runtime (cwd=project, --app-dir backend).
COPY omnivoice ./omnivoice
COPY backend ./backend

# Idle watcher / PID 1 wrapper (lives only in the image; the AppData source is untouched).
COPY --from=sidecar idle_unload.py /usr/local/bin/idle_unload.py

# Return freed heap to the OS after the backend unloads the model.
ENV MALLOC_ARENA_MAX=2 MALLOC_TRIM_THRESHOLD_=131072 \
    OMNIVOICE_DATA_DIR=/data OMNIVOICE_CACHE_DIR=/hf_cache HF_HUB_OFFLINE=1 \
    OMNIVOICE_ANALYTICS_DISABLED=1 OMNIVOICE_PORT=8080

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=10s --start-period=240s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health', timeout=8).read()"

CMD ["python", "/usr/local/bin/idle_unload.py", "-m", "uvicorn", "main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8080"]
