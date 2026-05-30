#!/bin/sh
# Destructive cleanup — stops the stack and deletes user-owned state.
#
# Source code is untouched: ``git status`` after ``make uninstall``
# shows only the absence of .env / certs / data.

set -e

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

cat <<'BANNER'
This will permanently delete:
  - The Eiswein Docker container + image
  - The mailpit Docker volume (if it exists)
  - .env              (your secrets — JWT, encryption key, Schwab tokens)
  - data/             (your SQLite database, watchlist, signal history)
  - certs/            (your self-signed TLS keys if you generated any)
  - .venv-bootstrap/  (the install-time Python venv)

Source code stays. You can re-run `make install` to set up again.

BANNER

printf 'Type "yes" to confirm: '
read -r CONFIRM
if [ "$CONFIRM" != "yes" ]; then
  echo "Aborted — nothing changed."
  exit 1
fi

echo "Stopping containers..."
docker compose down -v --remove-orphans 2>/dev/null || true

echo "Removing eiswein image..."
docker rmi -f eiswein 2>/dev/null || true
docker rmi -f "$(docker images -q 'eiswein-eiswein' 2>/dev/null)" 2>/dev/null || true

echo "Deleting local state..."
rm -f .env
rm -rf data certs .venv-bootstrap

echo ""
echo "Done. Source code is untouched."
