#!/usr/bin/env bash
set -Eeuo pipefail

root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
mkdir "$work/bin"

printf '#!/usr/bin/env bash\nexit 0\n' > "$work/bin/sleep"
chmod +x "$work/bin/sleep"

cat > "$work/bin/adb" <<'ADB'
#!/usr/bin/env bash
set -Eeuo pipefail
case "$1" in
    start-server) exit 0 ;;
    devices)
        printf 'List of devices attached\n'
        if [[ -f "$DISCOVERY_STATE" ]]; then
            printf '192.168.1.240:40233 device\n'
        fi
        ;;
    connect)
        if [[ "$2" == 192.168.1.240:40233 ]]; then
            touch "$DISCOVERY_STATE"
            printf 'connected to %s\n' "$2"
        else
            printf 'cannot resolve host\n' >&2
            exit 1
        fi
        ;;
    mdns)
        printf 'List of discovered mdns services%s' "$DISCOVERY_EOL"
        printf 'adb-phone\t_adb-tls-connect._tcp\t192.168.1.240:40233%s' "$DISCOVERY_EOL"
        printf 'adb-pair\t_adb-tls-pairing._tcp\t192.168.1.240:49999%s' "$DISCOVERY_EOL"
        ;;
    -s)
        case "${*: -1}" in
            ro.product.model) printf 'Pixel 8\n' ;;
            ro.build.version.release) printf '17\n' ;;
            *) exit 1 ;;
        esac
        ;;
    *) exit 1 ;;
esac
ADB
chmod +x "$work/bin/adb"
printf 'MOBILE_DEVICE=Android_old.local:36479\n' > "$work/mobile.env"

for format in unix windows; do
    if [[ "$format" == windows ]]; then eol=$'\r\n'; else eol=$'\n'; fi
    state="$work/$format.state"
    if ! output=$(PATH="$work/bin:$PATH" MOBILE_ADB="$work/bin/adb" \
        MOBILE_ENV_FILE="$work/mobile.env" DISCOVERY_STATE="$state" \
        DISCOVERY_EOL="$eol" bash "$root/tools/mobile/mobile-connect" 2>"$work/$format.error"); then
        printf 'FAIL: stale address recovery with %s mDNS output\n' "$format" >&2
        while IFS= read -r line; do printf '%s\n' "$line" >&2; done < "$work/$format.error"
        exit 1
    fi
    [[ "$output" == 'ADB_SERIAL=192.168.1.240:40233' ]] || {
        printf 'FAIL: did not select the advertised connect endpoint for %s\n' "$format" >&2
        exit 1
    }
    [[ $(<"$work/mobile.env") == 'MOBILE_DEVICE=Android_old.local:36479' ]] || {
        printf 'FAIL: discovery rewrote local configuration\n' >&2
        exit 1
    }
    printf 'PASS: stale address recovery with %s mDNS output\n' "$format"
done
