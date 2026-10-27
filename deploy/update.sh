#!/usr/bin/env bash
# Build the configured local image, archive the active database, and restart.
set -euo pipefail

DEPLOY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CHECKOUT_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd -P)"
ENV_FILE="$DEPLOY_DIR/deploy.env"
# shellcheck source=common.sh
source "$DEPLOY_DIR/common.sh"

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
  BRAIN_DEPLOY_ENV_FILE
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

if [[ ! -f "$BRAIN_DEPLOY_ENV_FILE" ]]; then
  echo "error: application environment file does not exist: $BRAIN_DEPLOY_ENV_FILE" >&2
  exit 1
fi
validate_application_environment "$BRAIN_DEPLOY_ENV_FILE"

DOCKER_BIN="$(command -v docker || true)"
if [[ -z "$DOCKER_BIN" || ! -x "$DOCKER_BIN" ]]; then
  echo "error: Docker executable was not found in PATH" >&2
  exit 1
fi

image_id_file="$(mktemp)"
DEPLOY_LOCK_FD=""
cleanup() {
  rm -f -- "$image_id_file"
}
trap cleanup EXIT

cd -- "$CHECKOUT_DIR"
# Build without changing the configured tag. The tag is updated only after the
# pre-update archive succeeds, so archive failure leaves the running image tag.
"$DOCKER_BIN" build --iidfile "$image_id_file" "$CHECKOUT_DIR"
image_id="$(<"$image_id_file")"
if [[ -z "$image_id" ]]; then
  echo "error: Docker did not report the built image ID" >&2
  exit 1
fi

if ! exec {DEPLOY_LOCK_FD}>"$BRAIN_DEPLOY_BACKUP_DIR/.backup.lock"; then
  echo "error: unable to open deployment lock in $BRAIN_DEPLOY_BACKUP_DIR" >&2
  exit 1
fi
if ! flock --exclusive "$DEPLOY_LOCK_FD"; then
  echo "error: unable to acquire deployment lock in $BRAIN_DEPLOY_BACKUP_DIR" >&2
  exit 1
fi
export BRAIN_DEPLOY_LOCK_FD="$DEPLOY_LOCK_FD"

bash "$DEPLOY_DIR/backup.sh" pre-update
"$DOCKER_BIN" tag "$image_id" "$BRAIN_IMAGE"
bash "$DEPLOY_DIR/install.sh"
systemctl --user restart "${BRAIN_DEPLOY_NAME}.service"
wait_for_service_health "${BRAIN_DEPLOY_NAME}.service" "$BRAIN_DEPLOY_PORT"

echo "updated $BRAIN_IMAGE and restarted ${BRAIN_DEPLOY_NAME}.service"
