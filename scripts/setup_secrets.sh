#!/usr/bin/env bash
# First-time SOPS + age setup for Eiswein secrets.
#
# Creates:
#   secrets/eiswein.enc.yaml   — encrypted secrets file (committed to git)
#   /etc/eiswein/age.key       — age private key (chmod 600, root)
#
# Documented in docs/OPERATIONS.md. Re-running is safe: existing keys are
# preserved; only absent files are created. Rotation is handled by
# `scripts/rotate_age_key.sh`.

set -euo pipefail

AGE_KEY_PATH="${AGE_KEY_PATH:-/etc/eiswein/age.key}"
SECRETS_DIR="${SECRETS_DIR:-$(git rev-parse --show-toplevel 2>/dev/null)/secrets}"
SECRETS_FILE="${SECRETS_FILE:-${SECRETS_DIR}/eiswein.enc.yaml}"

if ! command -v age-keygen >/dev/null 2>&1; then
  echo "error: age-keygen not installed (brew install age)" >&2
  exit 2
fi
if ! command -v sops >/dev/null 2>&1; then
  echo "error: sops not installed (brew install sops)" >&2
  exit 2
fi

mkdir -p "${SECRETS_DIR}"
mkdir -p "$(dirname "${AGE_KEY_PATH}")"

if [[ ! -f "${AGE_KEY_PATH}" ]]; then
  echo "Generating new age key at ${AGE_KEY_PATH}"
  age-keygen -o "${AGE_KEY_PATH}" 2>&1 | tail -n 1
  chmod 600 "${AGE_KEY_PATH}"
else
  echo "Age key already exists at ${AGE_KEY_PATH} (not overwriting)"
fi

AGE_RECIPIENT="$(age-keygen -y "${AGE_KEY_PATH}")"
echo "Age public key: ${AGE_RECIPIENT}"

if [[ ! -f "${SECRETS_FILE}" ]]; then
  TMP="$(mktemp)"
  cat >"${TMP}" <<'YAML'
JWT_SECRET: REPLACE_ME
ENCRYPTION_KEY: REPLACE_ME
ADMIN_USERNAME: admin
ADMIN_PASSWORD_HASH: REPLACE_ME
FRED_API_KEY: ""
SCHWAB_APP_KEY: ""
SCHWAB_APP_SECRET: ""
SMTP_USERNAME: ""
SMTP_PASSWORD: ""
YAML
  sops --encrypt --age "${AGE_RECIPIENT}" --input-type yaml --output-type yaml \
    "${TMP}" >"${SECRETS_FILE}"
  rm -f "${TMP}"
  echo "Wrote encrypted secrets template: ${SECRETS_FILE}"
  echo "Edit with:  sops ${SECRETS_FILE}"
else
  echo "Secrets file already exists: ${SECRETS_FILE} (not overwriting)"
fi

cat <<'NEXT'

Next steps:
  1. Back up the age key to 1Password (critical — loss = forced rotation).
  2. Edit secrets:   sops secrets/eiswein.enc.yaml
  3. Generate values:
       JWT_SECRET:        python -c "import secrets; print(secrets.token_urlsafe(64))"
       ENCRYPTION_KEY:    python -c "import secrets,base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
       ADMIN_PASSWORD_HASH: python scripts/set_password.py
NEXT
