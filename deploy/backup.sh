#!/usr/bin/env bash
# Create and restore local archives of the active database.
#
# Public interface:
#   backup.sh daily
#   backup.sh pre-update
#   backup.sh restore <archive>
set -euo pipefail

DEPLOY_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ENV_FILE="$DEPLOY_DIR/deploy.env"

fail() {
  printf 'error: %s\n' "$*" >&2
  return 1
}

if [[ ! -f "$ENV_FILE" ]]; then
  fail "$ENV_FILE not found"
  exit 1
fi
# shellcheck source=/dev/null
source "$ENV_FILE"

required_values=(
  BRAIN_DEPLOY_NAME
  BRAIN_DEPLOY_PORT
  BRAIN_DEPLOY_DATA_DIR
  BRAIN_DEPLOY_BACKUP_DIR
  BRAIN_DEPLOY_DB_NAME
)
for variable in "${required_values[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    fail "$variable must be set in $ENV_FILE"
    exit 1
  fi
done

# The archive format and every move below require a single active directory
# name. Reject path components before any filesystem operation.
if [[ "$BRAIN_DEPLOY_DB_NAME" == /* || "$BRAIN_DEPLOY_DB_NAME" == */* ||
  "$BRAIN_DEPLOY_DB_NAME" == "." || "$BRAIN_DEPLOY_DB_NAME" == ".." ||
  "$BRAIN_DEPLOY_DB_NAME" == *".."* ]]; then
  fail "BRAIN_DEPLOY_DB_NAME must be a single directory name"
  exit 1
fi

SERVICE_NAME="${BRAIN_DEPLOY_NAME}.service"
PIPELINE_URL="http://127.0.0.1:${BRAIN_DEPLOY_PORT}/ingest/pipeline"

pipeline_activity_json() {
  jq -r '
    def count($field):
      .[$field] // 0
      | if (type == "number" and . >= 0) then . else error("invalid activity field") end;
    if type != "object" then
      error("invalid pipeline response")
    else
      [
        count("ready"),
        count("leased"),
        count("retry_wait"),
        count("worker_count"),
        count("active_leases")
      ] | any(.[]; . > 0)
    end
  '
}

pipeline_is_non_idle() {
  local response parsed
  if ! response="$(curl --fail --silent --show-error "$PIPELINE_URL")"; then
    return 2
  fi

  if ! parsed="$(pipeline_activity_json <<<"$response")"; then
    # A shell wrapper can append one quoting brace to a top-level object.
    # Retry that wrapper artifact once without accepting other malformed data.
    if [[ "$response" == \{*\}\} ]]; then
      response="${response%\}}"
      if ! parsed="$(pipeline_activity_json <<<"$response")"; then
        return 2
      fi
    else
      return 2
    fi
  fi

  if [[ "$parsed" == "true" ]]; then
    return 0
  fi
  return 1
}

defer_or_fail_pipeline() {
  local mode=$1 reason=$2
  if [[ "$mode" == "daily" ]]; then
    printf 'deferred: %s\n' "$reason"
    return 0
  fi
  fail "$reason"
}

service_was_active() {
  if systemctl --user is-active --quiet "$SERVICE_NAME" >/dev/null 2>&1; then
    return 0
  fi
  return 1
}

recover_service() {
  local was_active=$1
  if [[ "$was_active" == 1 ]]; then
    if ! systemctl --user start "$SERVICE_NAME"; then
      printf 'error: failed to recover %s\n' "$SERVICE_NAME" >&2
      return 1
    fi
  fi
  return 0
}

validate_archive_directories() {
  if [[ ! -d "$BRAIN_DEPLOY_DATA_DIR" ]]; then
    fail "data directory does not exist: $BRAIN_DEPLOY_DATA_DIR"
    return 1
  fi
  if [[ ! -d "$BRAIN_DEPLOY_BACKUP_DIR" ]]; then
    fail "backup directory does not exist: $BRAIN_DEPLOY_BACKUP_DIR"
    return 1
  fi
  return 0
}

archive_name() {
  local prefix=$1 backup_dir=$2 stamp candidate suffix
  stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
  candidate="$backup_dir/${prefix}-${stamp}.tar.gz"
  suffix=1
  while [[ -e "$candidate" ]]; do
    candidate="$backup_dir/${prefix}-${stamp}-${suffix}.tar.gz"
    suffix=$((suffix + 1))
  done
  printf '%s\n' "$candidate"
}

