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

image_id_file="$(mktemp)"
cleanup() {
  rm -f -- "$image_id_file"
}
trap cleanup EXIT

cd -- "$CHECKOUT_DIR"
# Build without changing the configured tag. The tag is updated only after the
# pre-update archive succeeds, so archive failure leaves the running image tag.
docker build --iidfile "$image_id_file" "$CHECKOUT_DIR"
image_id="$(<"$image_id_file")"
if [[ -z "$image_id" ]]; then
  echo "error: Docker did not report the built image ID" >&2
  exit 1
fi

bash "$DEPLOY_DIR/backup.sh" pre-update
docker tag "$image_id" "$BRAIN_IMAGE"
bash "$DEPLOY_DIR/install.sh"
systemctl --user restart "${BRAIN_DEPLOY_NAME}.service"

echo "updated $BRAIN_IMAGE and restarted ${BRAIN_DEPLOY_NAME}.service"
