FROM node:22-alpine AS frontend-build
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
ARG VITE_BASE_URL=/
ENV VITE_BASE_URL=${VITE_BASE_URL}
RUN npm run build

FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl ffmpeg unzip \
    && curl -fsSL https://deno.land/install.sh | sh \
    && rm -rf /var/lib/apt/lists/*
ENV DENO_INSTALL=/root/.deno
ENV PATH="/root/.deno/bin:${PATH}"
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
COPY backend/README.md ./
# Install third-party runtime deps first for better layer caching.
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/ ./
RUN uv sync --frozen --no-dev
COPY --from=frontend-build /app/frontend/dist ./static
ENV DATA_DIR=/data
ENV MUSIC_DIR=/music
ENV BASE_URL=/
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8080
EXPOSE 8080
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--log-level", "info"]
