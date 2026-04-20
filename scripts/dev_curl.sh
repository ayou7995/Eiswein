#!/usr/bin/env bash
# Dev-only helper: login to local Eiswein + run an authenticated GET/POST.
#
# Usage:
#   scripts/dev_curl.sh                              # GET /api/v1/ticker/SPY/indicators
#   scripts/dev_curl.sh GET /api/v1/watchlist        # override path
#   scripts/dev_curl.sh POST /api/v1/watchlist '{"symbol":"QQQ"}'
#
# Credentials come from env vars (set these in your shell rc for convenience)
# or fall back to the dev defaults that match backend/.env:
#   EISWEIN_DEV_USERNAME  (default: admin)
#   EISWEIN_DEV_PASSWORD  (default: eiswein-dev-2026)
#   EISWEIN_HOST          (default: http://127.0.0.1:8000)

set -euo pipefail

host="${EISWEIN_HOST:-http://127.0.0.1:8000}"
user="${EISWEIN_DEV_USERNAME:-admin}"
pass="${EISWEIN_DEV_PASSWORD:-eiswein-dev-2026}"

method="${1:-GET}"
path="${2:-/api/v1/ticker/SPY/indicators}"
body="${3:-}"

cookie_jar="$(mktemp -t eiswein-curl)"
trap 'rm -f "$cookie_jar"' EXIT

# Login — fatal if it fails.
login_body=$(printf '{"username":"%s","password":"%s"}' "$user" "$pass")
login_http=$(curl -sS -o /dev/null -w '%{http_code}' \
  -c "$cookie_jar" -X POST "$host/api/v1/login" \
  -H 'Content-Type: application/json' \
  -d "$login_body")
if [[ "$login_http" != "200" ]]; then
  echo "login failed with HTTP $login_http" >&2
  exit 1
fi

# Build the authenticated request.
if [[ -n "$body" ]]; then
  curl -sS -b "$cookie_jar" -X "$method" "$host$path" \
    -H 'Content-Type: application/json' -d "$body" \
    | python3 -m json.tool
else
  curl -sS -b "$cookie_jar" -X "$method" "$host$path" \
    | python3 -m json.tool
fi
