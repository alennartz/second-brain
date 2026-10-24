#!/usr/bin/env bash

# Shared paths, configuration readers, dependency checks, and host-device helpers.
# This file does not source the local environment file. Provider credentials stay
# outside the Flutter container and are read only by Compose.

set -o pipefail

MOBILE_TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MOBILE_ROOT_DIR="$(cd "$MOBILE_TOOL_DIR/../.." && pwd)"
MOBILE_ENV_FILE="${MOBILE_ENV_FILE:-$MOBILE_ROOT_DIR/.env.mobile.local}"
MOBILE_ADB="${MOBILE_ADB:-/home/alenna/android/platform-tools/adb}"
MOBILE_IMAGE="${MOBILE_IMAGE:-second-brain-mobile-toolchain}"
MOBILE_PUB_CACHE_VOLUME="${MOBILE_PUB_CACHE_VOLUME:-second-brain-mobile-pub-cache}"
MOBILE_GRADLE_CACHE_VOLUME="${MOBILE_GRADLE_CACHE_VOLUME:-second-brain-mobile-gradle-cache}"
MOBILE_APK_PATH="$MOBILE_ROOT_DIR/client/mobile/build/app/outputs/flutter-apk/app-debug.apk"

mobile_error() {
    printf 'mobile: %s\n' "$*" >&2
    return 1
}

mobile_log() {
    printf 'mobile: %s\n' "$*" >&2
}

mobile_require_command() {
    local command_name=$1
    command -v "$command_name" >/dev/null 2>&1 || mobile_error "required command not found: $command_name"
}

mobile_require_linux() {
    [[ "$(uname -s)" == "Linux" ]] || mobile_error "host-network and ADB commands require Linux"
}

mobile_require_docker() {
    mobile_require_command docker || return
    docker info >/dev/null 2>&1 || mobile_error "Docker daemon is not available"
}

mobile_require_compose() {
    mobile_require_docker || return
    docker compose version >/dev/null 2>&1 || mobile_error "Docker Compose is not available"
}

mobile_require_adb() {
    [[ -x "$MOBILE_ADB" ]] || mobile_error "ADB executable is not available: $MOBILE_ADB"
}

mobile_require_env_file() {
    [[ -f "$MOBILE_ENV_FILE" ]] || mobile_error "missing $MOBILE_ENV_FILE; copy .env.mobile.example and fill local values"
}

