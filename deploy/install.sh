#!/usr/bin/env bash
# Install the local Second Brain systemd user service and backup timer.
#
# Machine-specific values live in deploy/deploy.env. The script resolves the
# checkout from its own location so callers can run it from any directory.
set -euo pipefail

DEPLOY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CHECKOUT_DIR="$(cd -- "$DEPLOY_DIR/.." && pwd -P)"
ENV_FILE="$DEPLOY_DIR/deploy.env"
# shellcheck source=common.sh
source "$DEPLOY_DIR/common.sh"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found" >&2
  echo "copy deploy/deploy.env.example to $ENV_FILE and fill it in" >&2
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

if [[ ! "$BRAIN_DEPLOY_PORT" =~ ^[1-9][0-9]*$ ]] || (( BRAIN_DEPLOY_PORT > 65535 )); then
  echo "error: BRAIN_DEPLOY_PORT must be a valid TCP port" >&2
  exit 1
fi
if [[ "$BRAIN_DEPLOY_DB_NAME" == /* || "$BRAIN_DEPLOY_DB_NAME" == */* ||
  "$BRAIN_DEPLOY_DB_NAME" == "." || "$BRAIN_DEPLOY_DB_NAME" == ".." ||
  "$BRAIN_DEPLOY_DB_NAME" == *".."* ]]; then
  echo "error: BRAIN_DEPLOY_DB_NAME must be a single directory name" >&2
  exit 1
fi

if [[ "$BRAIN_IMAGE" == *":latest" ]]; then
  echo "error: refusing to deploy :latest — use the configured local tag" >&2
  exit 1
fi

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
if ! "$DOCKER_BIN" image inspect "$BRAIN_IMAGE" >/dev/null 2>&1; then
  echo "error: local Docker image is not available: $BRAIN_IMAGE" >&2
  echo "build it locally before installing the service" >&2
  exit 1
fi

