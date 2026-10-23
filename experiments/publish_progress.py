#!/usr/bin/env python3
"""Publish a privacy-safe static benchmark snapshot on a fixed interval."""

from __future__ import annotations

import argparse
import json
import shutil
import time
from collections import deque
from datetime import UTC, datetime
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
PENDING_FIELDS = ("ready", "leased", "retry_wait", "paused")


def read_json(path: Path) -> dict:
    with path.open() as stream:
        return json.load(stream)


def tail_lines(path: Path, limit: int) -> list[str]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8", errors="replace") as stream:
        return [line.rstrip() for line in deque(stream, maxlen=limit)]


def relevant_runner_lines(path: Path, limit: int = 24) -> list[str]:
    if not path.exists():
        return []
    useful: deque[str] = deque(maxlen=limit)
    previous = None
    with path.open(encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.rstrip()
            if line.startswith("  pipeline drain:") or line.startswith(
                "  latest pipeline error:"
            ):
                continue
            if line and line != previous:
                useful.append(line)
            previous = line
    return list(useful)


def relevant_server_lines(path: Path, limit: int = 40) -> list[str]:
    markers = (
        "second_brain.app",
        "second_brain.agents.ingest",
        "second_brain.tools.ingest_tools",
        "HTTP Request: POST http://jetson.ordernet:8082/v1/chat/completions",
        "HTTP Request: POST http://jetson.ordernet:8084/v1/embeddings",
        "Embedding batch complete",
        "ERROR",
        "WARNING",
    )
    if not path.exists():
        return []
    useful: deque[str] = deque(maxlen=limit)
    with path.open(encoding="utf-8", errors="replace") as stream:
        for raw_line in stream:
            line = raw_line.rstrip()
            if (
                any(marker in line for marker in markers)
                and "Embedding request (" not in line
                and "search_knowledge tables=" not in line
            ):
                useful.append(line)
    return list(useful)


def fetch_pipeline(port: int) -> tuple[dict | None, bool]:
    try:
        with urlopen(f"http://127.0.0.1:{port}/ingest/pipeline", timeout=5) as response:
            return json.load(response), True
    except (OSError, URLError, TimeoutError, json.JSONDecodeError):
        return None, False


def build_snapshot(run_name: str, port: int) -> tuple[Path, dict]:
    run_dir = ROOT / "experiments" / "data" / run_name
    state = read_json(run_dir / "state.json")
    progress_dir = run_dir / "progress"
    progress_dir.mkdir(parents=True, exist_ok=True)

    live_pipeline, api_reachable = fetch_pipeline(port)
    saved_pipeline = state.get("pipeline") or {}
    queue = live_pipeline or saved_pipeline.get("last_snapshot") or {}
    counts = {field: int(queue.get(field, 0) or 0) for field in PENDING_FIELDS}
    pending = sum(counts.values()) if queue else None
    staged_rows = [
        row
        for row in state.get("ingest", [])
        if row.get("status") in {"staged", "complete"}
    ]
    chunks_total = sum(int(row.get("chunks_stored", 0) or 0) for row in staged_rows)
    current = state.get("current") or {}
    current_data = None
    if current:
        current_data = {"label": current.get("label")}
        if current.get("started_epoch"):
            current_data["elapsed_s"] = round(time.time() - current["started_epoch"])

    snapshot = {
        "run": run_name,
        "phase": state.get("phase", "unknown"),
        "phase_label": str(state.get("phase", "unknown")).replace("_", " ").title(),
        "checked_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "api_reachable": api_reachable,
        "staging": {
            "snippets_staged": len(staged_rows),
            "snippets_total": int(state.get("snippet_count", 30)),
            "chunks_total": chunks_total,
            "failed": sum(
                1 for row in state.get("ingest", []) if row.get("status") == "failed"
            ),
        },
        "pipeline": {
            **counts,
            "pending_chunks": pending,
            "processed_estimate": max(0, chunks_total - pending)
            if pending is not None
            else 0,
            "worker_count": int(queue.get("worker_count", 0) or 0),
            "active_leases": int(queue.get("active_leases", 0) or 0),
        },
        "current": current_data,
        "logs": {
            "server": relevant_server_lines(run_dir / "server.log"),
            "runner": relevant_runner_lines(
                ROOT / "experiments" / "data" / f"{run_name}-run.log"
            ),
        },
    }
    latency_path = run_dir / "latency.json"
    if latency_path.exists():
        snapshot["latency"] = read_json(latency_path)

    template = ROOT / "experiments" / "progress" / "index.html"
    shutil.copyfile(template, progress_dir / "index.html")
    target = progress_dir / "progress.json"
    temporary = target.with_suffix(".json.tmp")
    with temporary.open("w") as stream:
        json.dump(snapshot, stream, indent=2)
    temporary.replace(target)
    return target, snapshot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_name")
    parser.add_argument("--port", type=int, default=8101)
    parser.add_argument("--interval", type=float, default=10)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()

    while True:
        path, snapshot = build_snapshot(args.run_name, args.port)
        queue = snapshot["pipeline"]
        print(
            f"{snapshot['checked_at']} phase={snapshot['phase']} "
            f"staged={snapshot['staging']['snippets_staged']}/"
            f"{snapshot['staging']['snippets_total']} pending={queue['pending_chunks']} "
            f"api={snapshot['api_reachable']} file={path}",
            flush=True,
        )
        if args.once or snapshot["phase"] == "done":
            return
        time.sleep(max(5, args.interval))


if __name__ == "__main__":
    main()
