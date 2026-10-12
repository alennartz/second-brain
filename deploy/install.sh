#!/usr/bin/env bash
# Install or update the second-brain systemd USER service.
#
# Reads deploy/deploy.env (machine-specific, gitignored), renders the unit
# template, installs it under ~/.config/systemd/user/, and (re)starts it.
# Requires only docker-group membership — no sudo.
set -euo pipefail

cd "$(dirname "$0")/.."

ENV_FILE="deploy/deploy.env"
if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found" >&2
  echo "copy deploy/deploy.env.example to $ENV_FILE and fill it in" >&2
  exit 1
fi
# shellcheck source=/dev/null
source "$ENV_FILE"

: "${BRAIN_IMAGE:?BRAIN_IMAGE must be set in $ENV_FILE}"
: "${BRAIN_DEPLOY_NAME:?BRAIN_DEPLOY_NAME must be set in $ENV_FILE}"
: "${BRAIN_DEPLOY_PORT:?BRAIN_DEPLOY_PORT must be set in $ENV_FILE}"
: "${BRAIN_DEPLOY_ENV_FILE:?BRAIN_DEPLOY_ENV_FILE must be set in $ENV_FILE}"
: "${BRAIN_DEPLOY_DATA_DIR:?BRAIN_DEPLOY_DATA_DIR must be set in $ENV_FILE}"

if [[ "$BRAIN_IMAGE" == *":latest" ]]; then
  echo "error: refusing to deploy :latest — pin a release tag" >&2
  exit 1
fi

mkdir -p "$BRAIN_DEPLOY_DATA_DIR" "${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"

UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user/${BRAIN_DEPLOY_NAME}.service"
TMP_UNIT="$(mktemp)"

sed \
  -e "s|{{NAME}}|${BRAIN_DEPLOY_NAME}|g" \
  -e "s|{{IMAGE}}|${BRAIN_IMAGE}|g" \
  -e "s|{{PORT}}|${BRAIN_DEPLOY_PORT}|g" \
  -e "s|{{ENV_FILE}}|${BRAIN_DEPLOY_ENV_FILE}|g" \
  -e "s|{{DATA_DIR}}|${BRAIN_DEPLOY_DATA_DIR}|g" \
  deploy/second-brain.service.in > "$TMP_UNIT"

install -m 0644 "$TMP_UNIT" "$UNIT"
rm -f "$TMP_UNIT"

systemctl --user daemon-reload
systemctl --user enable --now "${BRAIN_DEPLOY_NAME}.service"

echo "deployed ${BRAIN_IMAGE} as user service ${BRAIN_DEPLOY_NAME}.service on :${BRAIN_DEPLOY_PORT}"
