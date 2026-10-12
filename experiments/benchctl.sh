#!/usr/bin/env bash
# Manage resumable benchmark runs as systemd user services.
# Usage: experiments/benchctl.sh {start|resume|status|stop|log} NAME [NOTES]
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ACTION="${1:-}"
NAME="${2:-}"
NOTES="${3:-}"
PORT="${EXPERIMENT_PORT:-8101}"

if [[ -z "$ACTION" || -z "$NAME" ]]; then
  echo "Usage: $0 {start|resume|status|stop|log} NAME [NOTES]" >&2
  exit 2
fi
if [[ ! "$NAME" =~ ^[a-zA-Z0-9_-]+$ ]]; then
  echo "error: NAME can contain only letters, numbers, underscore, and dash" >&2
  exit 2
fi

UNIT="brain-benchmark-${NAME}.service"
RUN_DIR="$ROOT/experiments/data/$NAME"
STATE="$RUN_DIR/state.json"
LOG="$ROOT/experiments/data/${NAME}-run.log"
PYTHON="$ROOT/.venv/bin/python"
SCRIPT="$ROOT/experiments/run_experiment.py"
ENV_ARGS=()
for key in BRAIN_TEST_MODE BRAIN_REASONING_MODEL BRAIN_EMBEDDING_MODEL \
  BRAIN_REASONING_BASE_URL BRAIN_EMBEDDING_BASE_URL BENCH_OP_TIMEOUT; do
  if [[ -v $key ]]; then
    ENV_ARGS+=(--setenv "$key=${!key}")
  fi
done

case "$ACTION" in
  start)
    mkdir -p "$RUN_DIR"
    if systemctl --user is-active --quiet "$UNIT"; then
      echo "$UNIT is already running"
      exit 0
    fi
    if [[ -f "$STATE" ]] && grep -q '"phase": "done"' "$STATE"; then
      echo "error: $NAME is complete; use a new name for a new benchmark" >&2
      exit 1
    fi
    systemctl --user reset-failed "$UNIT" >/dev/null 2>&1 || true
    systemd-run --user --unit="$UNIT" \
      --property=Restart=on-failure \
      --property=RestartSec=15s \
      --property="WorkingDirectory=$ROOT" \
      --property="Environment=EXPERIMENT_PORT=$PORT" \
      --property="StandardOutput=append:$LOG" \
      --property="StandardError=append:$LOG" \
      --collect "${ENV_ARGS[@]}" -- "$PYTHON" -u "$SCRIPT" "$NAME" "$NOTES"
    echo "started $UNIT (port $PORT)"
    ;;
  resume)
    mkdir -p "$RUN_DIR"
    if [[ ! -f "$STATE" ]]; then
      echo "error: no saved run state for $NAME; use start" >&2
      exit 1
    fi
    if systemctl --user is-active --quiet "$UNIT"; then
      echo "$UNIT is already running"
      exit 0
    fi
    systemctl --user reset-failed "$UNIT" >/dev/null 2>&1 || true
    systemd-run --user --unit="$UNIT" \
      --property=Restart=on-failure \
      --property=RestartSec=15s \
      --property="WorkingDirectory=$ROOT" \
      --property="Environment=EXPERIMENT_PORT=$PORT" \
      --property="StandardOutput=append:$LOG" \
      --property="StandardError=append:$LOG" \
      --collect "${ENV_ARGS[@]}" -- "$PYTHON" -u "$SCRIPT" "$NAME"
    echo "resumed $UNIT"
    ;;
  status)
    systemctl --user status "$UNIT" --no-pager || true
    if [[ -f "$STATE" ]]; then
      python3 - "$STATE" <<'PY'
import json, sys, time
with open(sys.argv[1]) as f:
    d = json.load(f)
cur = d.get("current") or {}
active = f" | current={cur.get('label')} elapsed={time.time()-cur['started_epoch']:.0f}s" if cur.get("started_epoch") else ""
print(f"state: phase={d['phase']} ingest={len(d['ingest'])}/30 recall={len(d['recall'])}/9 graph={len(d['graph'])}/20{active}")
print(f"updated: {d.get('updated_utc', 'not yet')}")
PY
    else
      echo "state: not started"
    fi
    ;;
  stop)
    if ! systemctl --user is-active --quiet "$UNIT"; then
      echo "$UNIT is not running; state remains available"
      exit 0
    fi
    systemctl --user stop "$UNIT"
    echo "stopped $UNIT; state is saved. Resume with: $0 resume $NAME"
    ;;
  log)
    tail -F "$LOG"
    ;;
  *)
    echo "unknown action: $ACTION" >&2
    exit 2
    ;;
esac
