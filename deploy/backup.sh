#!/usr/bin/env bash
# Create and restore local archives of the active database.
#
# Public interface:
#   backup.sh daily
#   backup.sh pre-update
#   backup.sh restore <archive>
set -euo pipefail
umask 077

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

# Operation state is shared with the EXIT trap. The trap handles interrupts,
# archive failures, and partial restores without starting an inactive service.
LOCK_FD=""
OP_WAS_ACTIVE=0
OP_STOP_REQUIRED=0
OP_STOPPED=0
OP_TEMP=""
OP_TEMP_LIST=""
OP_TEMP_VERBOSE=""
CREATED_ARCHIVE=""
PUBLISHED_ARCHIVE=""
OP_SAFETY=""
OP_ACTIVE_MOVED=0
OP_RESTORE_COMMITTED=0
OP_RECOVER_ALLOWED=1

cleanup_operation() {
  local status=$1
  # Cleanup must not replace the original failure status.
  set +e
  trap - INT TERM

  local temporary recovery_path
  for temporary in "$OP_TEMP" "$OP_TEMP_LIST" "$OP_TEMP_VERBOSE"; do
    [[ -n "$temporary" ]] || continue
    if [[ -d "$temporary" ]]; then
      rm -rf -- "$temporary"
    else
      rm -f -- "$temporary"
    fi
  done
  OP_TEMP=""
  OP_TEMP_LIST=""
  OP_TEMP_VERBOSE=""

  # A failed restore must never start the service on a missing or partial
  # database. Rebuild the active path through a temporary copy, then publish
  # it atomically while retaining the safety copy.
  if [[ "$status" -ne 0 && "$OP_ACTIVE_MOVED" == 1 &&
    "$OP_RESTORE_COMMITTED" == 0 && "$OP_RECOVER_ALLOWED" == 1 &&
    -n "$OP_SAFETY" && -d "$OP_SAFETY" &&
    ! -e "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" ]]; then
    recovery_path="$BRAIN_DEPLOY_DATA_DIR/.${BRAIN_DEPLOY_DB_NAME}.recovery-$$"
    if cp -a -- "$OP_SAFETY" "$recovery_path" &&
      mv -- "$recovery_path" "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME"; then
      :
    else
      rm -rf -- "$recovery_path"
      printf 'error: unable to restore the safety database; service remains stopped\n' >&2
      OP_RECOVER_ALLOWED=0
    fi
  fi

  if [[ "$status" -ne 0 && "$OP_STOPPED" == 1 &&
    "$OP_WAS_ACTIVE" == 1 && "$OP_RECOVER_ALLOWED" == 1 ]]; then
    if systemctl --user start "$SERVICE_NAME"; then
      OP_STOPPED=0
    else
      printf 'error: failed to recover %s\n' "$SERVICE_NAME" >&2
    fi
  fi
}

on_exit() {
  local status=$?
  trap - EXIT
  cleanup_operation "$status"
  exit "$status"
}

trap on_exit EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

pipeline_activity_json() {
  jq --raw-output --slurp '
    if length != 1 then
      error("invalid pipeline response")
    elif .[0] | type != "object" then
      error("invalid pipeline response")
    else
      .[0] as $snapshot
      | def count($field):
          (if $snapshot | has($field) then $snapshot[$field] else 0 end)
          | if (type == "number" and . >= 0 and floor == .) then
              .
            else
              error("invalid activity field")
            end;
        [
          ($snapshot | count("ready")),
          ($snapshot | count("leased")),
          ($snapshot | count("retry_wait")),
          ($snapshot | count("active_leases"))
        ]
        | any(.[]; . > 0)
    end
  '
}

pipeline_is_non_idle() {
  local response parsed
  if ! response="$(curl --fail --silent --show-error --max-time 10 "$PIPELINE_URL")"; then
    return 2
  fi
  if ! parsed="$(pipeline_activity_json <<<"$response")"; then
    return 2
  fi

  case "$parsed" in
    true) return 0 ;;
    false) return 1 ;;
    *) return 2 ;;
  esac
}

defer_or_fail_pipeline() {
  local mode=$1 reason=$2
  if [[ "$mode" == "daily" ]]; then
    printf 'deferred: %s\n' "$reason"
    return 0
  fi
  fail "$reason"
}

