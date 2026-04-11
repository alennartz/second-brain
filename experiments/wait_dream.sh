#!/usr/bin/env bash
# Trigger a dream cycle and poll for completion with exponential backoff.
# Usage: ./experiments/wait_dream.sh [base_url]
set -euo pipefail

BASE="${1:-http://localhost:8000}"

resp=$(curl -sf -X POST "$BASE/dream")
job_id=$(echo "$resp" | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
echo "Dream job: $job_id"

delay=2
max_delay=30
while true; do
    status=$(curl -sf "$BASE/dream/jobs/$job_id" | python3 -c "import json,sys; print(json.load(sys.stdin)['status'])")
    case "$status" in
        complete) echo "Done."; exit 0 ;;
        failed)   echo "FAILED."; exit 1 ;;
        *)        printf "."; sleep "$delay" ;;
    esac
    delay=$(( delay * 2 > max_delay ? max_delay : delay * 2 ))
done
