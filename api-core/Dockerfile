# api-core/Dockerfile
#
# Build from the repo root:
#   docker build -f api-core/Dockerfile -t security-assistant-api ./api-core
#
# Migrations run automatically on startup (src/db/migrate.py, called from
# api/http.py's startup hook) -- no separate migration step needed here.

FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# curl: only for the HEALTHCHECK below. The pinned Python deps (bcrypt,
# psycopg[binary]) ship prebuilt wheels for this image, so no compiler
# toolchain is needed.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml ./
COPY src ./src
# Loaded at import time by src/api/state.py (PolicyEngine reads
# config/policies/*.yaml; LLM settings read config/app.yaml). It sits next to
# `src`, not inside it, so it has to be copied explicitly -- without it the
# container exits on startup with "Policy directory not found".
COPY config ./config
# Read at runtime (the startup migration call, and the `alembic` CLI for
# manual use) rather than imported as Python -- copied explicitly since
# they're not part of the `src` package.
COPY alembic.ini ./
COPY migrations ./migrations

# [postgres] extra pulls in psycopg -- harmless if DATABASE_URL points at
# SQLite instead, and means the same image works for either without a
# rebuild.
RUN pip install --no-cache-dir '.[postgres]'

RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data /app/logs \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://127.0.0.1:${PORT:-8000}/health || exit 1

# Single worker, deliberately: the in-memory rate limiter
# (src/security/rate_limit.py) tracks request counts per-process, so
# >1 worker here would silently multiply every configured limit. Scale
# by running multiple container replicas behind a load balancer instead
# -- not by raising --workers -- until rate limiting moves to a shared
# store (e.g. Redis).
CMD ["sh", "-c", "uvicorn src.api.http:app --host 0.0.0.0 --port ${PORT:-8000}"]