create_archive() {
  local prefix=$1 data_dir=$2 database_name=$3 backup_dir=$4
  local temporary published

  temporary="$(mktemp "$backup_dir/.${prefix}-XXXXXX.tar.gz.tmp")" || {
    printf 'error: unable to create temporary archive in %s\n' "$backup_dir" >&2
    return 1
  }

  if [[ ! -d "$data_dir/$database_name" || -L "$data_dir/$database_name" ]]; then
    rm -f -- "$temporary"
    printf 'error: active database directory is missing: %s\n' "$data_dir/$database_name" >&2
    return 1
  fi

  if ! (cd -- "$data_dir" && tar --create --gzip --file="$temporary" -- "$database_name"); then
    rm -f -- "$temporary"
    printf 'error: database archive failed\n' >&2
    return 1
  fi
  if ! chmod 0600 -- "$temporary"; then
    rm -f -- "$temporary"
    printf 'error: unable to protect temporary archive\n' >&2
    return 1
  fi

  published="$(archive_name "$prefix" "$backup_dir")"
  if ! mv -- "$temporary" "$published"; then
    rm -f -- "$temporary"
    printf 'error: unable to publish archive\n' >&2
    return 1
  fi
  if ! chmod 0600 -- "$published"; then
    printf 'error: unable to protect archive: %s\n' "$published" >&2
    return 1
  fi
  printf '%s\n' "$published"
}

