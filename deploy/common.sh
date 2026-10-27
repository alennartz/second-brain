#!/usr/bin/env bash

# Shared configuration and readiness helpers for the local Bun deployment.
# This file is sourced by deployment commands and has no standalone behavior.

dotenv_value() {
  local file=$1
  local key=$2
  local line value

  while IFS= read -r line || [[ -n "$line" ]]; do
    line=${line%$'\r'}
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ "$line" =~ ^[[:space:]]*$ ]] && continue
    if [[ "$line" =~ ^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=[[:space:]]*(.*)$ ]]; then
      value=${BASH_REMATCH[2]}
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
  done < "$file"

  return 1
}

validate_application_environment() {
  local file=$1
  local key value

  for key in BRAIN_INGEST_MODEL BRAIN_RECALL_MODEL BRAIN_DREAM_MODEL; do
    value="$(dotenv_value "$file" "$key" || true)"
    if [[ -z "$value" ]]; then
      printf 'error: %s is required in %s\n' "$key" "$file" >&2
      return 1
    fi
  done
}

wait_for_service_health() {
  local service_name=$1
  local port=$2
  local attempts=${3:-60}
  local url="http://127.0.0.1:${port}/health"
  local attempt

  if ! command -v curl >/dev/null 2>&1; then
    printf 'error: curl is required to verify service health\n' >&2
    return 1
  fi

  for ((attempt = 1; attempt <= attempts; attempt++)); do
    if curl --fail --silent --show-error --max-time 2 "$url" >/dev/null; then
      return 0
    fi
    sleep 1
  done

  printf 'error: %s did not become healthy at %s\n' "$service_name" "$url" >&2
  if command -v systemctl >/dev/null 2>&1; then
    systemctl --user status "$service_name" --no-pager >&2 || true
  fi
  if command -v journalctl >/dev/null 2>&1; then
    journalctl --user -u "$service_name" -n 40 --no-pager >&2 || true
  fi
  return 1
}
