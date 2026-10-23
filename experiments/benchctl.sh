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
# Pi's CLI uses /usr/bin/env node, so preserve the caller's runtime PATH in services.
for key in PATH BRAIN_TEST_MODE BRAIN_REASONING_MODEL BRAIN_EMBEDDING_MODEL \
  BRAIN_REASONING_BASE_URL BRAIN_EMBEDDING_BASE_URL \
  BRAIN_REASONING_TEMPERATURE BRAIN_REASONING_CHAT_TEMPLATE_KWARGS \
  BRAIN_REASONING_EFFORT BENCH_OP_TIMEOUT \
  BENCH_PIPELINE_POLL PI_CODING_AGENT_DIR PI_JUDGE_TIMEOUT_SECONDS; do
  if [[ -v $key ]]; then
    ENV_ARGS+=(--setenv "$key=${!key}")
  fi
done
PI_CLI="${PI_CLI_PATH:-$(command -v pi || true)}"
if [[ -n "$PI_CLI" ]]; then
  ENV_ARGS+=(--setenv "PI_CLI_PATH=$PI_CLI")
fi

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
pipeline = d.get("pipeline") or {}
queue = pipeline.get("last_snapshot")
pending = sum(int(queue.get(k, 0) or 0) for k in ("ready", "leased", "retry_wait", "paused")) if queue is not None else "unknown"
staged = sum(1 for r in d["ingest"] if r.get("status") in ("staged", "complete"))
active = f" | current={cur.get('label')} elapsed={time.time()-cur['started_epoch']:.0f}s" if cur.get("started_epoch") else ""
print(f"state: phase={d['phase']} staged={staged}/30 queue_pending={pending} recall={len(d['recall'])}/9 graph={len(d['graph'])}/20{active}")
errors = pipeline.get("recent_errors") or []
if errors:
    print(f"pipeline recent errors: {len(errors)}; latest: {errors[-1].get('error')}")
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
