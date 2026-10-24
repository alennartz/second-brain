#!/usr/bin/env bash
# Build the configured local image, archive the active database, and restart.
set -euo pipefail

DEPLOY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CHECKOUT_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd -P)"
ENV_FILE="$DEPLOY_DIR/deploy.env"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$ENV_FILE"

required_values=(
  BRAIN_IMAGE
  BRAIN_DEPLOY_NAME
  BRAIN_DEPLOY_PORT
  BRAIN_DEPLOY_DATA_DIR
  BRAIN_DEPLOY_BACKUP_DIR
  BRAIN_DEPLOY_DB_NAME
)
for variable in "${required_values[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    echo "error: $variable must be set in $ENV_FILE" >&2
    exit 1
  fi
done

cd -- "$CHECKOUT_DIR"
# A local build is deliberate. This command never pulls the configured tag.
docker build -t "$BRAIN_IMAGE" "$CHECKOUT_DIR"

bash "$DEPLOY_DIR/backup.sh" pre-update
bash "$DEPLOY_DIR/install.sh"
systemctl --user restart "${BRAIN_DEPLOY_NAME}.service"

echo "updated $BRAIN_IMAGE and restarted ${BRAIN_DEPLOY_NAME}.service"
