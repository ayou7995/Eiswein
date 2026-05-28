#!/bin/sh
# Container entrypoint for the distributable Eiswein image.
#
# Responsibilities:
#   1. Apply any pending Alembic migrations against the mounted SQLite
#      file. Idempotent — re-running this on a current DB is a no-op.
#   2. Detect mounted TLS cert pair (host's mkcert output) and start
#      uvicorn over HTTPS when present, plain HTTP otherwise.
#   3. ``exec`` uvicorn so the server is PID 1 and receives Docker's
#      SIGTERM directly — gives the FastAPI lifespan hook a chance to
#      cancel the startup catch-up task and shut down APScheduler
#      gracefully.
#
# CLAUDE.md invariant: ``uvicorn --workers 1`` so APScheduler doesn't
# race itself across workers. fcntl.flock in the scheduler is the
# belt; this flag is the suspenders.

set -e

cd /app

echo "[entrypoint] Running database migrations..."
alembic upgrade head

UVICORN_BASE="uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 --workers 1"

if [ -f /app/certs/localhost-key.pem ] && [ -f /app/certs/localhost.pem ]; then
  echo "[entrypoint] HTTPS certs detected — starting uvicorn with TLS"
  # shellcheck disable=SC2086  # word-splitting on the base string is intentional
  exec $UVICORN_BASE \
    --ssl-keyfile /app/certs/localhost-key.pem \
    --ssl-certfile /app/certs/localhost.pem
else
  echo "[entrypoint] No HTTPS certs found in /app/certs — starting uvicorn HTTP"
  # shellcheck disable=SC2086
  exec $UVICORN_BASE
fi
