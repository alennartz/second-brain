#!/bin/bash
# Usage: ./experiments/cycle.sh <experiment_name> [notes]
set -e

EXPERIMENT_NAME="${1:?Usage: cycle.sh <experiment_name> [notes]}"
NOTES="${2:-}"

cd "$(dirname "$0")/.."

echo "=== Stopping server ==="
kill $(lsof -ti:8000) 2>/dev/null || true
sleep 2

echo "=== Wiping DB ==="
rm -rf data/brain.db

echo "=== Starting server ==="
~/.local/bin/uv run uvicorn second_brain.app:app --host 0.0.0.0 --port 8000 > /dev/null 2>&1 &
SERVER_PID=$!
sleep 4

# Verify server is up
if ! curl -s http://localhost:8000/health > /dev/null 2>&1; then
    echo "ERROR: Server failed to start"
    exit 1
fi

echo "=== Running experiment: $EXPERIMENT_NAME ==="
~/.local/bin/uv run python experiments/run_experiment.py "$EXPERIMENT_NAME" "$NOTES"

echo "=== Done ==="