service_state() {
  local state
  if ! state="$(systemctl --user show "$SERVICE_NAME" \
    --property=ActiveState --value 2>/dev/null)"; then
    return 2
  fi
  case "$state" in
    active) return 0 ;;
    inactive) return 1 ;;
    failed) return 3 ;;
    *) return 2 ;;
  esac
}

prepare_operation() {
  OP_WAS_ACTIVE=0
  OP_STOP_REQUIRED=0
  OP_STOPPED=0
  OP_TEMP=""
  OP_TEMP_LIST=""
  OP_TEMP_VERBOSE=""
  CREATED_ARCHIVE=""
  PUBLISHED_ARCHIVE=""
  OP_SAFETY=""
  OP_ACTIVE_MOVED=0
  OP_RESTORE_COMMITTED=0
  OP_RECOVER_ALLOWED=1
  local status
  if service_state; then
    status=0
  else
    status=$?
  fi
  case "$status" in
    0)
      OP_WAS_ACTIVE=1
      OP_STOP_REQUIRED=1
      ;;
    1)
      ;;
    3)
      # Stop a failed unit before archiving so Restart=on-failure cannot race
      # the snapshot. Preserve its inactive state after a successful archive.
      OP_STOP_REQUIRED=1
      ;;
    *)
      fail "unable to determine the state of $SERVICE_NAME"
      return 1
      ;;
  esac
}

verify_clean_stop() {
  local result
  if ! result="$(systemctl --user show "$SERVICE_NAME" \
    --property=Result --value 2>/dev/null)"; then
    fail "unable to verify the stop result for $SERVICE_NAME"
    return 1
  fi
  if [[ "$result" != "success" ]]; then
    fail "$SERVICE_NAME stopped with result $result"
    return 1
  fi
}

