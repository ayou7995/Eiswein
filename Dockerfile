# syntax=docker/dockerfile:1.7
#
# Eiswein distributable image.
#
# Two stages so the final layer carries only the Python runtime + the
# built frontend bundle — no Node toolchain, no source TS, no
# node_modules. Target image size: < 500 MB.
#
# Build:   docker compose build  (or: docker build -t eiswein .)
# Run:     docker compose up -d
#
# The container is parametrised via env vars mounted from ./.env. The
# bootstrap script (scripts/bootstrap.py) generates that file before the
# first ``docker compose up``.

# ---------- Stage 1: build the React bundle ----------
FROM node:20-alpine AS frontend-builder

WORKDIR /build

# Cache the npm install layer separately from the source so dependency
# changes invalidate fewer rebuilds than source changes.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# Vite writes the production bundle to /build/dist/. The runtime stage
# copies that path verbatim into the FastAPI static serving root.
RUN npm run build


# ---------- Stage 2: Python runtime ----------
FROM python:3.12-slim AS runtime

# Defence in depth: don't run as root inside the container.
ARG APP_USER=eiswein
ARG APP_UID=1000

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Install only the runtime libraries our pip wheels actually need.
# - curl: container healthcheck
# - tini: PID 1 reaper so uvicorn doesn't end up zombified by Docker
# Build tools (gcc, libpq) are intentionally absent — pip pulls
# pre-built wheels for every dependency in requirements.txt.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        curl \
        tini \
        ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies before copying source so dependency
# changes don't invalidate the source COPY layer.
COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Backend source. ``app/`` is the package; ``alembic.ini`` + ``alembic/``
# carry the migration scripts the entrypoint applies on boot.
COPY backend/app /app/app
COPY backend/alembic /app/alembic
COPY backend/alembic.ini /app/alembic.ini

# Built frontend dist → served by FastAPI as static at /. Same single
# origin as the API which is what makes the production cookie story
# work (no port split → no localhost-vs-127.0.0.1 footgun).
COPY --from=frontend-builder /build/dist /app/frontend_dist

# Operator-curated industry events (`docs/events.yaml`). The calendar
# sync looks it up via the path configured in Settings; defaults work
# for the in-container layout.
COPY docs/events.yaml /app/docs/events.yaml

# Container entrypoint: alembic migrate → uvicorn (HTTPS if certs
# mounted at /app/certs/, HTTP otherwise).
COPY scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

# Pre-create the data + certs mount points so the container can boot
# even when the host operator forgets to declare the bind mount. The
# bootstrap-generated compose file always sets them, but a manual
# ``docker run`` smoke test shouldn't fail on a missing dir.
RUN mkdir -p /app/data /app/certs \
    && useradd --uid ${APP_UID} --create-home --shell /sbin/nologin ${APP_USER} \
    && chown -R ${APP_USER}:${APP_USER} /app

USER ${APP_USER}

# Default DB path matches Settings.database_url. Override via env if
# the operator wants a custom layout.
ENV DATABASE_URL=sqlite:///./data/eiswein.db

# uvicorn listens on 8000 inside the container; docker-compose maps
# that to 8080 on the host so multiple Eiswein instances can coexist
# with a foreground ``make dev`` running 8000 directly.
EXPOSE 8000

# tini reaps zombies + forwards SIGTERM cleanly so the FastAPI
# lifespan finally-block has time to cancel the startup catch-up task
# and shut down APScheduler.
ENTRYPOINT ["/usr/bin/tini", "--", "/app/entrypoint.sh"]

# Container-level healthcheck. Compose surfaces this on
# ``docker compose ps`` so the operator can see at a glance whether
# the API is up. Plain HTTP because the healthcheck runs locally
# inside the container — no Schwab/TLS concerns.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl --fail --silent --output /dev/null http://127.0.0.1:8000/api/v1/health || exit 1