rotate_archives() {
  local prefix=$1 backup_dir=$2 item path index
  local -a ordered=()

  while IFS= read -r -d '' item; do
    ordered+=("$item")
  done < <(
    for path in "$backup_dir"/"$prefix"-*.tar.gz; do
      [[ -f "$path" ]] || continue
      printf '%s\t%s\0' "$(stat -c '%Y' -- "$path")" "$path"
    done | sort -z -rn -k1,1 -k2,2
  )

  for ((index = 7; index < ${#ordered[@]}; index++)); do
    path="${ordered[index]#*$'\t'}"
    rm -f -- "$path" || return 1
  done
}

run_backup() {
  local mode=$1
  local archive was_active=0 rotation_failed=0

  if ! validate_archive_directories ||
    [[ ! -d "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" ]] ||
    [[ -L "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" ]]; then
    fail "active database directory is missing: $BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME"
    return 1
  fi

  if service_was_active; then
    was_active=1
  fi

  if ! systemctl --user stop "$SERVICE_NAME"; then
    printf 'error: failed to stop %s; no archive was created\n' "$SERVICE_NAME" >&2
    return 1
  fi

  if ! archive="$(create_archive "$mode" "$BRAIN_DEPLOY_DATA_DIR" "$BRAIN_DEPLOY_DB_NAME" "$BRAIN_DEPLOY_BACKUP_DIR")"; then
    recover_service "$was_active" || true
    return 1
  fi

  if ! rotate_archives "$mode" "$BRAIN_DEPLOY_BACKUP_DIR"; then
    rotation_failed=1
    printf 'error: archive rotation failed\n' >&2
  fi

  if ! systemctl --user start "$SERVICE_NAME"; then
    printf 'error: failed to start %s after archive\n' "$SERVICE_NAME" >&2
    recover_service "$was_active" || true
    return 1
  fi

  printf 'created %s\n' "$archive"
  if [[ "$rotation_failed" == 1 ]]; then
    return 1
  fi
  return 0
}

resolved_archive_path() {
  local requested=$1 backup_real archive_real
  backup_real="$(realpath -e -- "$BRAIN_DEPLOY_BACKUP_DIR")" || return 1
  archive_real="$(realpath -e -- "$requested")" || return 1
  [[ -f "$archive_real" ]] || return 1
  case "$archive_real" in
    "$backup_real"/*) printf '%s\n' "$archive_real"; return 0 ;;
    *) return 1 ;;
  esac
}

validate_archive() {
  local archive=$1 database_name=$2 backup_dir=$3
  local listing verbose entry normalized line member_type found=0
  listing="$(mktemp "$backup_dir/.restore-list-XXXXXX")" || return 1
  verbose="$(mktemp "$backup_dir/.restore-verbose-XXXXXX")" || {
    rm -f -- "$listing"
    return 1
  }

  if ! tar --list --gzip --file="$archive" >"$listing" ||
    ! tar --list --verbose --gzip --file="$archive" >"$verbose"; then
    rm -f -- "$listing" "$verbose"
    return 1
  fi

  # Links and special files are not needed in an embedded database archive.
  # Rejecting them prevents a link from redirecting extraction outside the root.
  while IFS= read -r line || [[ -n "$line" ]]; do
    member_type="${line:0:1}"
    case "$member_type" in
      -|d) ;;
      *)
        rm -f -- "$listing" "$verbose"
        return 1
        ;;
    esac
  done < "$verbose"

  while IFS= read -r entry || [[ -n "$entry" ]]; do
    [[ -n "$entry" ]] || continue
    normalized="$entry"
    while [[ "$normalized" == ./* ]]; do
      normalized="${normalized#./}"
    done
    if [[ "$normalized" == /* || "$normalized" == *"//"* ||
      "$normalized" == ".." || "$normalized" == ../* ||
      "$normalized" == */../* || "$normalized" == */.. ]]; then
      rm -f -- "$listing" "$verbose"
      return 1
    fi
    normalized="${normalized%/}"
    if [[ "$normalized" == "$database_name" ||
      "$normalized" == "$database_name"/* ]]; then
      found=1
    else
      rm -f -- "$listing" "$verbose"
      return 1
    fi
  done < "$listing"

  rm -f -- "$listing" "$verbose"
  [[ "$found" == 1 ]]
}

restore_archive() {
  local requested=$1 archive was_active=0 safety suffix

  if ! validate_archive_directories; then
    return 1
  fi
  if ! archive="$(resolved_archive_path "$requested")"; then
    fail "archive must be an existing file under $BRAIN_DEPLOY_BACKUP_DIR"
    return 1
  fi
  if ! validate_archive "$archive" "$BRAIN_DEPLOY_DB_NAME" "$BRAIN_DEPLOY_BACKUP_DIR"; then
    fail "archive contains invalid database entries: $requested"
    return 1
  fi
  if [[ ! -d "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" ||
    -L "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" ]]; then
    fail "active database directory is missing: $BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME"
    return 1
  fi

  if service_was_active; then
    was_active=1
  fi
  if ! systemctl --user stop "$SERVICE_NAME"; then
    printf 'error: failed to stop %s; data was not moved\n' "$SERVICE_NAME" >&2
    return 1
  fi

  safety="$BRAIN_DEPLOY_DATA_DIR/${BRAIN_DEPLOY_DB_NAME}.safety-$(date -u +%Y-%m-%dT%H%M%SZ)-$$"
  suffix=1
  while [[ -e "$safety" ]]; do
    safety="$BRAIN_DEPLOY_DATA_DIR/${BRAIN_DEPLOY_DB_NAME}.safety-$(date -u +%Y-%m-%dT%H%M%SZ)-$$-$suffix"
    suffix=$((suffix + 1))
  done
  if ! mv -- "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" "$safety"; then
    recover_service "$was_active" || true
    fail "unable to move the active database to $safety"
    return 1
  fi

  if ! tar --extract --gzip --file="$archive" --directory="$BRAIN_DEPLOY_DATA_DIR" ||
    [[ ! -d "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" ]]; then
    printf 'error: restore extraction failed; safety copy retained at %s\n' "$safety" >&2
    recover_service "$was_active" || true
    return 1
  fi

  if ! systemctl --user start "$SERVICE_NAME"; then
    printf 'error: failed to start %s; safety copy retained at %s\n' "$SERVICE_NAME" "$safety" >&2
    recover_service "$was_active" || true
    return 1
  fi

  printf 'restored %s; previous database retained at %s\n' "$archive" "$safety"
  return 0
}

usage() {
  printf 'usage: %s daily|pre-update|restore <archive>\n' "${BASH_SOURCE[0]}" >&2
}

if [[ $# -lt 1 ]]; then
  usage
  exit 1
fi

case "$1" in
  daily|pre-update)
    if [[ $# -ne 1 ]]; then
      usage
      exit 1
    fi
    pipeline_status=1
    if pipeline_is_non_idle; then
      pipeline_status=0
    else
      pipeline_status=$?
    fi
    case "$pipeline_status" in
      0)
        defer_or_fail_pipeline "$1" "intake pipeline is not idle"
        exit $?
        ;;
      1)
        ;;
      *)
        defer_or_fail_pipeline "$1" "unable to read a valid intake pipeline snapshot"
        exit $?
        ;;
    esac
    run_backup "$1"
    ;;
  restore)
    if [[ $# -ne 2 || -z "$2" ]]; then
      usage
      exit 1
    fi
    restore_archive "$2"
    ;;
  *)
    usage
    exit 1
    ;;
esac
