# syntax=docker/dockerfile:1
# Confiance in one image: builds the web app, then serves it and the API from a single port.

# ---- 1. build the web app ---------------------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. the runtime image ---------------------------------------------------------------------------
FROM python:3.13-slim AS app
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH="/app/backend/.venv/bin:$PATH" PYTHONUNBUFFERED=1 \
    CONFIANCE_DATABASE_URL=sqlite:////data/confiance.db \
    CONFIANCE_BLOB_DIR=/data/blobs \
    CONFIANCE_SECRETS_FILE=/data/secrets.json \
    CONFIANCE_STATIC_DIR=/app/frontend/dist
WORKDIR /app/backend
COPY backend/pyproject.toml backend/uv.lock backend/README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev
COPY --from=web /web/dist /app/frontend/dist

# Everything the app stores (database, page snapshots, saved settings) lives in one volume.
RUN useradd --create-home --uid 10001 confiance && mkdir /data && chown confiance /data
USER confiance
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8000/api/health', timeout=4)"
CMD ["uvicorn", "confiance.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--log-level", "warning"]
