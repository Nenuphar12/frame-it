# syntax=docker/dockerfile:1
# ---- frontend build -------------------------------------------------------------------------------
FROM node:24-slim AS frontend
WORKDIR /src/frontend
RUN corepack enable
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN mkdir -p ../backend/src/frame_it/static && pnpm exec vite build

# ---- runtime -----------------------------------------------------------------------------------------
FROM python:3.14-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never \
    PATH=/app/.venv/bin:$PATH FRAME_IT_DATA_DIR=/data FRAME_IT_HOST=0.0.0.0 FRAME_IT_PORT=8765
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
COPY --from=frontend /src/backend/src/frame_it/static ./src/frame_it/static
RUN uv sync --frozen --no-dev && useradd --system --uid 1000 frame && mkdir /data && chown frame /data
USER frame
VOLUME ["/data"]
EXPOSE 8765 53317/tcp 53317/udp
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/v1/system/info')"
CMD ["frame-it", "serve"]
