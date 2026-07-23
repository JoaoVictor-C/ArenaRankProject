# syntax=docker/dockerfile:1.7
#
# arenarank backend image — single image, two roles (api / worker) selected at
# runtime by the container command. Multi-stage: a builder that materializes the
# LOCKED dependency set (uv.lock) into a venv, and a slim runtime that only
# carries the venv + the `arena` package. Non-root, slim, for a small attack
# surface (proposal §10, §14.3 redaction relies on our own logging).
#
# Dependencies are managed with uv (pyproject.toml + uv.lock) — reproducible,
# no floating pins. OpenTelemetry is the `[otel]` optional extra (the app
# degrades to no-ops without it; we include it here for production traces).
#
# Build:   docker build -t arenarank-backend:dev .
# Run api: docker run -p 8000:8000 arenarank-backend:dev
# Run wkr: docker run arenarank-backend:dev arq arena.workers.main.PriorityWorker

ARG PYTHON_VERSION=3.12-slim-bookworm

# --------------------------------------------------------------------------- #
# Stage 1 — builder: uv resolves the locked deps into a venv we copy forward.
# --------------------------------------------------------------------------- #
FROM python:${PYTHON_VERSION} AS builder

# Pinned uv binary from the official distroless image.
COPY --from=ghcr.io/astral-sh/uv:0.11.23 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# Build toolchain only in the builder stage (asyncpg / pydantic-core wheels are
# usually prebuilt, but keep gcc available for sdist fallbacks).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install ONLY the locked deps first so this layer caches across source-only
# changes. --frozen fails if uv.lock is stale; --no-dev drops ruff/mypy/pytest;
# --extra otel pulls in the OpenTelemetry exporter stack for production traces.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra otel --no-install-project

# Then install the project itself (its own layer).
COPY arena ./arena
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
RUN uv sync --frozen --no-dev --extra otel --no-editable

# --------------------------------------------------------------------------- #
# Stage 2 — runtime: slim, non-root, venv + source only.
# --------------------------------------------------------------------------- #
FROM python:${PYTHON_VERSION} AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    VIRTUAL_ENV=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    APP_HOME=/app \
    PORT=8000

# tini for correct PID-1 signal handling (graceful SIGTERM → uvicorn/arq drain).
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 10001 arena \
    && useradd --system --uid 10001 --gid arena --no-create-home arena

COPY --from=builder /opt/venv /opt/venv

WORKDIR ${APP_HOME}
COPY --chown=arena:arena arena ./arena
COPY --chown=arena:arena alembic.ini ./alembic.ini
COPY --chown=arena:arena alembic ./alembic

USER arena
EXPOSE 8000

# Liveness: the API serves GET /healthz (arena/api/app.py). Workers override the
# command and this HTTP check is not used by the worker pods (they use exec
# probes / no probe). Kept here for the api role and `docker run` convenience.
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD curl -fsS "http://127.0.0.1:${PORT}/healthz" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--"]

# Default command: API. Workers override (see k8s worker deployments):
#   command: ["arq", "arena.workers.main.PriorityWorker"]
CMD ["uvicorn", "arena.api.app:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
