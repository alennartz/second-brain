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
    MOBILE_SERVER_BIND_ADDRESS="$(mobile_config_value MOBILE_SERVER_BIND_ADDRESS || true)"
    MOBILE_DEVTOOLS_PORT="$(mobile_config_value MOBILE_DEVTOOLS_PORT || true)"
}

mobile_require_server_url() {
    [[ -n "${MOBILE_SERVER_URL:-}" ]] || { mobile_error "MOBILE_SERVER_URL is required in $MOBILE_ENV_FILE"; return 1; }
    [[ "$MOBILE_SERVER_URL" =~ ^https?://[^[:space:]]+$ ]] || { mobile_error "MOBILE_SERVER_URL must be an http(s) URL"; return 1; }
    [[ "$MOBILE_SERVER_URL" != *'@'* ]] || { mobile_error "MOBILE_SERVER_URL must not contain credentials"; return 1; }

    local authority port host
    authority=${MOBILE_SERVER_URL#*://}
    authority=${authority%%/*}
    [[ "$authority" == *:* ]] || { mobile_error "MOBILE_SERVER_URL must include the mobile server port 8200"; return 1; }
    host=${authority%:*}
    port=${authority##*:}
    [[ -n "$host" ]] || { mobile_error "MOBILE_SERVER_URL must include a host"; return 1; }
    [[ "$port" =~ ^[1-9][0-9]*$ ]] || { mobile_error "MOBILE_SERVER_URL must use a decimal port"; return 1; }
    [[ "$port" == 8200 ]] || { mobile_error "MOBILE_SERVER_URL must use the isolated mobile server port 8200"; return 1; }
}

mobile_require_server_bind_address() {
    [[ -n "${MOBILE_SERVER_BIND_ADDRESS:-}" ]] || { mobile_error "MOBILE_SERVER_BIND_ADDRESS is required in $MOBILE_ENV_FILE"; return 1; }
    [[ "$MOBILE_SERVER_BIND_ADDRESS" =~ ^([0-9]{1,3}[.]){3}[0-9]{1,3}$ ]] || { mobile_error "MOBILE_SERVER_BIND_ADDRESS must be an IPv4 LAN address"; return 1; }
    [[ "$MOBILE_SERVER_BIND_ADDRESS" != 0.0.0.0 ]] || { mobile_error "MOBILE_SERVER_BIND_ADDRESS must not be the wildcard address 0.0.0.0"; return 1; }

    local octet
    local -a octets
    IFS=. read -r -a octets <<< "$MOBILE_SERVER_BIND_ADDRESS"
    for octet in "${octets[@]}"; do
        [[ "$octet" =~ ^(0|[1-9][0-9]{0,2})$ ]] || { mobile_error "MOBILE_SERVER_BIND_ADDRESS has an invalid IPv4 octet: $octet"; return 1; }
        (( 10#$octet <= 255 )) || { mobile_error "MOBILE_SERVER_BIND_ADDRESS has an invalid IPv4 octet: $octet"; return 1; }
    done
}

mobile_require_device() {
    [[ -n "${MOBILE_DEVICE:-}" ]] || { mobile_error "MOBILE_DEVICE is required in $MOBILE_ENV_FILE"; return 1; }
    [[ "$MOBILE_DEVICE" =~ ^[^[:space:]]+:[1-9][0-9]*$ ]] || { mobile_error "MOBILE_DEVICE must be a wireless ADB address such as 192.168.1.42:37123"; return 1; }

    local port=${MOBILE_DEVICE##*:}
    (( port > 0 && port <= 65535 )) || { mobile_error "MOBILE_DEVICE has an invalid port: $port"; return 1; }
}

mobile_require_devtools_port() {
    [[ -n "${MOBILE_DEVTOOLS_PORT:-}" ]] || { mobile_error "MOBILE_DEVTOOLS_PORT is required in $MOBILE_ENV_FILE"; return 1; }
    [[ "$MOBILE_DEVTOOLS_PORT" =~ ^[1-9][0-9]*$ ]] || { mobile_error "MOBILE_DEVTOOLS_PORT must be a decimal port without leading zeroes"; return 1; }
    (( MOBILE_DEVTOOLS_PORT > 0 && MOBILE_DEVTOOLS_PORT <= 65535 )) || { mobile_error "MOBILE_DEVTOOLS_PORT must be between 1 and 65535"; return 1; }
}

mobile_print_server_url() {
    printf 'MOBILE_SERVER_URL=%s\n' "$MOBILE_SERVER_URL"
    printf 'Enter this URL in the app on first launch.\n'
}

mobile_compose() {
    mobile_require_env_file || return
    (cd "$MOBILE_ROOT_DIR" && MOBILE_ENV_FILE="$MOBILE_ENV_FILE" docker compose --env-file "$MOBILE_ENV_FILE" --profile mobile "$@")
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
    local state output output_lower

    MOBILE_CONNECT_ERROR=""
    MOBILE_PAIRING_REQUIRED=false
    if ! output=$("$MOBILE_ADB" connect "$address" 2>&1); then
        MOBILE_CONNECT_ERROR=$output
        mobile_log "adb connect $address failed: ${output:-no diagnostic output}"
    elif [[ -n "$output" ]]; then
        mobile_log "adb connect $address: $output"
    fi
    output_lower=${output,,}
    if [[ "$output_lower" == *authenticat* || "$output_lower" == *pair* || "$output_lower" == *unauthorized* ]]; then
        MOBILE_PAIRING_REQUIRED=true
    fi

    # Wireless debugging can report connecting or authorizing for a short time.
    # Wait for the selected serial instead of treating that transient state as a
    # failed connection.
    for _ in {1..20}; do
        state=$(mobile_device_state "$address")
        case "$state" in
            device)
                return 0
                ;;
            unauthorized)
                MOBILE_PAIRING_REQUIRED=true
                return 1
                ;;
        esac
        sleep 0.5
    done
    state=$(mobile_device_state "$address")
    mobile_log "ADB device $address remained in state ${state:-absent} after waiting"
    return 1
}

mobile_mdns_candidates() {
    local output
    output=$("$MOBILE_ADB" mdns services 2>/dev/null || true)
    # Prefer TLS connect services. Group records by advertised host so one
    # phone offering legacy and TLS services is one candidate, not two.
    awk '
        function remember(address, is_tls, host) {
            host = address
            sub(/:[0-9]+$/, "", host)
            if (is_tls) tls[host] = address
            else if (!(host in tls)) legacy[host] = address
        }
        {
            service = ""
            if ($0 ~ /adb-tls-connect[.]_tcp/) service = "tls"
            else if ($0 ~ /adb[.]_tcp/ || $0 ~ /_adb[.]tcp/) service = "legacy"
            if (!service) next
            for (field = 1; field <= NF; field++) {
                if ($field ~ /^[^[:space:]]+:[0-9]+$/) {
                    remember($field, service == "tls")
                }
            }
        }
        END {
            for (host in tls) print tls[host]
            for (host in legacy) if (!(host in tls)) print legacy[host]
        }
    ' <<< "$output" | sort -u
}

mobile_mdns_pairing_candidates() {
    local output
    output=$("$MOBILE_ADB" mdns services 2>/dev/null || true)
    awk '/adb-tls-pairing[.]_tcp/ {
        for (field = 1; field <= NF; field++) {
            if ($field ~ /^[^[:space:]]+:[0-9]+$/) print $field
        }
    }' <<< "$output" | sort -u
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
    local target=${1:-the phone}
    local pairing_address=${2:-}
    mobile_log "ADB could not authorize $target. Approve wireless debugging on the phone."
    mobile_log "If pairing is required, find the _adb-tls-pairing._tcp address with:"
    mobile_log "  $MOBILE_ADB mdns services"
    if [[ -n "$pairing_address" ]]; then
        mobile_log "Advertised pairing address: $pairing_address"
    fi
    mobile_log "Then run once on the host:"
    mobile_log "  $MOBILE_ADB pair <pairing-address> <pairing-code>"
    mobile_log "Pairing addresses and codes are one-time inputs and are not saved."
}

# Logs go to stderr. The selected serial is the only stdout value, so callers
# can pass it without parsing human-readable status output.
mobile_select_device() {
    local target=$1
    local state candidate candidate_state unauthorized_target="" pairing_address=""
    local pairing_required=false
    local -a candidates=() pairing_services=()

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
    [[ "${MOBILE_PAIRING_REQUIRED:-false}" == true ]] && pairing_required=true
    state=$(mobile_device_state "$target")
    [[ "$state" == "unauthorized" ]] && unauthorized_target="$target"

    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] && candidates+=("$candidate")
    done < <(mobile_mdns_candidates)
    while IFS= read -r candidate; do
        [[ -n "$candidate" ]] && pairing_services+=("$candidate")
    done < <(mobile_mdns_pairing_candidates)
    if (( ${#pairing_services[@]} > 0 )); then
        pairing_address=${pairing_services[0]}
    fi

    if (( ${#candidates[@]} > 1 )); then
        mobile_error "more than one wireless ADB device was discovered; set MOBILE_DEVICE explicitly"
        printf '  %s\n' "${candidates[@]}" >&2
        return 1
    fi

    if (( ${#candidates[@]} == 1 )); then
        candidate_state=$(mobile_device_state "${candidates[0]}")
        [[ "$candidate_state" == "unauthorized" ]] && unauthorized_target="${candidates[0]}"
        if [[ "$candidate_state" == "device" ]]; then
            mobile_report_device "${candidates[0]}"
            printf '%s\n' "${candidates[0]}"
            return 0
        fi
        if mobile_connect_address "${candidates[0]}"; then
            mobile_log "connected through mDNS at ${candidates[0]}"
            mobile_report_device "${candidates[0]}"
            printf '%s\n' "${candidates[0]}"
            return 0
        fi
        [[ "${MOBILE_PAIRING_REQUIRED:-false}" == true ]] && pairing_required=true
        candidate_state=$(mobile_device_state "${candidates[0]}")
        [[ "$candidate_state" == "unauthorized" ]] && unauthorized_target="${candidates[0]}"
    fi

    if [[ -n "$unauthorized_target" || "$pairing_required" == true || -n "$pairing_address" ]]; then
        mobile_pairing_instructions "${unauthorized_target:-$target}" "$pairing_address"
    fi
    mobile_error "could not authorize a wireless ADB device at $target"
    return 1
}