# Read one numeric setting without executing the application environment file.
read_shutdown_grace() {
  awk '
    /^[[:space:]]*(export[[:space:]]+)?BRAIN_INTAKE_SHUTDOWN_GRACE_SECONDS[[:space:]]*=/ {
      sub(/^[^=]*=/, "")
      sub(/[[:space:]]+#.*$/, "")
      gsub(/^[[:space:]]+|[[:space:]]+$/, "")
      if ((substr($0, 1, 1) == "\"" && substr($0, length($0), 1) == "\"") ||
          (substr($0, 1, 1) == "\047" && substr($0, length($0), 1) == "\047")) {
        $0 = substr($0, 2, length($0) - 2)
      }
      print
      exit
    }
  ' "$BRAIN_DEPLOY_ENV_FILE"
}

grace_seconds="$(read_shutdown_grace)"
if [[ -z "$grace_seconds" ]]; then
  grace_seconds=60
fi
if [[ ! "$grace_seconds" =~ ^(([0-9]+([.][0-9]*)?)|([.][0-9]+))$ ]]; then
  echo "error: BRAIN_INTAKE_SHUTDOWN_GRACE_SECONDS must be a non-negative number" >&2
  exit 1
fi

# Both integer timeouts must exceed the configured (possibly fractional) grace.
grace_ceiling="$(awk -v value="$grace_seconds" 'BEGIN { whole = int(value); if (value > whole) whole++; print whole }')"
# Pipeline shutdown can wait through the grace period, cancel stuck workers,
# and wait through a second grace period before Storage closes.
docker_stop_timeout=$((grace_ceiling * 2 + 5))
systemd_stop_timeout=$((docker_stop_timeout + 5))

CONFIG_HOME="${XDG_CONFIG_HOME:-}"
if [[ -z "$CONFIG_HOME" && -n "${HOME:-}" ]]; then
  CONFIG_HOME="$HOME/.config"
fi
if [[ -z "$CONFIG_HOME" ]]; then
  echo "error: HOME or XDG_CONFIG_HOME must be set" >&2
  exit 1
fi
UNIT_DIR="$CONFIG_HOME/systemd/user"
mkdir -p -- "$BRAIN_DEPLOY_DATA_DIR" "$BRAIN_DEPLOY_BACKUP_DIR" "$UNIT_DIR"
chmod 0600 -- "$BRAIN_DEPLOY_ENV_FILE"

user_uid="$(id -u)"
user_gid="$(id -g)"
if [[ ! "$user_uid" =~ ^[0-9]+$ || ! "$user_gid" =~ ^[0-9]+$ ]]; then
  echo "error: unable to determine numeric host user identity" >&2
  exit 1
fi

escape_sed_replacement() {
  printf '%s' "$1" | sed 's/[&|\\]/\\&/g'
}

name_replacement="$(escape_sed_replacement "$BRAIN_DEPLOY_NAME")"
image_replacement="$(escape_sed_replacement "$BRAIN_IMAGE")"
port_replacement="$(escape_sed_replacement "$BRAIN_DEPLOY_PORT")"
docker_replacement="$(escape_sed_replacement "$DOCKER_BIN")"
db_path_replacement="$(escape_sed_replacement "/data/$BRAIN_DEPLOY_DB_NAME")"
env_replacement="$(escape_sed_replacement "$BRAIN_DEPLOY_ENV_FILE")"
data_replacement="$(escape_sed_replacement "$BRAIN_DEPLOY_DATA_DIR")"
backup_script_replacement="$(escape_sed_replacement "$DEPLOY_DIR/backup.sh")"
uid_replacement="$(escape_sed_replacement "$user_uid")"
gid_replacement="$(escape_sed_replacement "$user_gid")"

render_template() {
  local template=$1 output=$2
  sed \
    -e "s|{{NAME}}|$name_replacement|g" \
    -e "s|{{IMAGE}}|$image_replacement|g" \
    -e "s|{{PORT}}|$port_replacement|g" \
    -e "s|{{DOCKER}}|$docker_replacement|g" \
    -e "s|{{DB_PATH}}|$db_path_replacement|g" \
    -e "s|{{ENV_FILE}}|$env_replacement|g" \
    -e "s|{{DATA_DIR}}|$data_replacement|g" \
    -e "s|{{USER_UID}}|$uid_replacement|g" \
    -e "s|{{USER_GID}}|$gid_replacement|g" \
    -e "s|{{DOCKER_STOP_TIMEOUT}}|$docker_stop_timeout|g" \
    -e "s|{{SYSTEMD_STOP_TIMEOUT}}|$systemd_stop_timeout|g" \
    -e "s|{{BACKUP_SCRIPT}}|$backup_script_replacement|g" \
    "$template" > "$output"
}

install_rendered_unit() {
  local template=$1 target=$2
  local temporary
  temporary="$(mktemp "$UNIT_DIR/.unit.XXXXXX")"
  render_template "$template" "$temporary"
  install -m 0644 -- "$temporary" "$target"
  rm -f -- "$temporary"
}

service_unit="$UNIT_DIR/${BRAIN_DEPLOY_NAME}.service"
backup_service_unit="$UNIT_DIR/${BRAIN_DEPLOY_NAME}-backup.service"
backup_timer_unit="$UNIT_DIR/${BRAIN_DEPLOY_NAME}-backup.timer"
install_rendered_unit "$DEPLOY_DIR/second-brain.service.in" "$service_unit"
install_rendered_unit "$DEPLOY_DIR/second-brain-backup.service.in" "$backup_service_unit"
install_rendered_unit "$DEPLOY_DIR/second-brain-backup.timer.in" "$backup_timer_unit"

cd -- "$CHECKOUT_DIR"
systemctl --user daemon-reload
systemctl --user enable --now "${BRAIN_DEPLOY_NAME}.service"
systemctl --user enable --now "${BRAIN_DEPLOY_NAME}-backup.timer"
wait_for_service_health "${BRAIN_DEPLOY_NAME}.service" "$BRAIN_DEPLOY_PORT"

echo "deployed $BRAIN_IMAGE as user service ${BRAIN_DEPLOY_NAME}.service on 127.0.0.1:$BRAIN_DEPLOY_PORT"