acquire_lock() {
  if [[ -n "${BRAIN_DEPLOY_LOCK_FD:-}" ]]; then
    if ! : >&"$BRAIN_DEPLOY_LOCK_FD"; then
      fail "inherited deployment lock is not available"
      return 1
    fi
    LOCK_FD="$BRAIN_DEPLOY_LOCK_FD"
    return 0
  fi
  if ! exec {LOCK_FD}>"$BRAIN_DEPLOY_BACKUP_DIR/.backup.lock"; then
    fail "unable to open backup lock in $BRAIN_DEPLOY_BACKUP_DIR"
    return 1
  fi
  if ! flock --exclusive "$LOCK_FD"; then
    fail "unable to acquire backup lock in $BRAIN_DEPLOY_BACKUP_DIR"
    return 1
  fi
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

publish_archive() {
  local prefix=$1 temporary=$2 backup_dir=$3
  local stamp candidate suffix=0

  stamp="$(date -u +%Y-%m-%dT%H%M%SZ)"
  while ((suffix < 100000)); do
    if ((suffix == 0)); then
      candidate="$backup_dir/${prefix}-${stamp}.tar.gz"
    else
      candidate="$backup_dir/${prefix}-${stamp}-${suffix}.tar.gz"
    fi

    # mv -n provides an atomic no-clobber publication. If another process
    # selected this name, the temporary file remains and the next suffix wins.
    if mv -n -- "$temporary" "$candidate" && [[ ! -e "$temporary" ]]; then
      if ! chmod 0600 -- "$candidate"; then
        rm -f -- "$candidate"
        return 1
      fi
      OP_TEMP=""
      PUBLISHED_ARCHIVE="$candidate"
      return 0
    fi
    suffix=$((suffix + 1))
  done

  return 1
}

create_archive() {
  local prefix=$1 data_dir=$2 database_name=$3 backup_dir=$4
  local temporary

  if [[ ! -d "$data_dir/$database_name" || -L "$data_dir/$database_name" ]]; then
    printf 'error: active database directory is missing: %s\n' "$data_dir/$database_name" >&2
    return 1
  fi

  temporary="$(mktemp "$backup_dir/.${prefix}-XXXXXX.tar.gz.tmp")" || {
    printf 'error: unable to create temporary archive in %s\n' "$backup_dir" >&2
    return 1
  }
  OP_TEMP="$temporary"

  if ! (cd -- "$data_dir" && tar --create --gzip --file="$temporary" -- "$database_name"); then
    printf 'error: database archive failed\n' >&2
    return 1
  fi
  if ! chmod 0600 -- "$temporary"; then
    printf 'error: unable to protect temporary archive\n' >&2
    return 1
  fi

  if ! publish_archive "$prefix" "$temporary" "$backup_dir"; then
    printf 'error: unable to publish archive\n' >&2
    return 1
  fi
  CREATED_ARCHIVE="$PUBLISHED_ARCHIVE"
}

rotate_archives() {
  local prefix=$1 backup_dir=$2 path base timestamp suffix record index
  local pattern="^${prefix}-([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{6}Z)(-([0-9]+))?\\.tar\\.gz$"
  local -a ordered=()

  while IFS= read -r -d '' record; do
    ordered+=("$backup_dir/${record##*$'\t'}")
  done < <(
    for path in "$backup_dir"/*.tar.gz; do
      [[ -f "$path" ]] || continue
      base="${path##*/}"
      [[ "$base" =~ $pattern ]] || continue
      timestamp="${BASH_REMATCH[1]}"
      suffix="${BASH_REMATCH[3]:-0}"
      # Sort the timestamp first and the numeric collision suffix second.
      printf '%s%010d\t%s\0' "$timestamp" "$suffix" "$base"
    done | sort -z -r
  )

  for ((index = 7; index < ${#ordered[@]}; index++)); do
    rm -f -- "${ordered[index]}" || return 1
  done
}

run_backup() {
  local mode=$1 archive rotation_failed=0 pipeline_status

  if ! validate_archive_directories; then
    return 1
  fi
  if ! acquire_lock; then
    return 1
  fi
  if ! prepare_operation; then
    return 1
  fi

  # An inactive service cannot answer the pipeline endpoint. Its stopped state
  # is already quiescent, so skip that check and preserve the state below.
  if ((OP_WAS_ACTIVE == 1)); then
    pipeline_status=1
    if pipeline_is_non_idle; then
      pipeline_status=0
    else
      pipeline_status=$?
    fi
    case "$pipeline_status" in
      0)
        defer_or_fail_pipeline "$mode" "intake pipeline is not idle"
        return $?
        ;;
      1)
        ;;
      *)
        defer_or_fail_pipeline "$mode" "unable to read a valid intake pipeline snapshot"
        return $?
        ;;
    esac
  fi

  if [[ ! -d "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" ||
    -L "$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME" ]]; then
    fail "active database directory is missing: $BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME"
    return 1
  fi

  if ((OP_STOP_REQUIRED == 1)); then
    # Mark the service for recovery before invoking stop. An interrupt during
    # the stop command must not leave a previously active service down.
    OP_STOPPED=1
    if ! systemctl --user stop "$SERVICE_NAME"; then
      printf 'error: failed to stop %s; no archive was created\n' "$SERVICE_NAME" >&2
      return 1
    fi
    if ! verify_clean_stop; then
      return 1
    fi
  fi

  if ! create_archive "$mode" "$BRAIN_DEPLOY_DATA_DIR" "$BRAIN_DEPLOY_DB_NAME" "$BRAIN_DEPLOY_BACKUP_DIR"; then
    return 1
  fi
  archive="$CREATED_ARCHIVE"

  if ! rotate_archives "$mode" "$BRAIN_DEPLOY_BACKUP_DIR"; then
    rotation_failed=1
    printf 'error: archive rotation failed\n' >&2
  fi

  if ((OP_WAS_ACTIVE == 1)); then
    if ! systemctl --user start "$SERVICE_NAME"; then
      printf 'error: failed to start %s after archive\n' "$SERVICE_NAME" >&2
      return 1
    fi
    OP_STOPPED=0
  else
    OP_STOPPED=0
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
  OP_TEMP_LIST="$listing"
  verbose="$(mktemp "$backup_dir/.restore-verbose-XXXXXX")" || {
    rm -f -- "$listing"
    OP_TEMP_LIST=""
    return 1
  }
  OP_TEMP_VERBOSE="$verbose"

  if ! tar --list --gzip --file="$archive" >"$listing" ||
    ! tar --list --verbose --gzip --file="$archive" >"$verbose"; then
    rm -f -- "$listing" "$verbose"
    OP_TEMP_LIST=""
    OP_TEMP_VERBOSE=""
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
        OP_TEMP_LIST=""
        OP_TEMP_VERBOSE=""
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
      OP_TEMP_LIST=""
      OP_TEMP_VERBOSE=""
      return 1
    fi
    normalized="${normalized%/}"
    if [[ "$normalized" == "$database_name" ||
      "$normalized" == "$database_name"/* ]]; then
      found=1
    else
      rm -f -- "$listing" "$verbose"
      OP_TEMP_LIST=""
      OP_TEMP_VERBOSE=""
      return 1
    fi
  done < "$listing"

  rm -f -- "$listing" "$verbose"
  OP_TEMP_LIST=""
  OP_TEMP_VERBOSE=""
  [[ "$found" == 1 ]]
}

restore_archive() {
  local requested=$1 archive safety suffix stage had_active=0
  local active_path="$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME"

  if ! validate_archive_directories; then
    return 1
  fi
  if ! acquire_lock; then
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
  if [[ -L "$active_path" || (-e "$active_path" && ! -d "$active_path") ]]; then
    fail "active database path is not a directory: $active_path"
    return 1
  fi
  if [[ -d "$active_path" ]]; then
    had_active=1
  fi

  if ! prepare_operation; then
    return 1
  fi
  if ((had_active == 0)); then
    # There is no safety copy to restore if extraction fails. Never start a
    # service that could create a fresh, incorrect database in that case.
    OP_RECOVER_ALLOWED=0
  fi

  if ((OP_STOP_REQUIRED == 1)); then
    OP_STOPPED=1
    if ! systemctl --user stop "$SERVICE_NAME"; then
      printf 'error: failed to stop %s; data was not moved\n' "$SERVICE_NAME" >&2
      return 1
    fi
    if ! verify_clean_stop; then
      return 1
    fi
  fi

  if ((had_active == 1)); then
    safety="$BRAIN_DEPLOY_DATA_DIR/${BRAIN_DEPLOY_DB_NAME}.safety-$(date -u +%Y-%m-%dT%H%M%SZ)-$$"
    suffix=1
    while [[ -e "$safety" || -L "$safety" ]]; do
      safety="$BRAIN_DEPLOY_DATA_DIR/${BRAIN_DEPLOY_DB_NAME}.safety-$(date -u +%Y-%m-%dT%H%M%SZ)-$$-$suffix"
      suffix=$((suffix + 1))
    done
    OP_SAFETY="$safety"
    OP_ACTIVE_MOVED=1
    if ! mv -- "$active_path" "$safety"; then
      fail "unable to move the active database to $safety"
      return 1
    fi
  fi

  stage="$(mktemp -d "$BRAIN_DEPLOY_DATA_DIR/.restore-staging-XXXXXX")" || {
    printf 'error: unable to create restore staging directory\n' >&2
    return 1
  }
  OP_TEMP="$stage"

  if ! tar --extract --gzip --file="$archive" --directory="$stage" ||
    [[ ! -d "$stage/$BRAIN_DEPLOY_DB_NAME" ||
      -L "$stage/$BRAIN_DEPLOY_DB_NAME" ]]; then
    printf 'error: restore extraction failed; safety copy retained at %s\n' "${OP_SAFETY:-none}" >&2
    return 1
  fi

  if [[ -e "$active_path" || -L "$active_path" ]] ||
    ! mv -- "$stage/$BRAIN_DEPLOY_DB_NAME" "$active_path"; then
    printf 'error: unable to publish restored database; safety copy retained at %s\n' "${OP_SAFETY:-none}" >&2
    return 1
  fi
  rm -rf -- "$stage"
  OP_TEMP=""
  OP_RESTORE_COMMITTED=1
  if ((had_active == 0)); then
    # The staged database is now valid, so startup recovery is safe.
    OP_RECOVER_ALLOWED=1
  fi

  if ! systemctl --user start "$SERVICE_NAME"; then
    printf 'error: failed to start %s; safety copy retained at %s\n' "$SERVICE_NAME" "${OP_SAFETY:-none}" >&2
    return 1
  fi
  OP_STOPPED=0

  printf 'restored %s; previous database retained at %s\n' "$archive" "${OP_SAFETY:-none}"
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