# Read one simple dotenv value without evaluating the file. Values may be
# unquoted or surrounded by matching single or double quotes.
mobile_config_value() {
    local key=$1
    local line value

    while IFS= read -r line || [[ -n "$line" ]]; do
        line=${line%$'\r'}
        [[ "$line" =~ ^[[:space:]]*# ]] && continue
        [[ "$line" =~ ^[[:space:]]*$ ]] && continue
        if [[ "$line" =~ ^[[:space:]]*${key}[[:space:]]*=[[:space:]]*(.*)$ ]]; then
            value=${BASH_REMATCH[1]}
            if [[ "$value" == \"*\" && "$value" == *\" ]]; then
                value=${value:1:${#value}-2}
            elif [[ "$value" == \'*\' && "$value" == *\' ]]; then
                value=${value:1:${#value}-2}
            else
                value="${value%%[[:space:]]#*}"
                value="${value%${value##*[![:space:]]}}"
            fi
            printf '%s' "$value"
            return 0
        fi
    done < "$MOBILE_ENV_FILE"

    return 1
}

mobile_load_config() {
    mobile_require_env_file || return
    MOBILE_DEVICE="$(mobile_config_value MOBILE_DEVICE || true)"
    MOBILE_SERVER_URL="$(mobile_config_value MOBILE_SERVER_URL || true)"
    MOBILE_DEVTOOLS_PORT="$(mobile_config_value MOBILE_DEVTOOLS_PORT || true)"
}

mobile_require_server_url() {
    [[ -n "${MOBILE_SERVER_URL:-}" ]] || mobile_error "MOBILE_SERVER_URL is required in $MOBILE_ENV_FILE"
    [[ "$MOBILE_SERVER_URL" =~ ^https?://[^[:space:]]+$ ]] || mobile_error "MOBILE_SERVER_URL must be an http(s) URL"
    [[ "$MOBILE_SERVER_URL" != *'@'* ]] || mobile_error "MOBILE_SERVER_URL must not contain credentials"
}

mobile_require_device() {
    [[ -n "${MOBILE_DEVICE:-}" ]] || mobile_error "MOBILE_DEVICE is required in $MOBILE_ENV_FILE"
    [[ "$MOBILE_DEVICE" =~ ^[^[:space:]]+:[0-9]+$ ]] || mobile_error "MOBILE_DEVICE must be a wireless ADB address such as 192.168.1.42:37123"

    local port=${MOBILE_DEVICE##*:}
    (( port > 0 && port <= 65535 )) || mobile_error "MOBILE_DEVICE has an invalid port: $port"
}

mobile_require_devtools_port() {
    [[ -n "${MOBILE_DEVTOOLS_PORT:-}" ]] || mobile_error "MOBILE_DEVTOOLS_PORT is required in $MOBILE_ENV_FILE"
    [[ "$MOBILE_DEVTOOLS_PORT" =~ ^[0-9]+$ ]] || mobile_error "MOBILE_DEVTOOLS_PORT must be an integer"
    (( MOBILE_DEVTOOLS_PORT > 0 && MOBILE_DEVTOOLS_PORT <= 65535 )) || mobile_error "MOBILE_DEVTOOLS_PORT must be between 1 and 65535"
}

mobile_print_server_url() {
    printf 'MOBILE_SERVER_URL=%s\n' "$MOBILE_SERVER_URL"
    printf 'Enter this URL in the app on first launch.\n'
}

mobile_compose() {
    (cd "$MOBILE_ROOT_DIR" && docker compose --profile mobile "$@")
}

mobile_setup_adb() {
    mobile_require_adb || return
    # Keep both the client and daemon on the loopback ADB socket. Do not inherit
    # a caller-selected remote ADB server.
    export ADB_SERVER_SOCKET=tcp:127.0.0.1:5037
    "$MOBILE_ADB" start-server >/dev/null 2>&1 || mobile_error "could not start the host ADB server on 127.0.0.1:5037"
}

mobile_device_state() {
    local serial=$1
    "$MOBILE_ADB" devices 2>/dev/null | awk -v serial="$serial" '$1 == serial { print $2; exit }'
}

mobile_connect_address() {
    local address=$1
    local state

    "$MOBILE_ADB" connect "$address" >/dev/null 2>&1 || return 1
    state=$(mobile_device_state "$address")
    [[ "$state" == "device" ]] || return 1
    return 0
}

mobile_mdns_candidates() {
    local output
    output=$("$MOBILE_ADB" mdns services 2>/dev/null || true)
    awk '
        /adb-tls-connect[.]_tcp/ || /_adb[.]_tcp/ {
            for (field = 1; field <= NF; field++) {
                if ($field ~ /^[^[:space:]]+:[0-9]+$/) print $field
            }
        }
    ' <<< "$output" | sort -u
}

mobile_report_device() {
    local serial=$1
    local model android_version

    model=$("$MOBILE_ADB" -s "$serial" shell getprop ro.product.model 2>/dev/null | tr -d '\r\n' || true)
    android_version=$("$MOBILE_ADB" -s "$serial" shell getprop ro.build.version.release 2>/dev/null | tr -d '\r\n' || true)
    [[ -n "$model" ]] || model=unknown
    [[ -n "$android_version" ]] || android_version=unknown
    mobile_log "selected device: serial=$serial model=$model android=$android_version"
}

mobile_pairing_instructions() {
    local target=$1
    mobile_log "ADB reports $target as unauthorized. Approve wireless debugging on the phone."
    mobile_log "If pairing is required, find the _adb-tls-pairing._tcp address with:"
    mobile_log "  $MOBILE_ADB mdns services"
    mobile_log "Then run once on the host:"
    mobile_log "  $MOBILE_ADB pair <pairing-address> <pairing-code>"
    mobile_log "Pairing addresses and codes are one-time inputs and are not saved."
}

# Logs go to stderr. The selected serial is the only stdout value, so callers
# can pass it without parsing human-readable status output.
mobile_select_device() {
    local target=$1
    local state candidate candidate_state unauthorized_target=""
    local -a candidates=()

    mobile_setup_adb || return
    state=$(mobile_device_state "$target")
    [[ "$state" == "unauthorized" ]] && unauthorized_target="$target"
    if [[ "$state" == "device" ]]; then
        mobile_report_device "$target"
        printf '%s\n' "$target"
        return 0
    fi

    if mobile_connect_address "$target"; then
        mobile_report_device "$target"
        printf '%s\n' "$target"
        return 0
    fi
    state=$(mobile_device_state "$target")
    [[ "$state" == "unauthorized" ]] && unauthorized_target="$target"

    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] && candidates+=("$candidate")
    done < <(mobile_mdns_candidates)

    if (( ${#candidates[@]} > 1 )); then
        mobile_error "more than one wireless ADB device was discovered; set MOBILE_DEVICE explicitly"
        printf '  %s\n' "${candidates[@]}" >&2
        return 1
    fi

    if (( ${#candidates[@]} == 1 )); then
        candidate_state=$(mobile_device_state "${candidates[0]}")
        [[ "$candidate_state" == "unauthorized" ]] && unauthorized_target="${candidates[0]}"
        if mobile_connect_address "${candidates[0]}"; then
            mobile_log "connected through mDNS at ${candidates[0]}"
            mobile_report_device "${candidates[0]}"
            printf '%s\n' "${candidates[0]}"
            return 0
        fi
        candidate_state=$(mobile_device_state "${candidates[0]}")
        [[ "$candidate_state" == "unauthorized" ]] && unauthorized_target="${candidates[0]}"
    fi

    if [[ -n "$unauthorized_target" ]]; then
        mobile_pairing_instructions "$unauthorized_target"
    fi
    mobile_error "could not authorize a wireless ADB device at $target"
    return 1
}
