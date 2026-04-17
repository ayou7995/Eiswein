#!/usr/bin/env bash
# Rotate the age encryption key on the VM (I2).
#
# Process
#   1. Generate new age key (does NOT overwrite existing).
#   2. `sops updatekeys` — re-encrypts the data key for the new recipient
#      while the old key can still decrypt; ensures zero-downtime rotation.
#   3. Verify decryption succeeds with the new key.
#   4. Archive the old key (to 1Password) then remove.
#
# Run quarterly.

set -euo pipefail

OLD_KEY="${AGE_KEY_PATH:-/etc/eiswein/age.key}"
NEW_KEY="${OLD_KEY}.new"
BACKUP_DIR="${BACKUP_DIR:-/etc/eiswein/backups}"
SECRETS_FILE="${SECRETS_FILE:-$(git rev-parse --show-toplevel 2>/dev/null)/secrets/eiswein.enc.yaml}"

if [[ ! -f "${OLD_KEY}" ]]; then
  echo "error: existing age key not found at ${OLD_KEY}" >&2
  exit 2
fi
if [[ ! -f "${SECRETS_FILE}" ]]; then
  echo "error: secrets file not found at ${SECRETS_FILE}" >&2
  exit 2
fi

mkdir -p "${BACKUP_DIR}"

age-keygen -o "${NEW_KEY}"
chmod 600 "${NEW_KEY}"
NEW_RECIPIENT="$(age-keygen -y "${NEW_KEY}")"

# Make both keys visible to SOPS during re-encryption.
export SOPS_AGE_KEY_FILE="${OLD_KEY}"
export SOPS_AGE_RECIPIENTS="${NEW_RECIPIENT}"

sops updatekeys --yes "${SECRETS_FILE}"

# Switch to the new key and verify decryption.
export SOPS_AGE_KEY_FILE="${NEW_KEY}"
sops --decrypt "${SECRETS_FILE}" >/dev/null

TS="$(date -u +%Y%m%dT%H%M%SZ)"
cp "${OLD_KEY}" "${BACKUP_DIR}/age.key.retired.${TS}"
mv "${NEW_KEY}" "${OLD_KEY}"

echo "Rotated. Retired key archived at ${BACKUP_DIR}/age.key.retired.${TS}"
echo "Back up the new key to 1Password, then securely delete the archived copy after 30 days."
