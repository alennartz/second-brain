#!/usr/bin/env python3
"""Reproduce Gemma's tool-call fan-out on the Jetson SGLang server — FIRST turn.

Single file, stdlib only, no database, no app imports. Sends exactly one request:
the recall system prompt + one user question + the two tool schemas. Nothing is
fed back from any tool, so it runs anywhere.

The bug: the assistant emits 7 tool calls in one turn (duplicates included,
invented pseudo-IDs included) against a system prompt that says "Make at most
1 or 2 tool calls per turn ... aim them at different parts." Deterministic under
greedy decoding (temperature=0) + fixed seed.

Usage:
    python repro_tool_fanout.py [trials] [base_url]

Defaults: trials=4, base_url=http://jetson.ordernet:8082/v1
Exit 0 means the bug reproduced in every trial.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

# --- pinned request -----------------------------------------------------------

BASE_URL = sys.argv[2] if len(sys.argv) > 2 else "http://jetson.ordernet:8082/v1"
TRIALS = int(sys.argv[1]) if len(sys.argv) > 1 else 4
MODEL = "gemma4-26b-a4b"
SEED = 0
TEMPERATURE = 0
MAX_TOKENS = 5000  # enough for the full first turn to emit; it stops at 7 calls

# Exact system prompt from second_brain.agents.recall.create_recall_agent.
SYSTEM = (
    "You are a personal knowledge recall agent. Explore the user's memory "
    "in two stages.\n\n"
    "First, call search_knowledge once or twice to locate relevant graph "
    "nodes and unprocessed intake evidence. These searches find entry points "
    "only.\n\n"
    "Then walk the graph. Call get_node on a promising node to read its "
    "connections, then follow those adjacent IDs with get_node to reach new "
    "nodes. Follow the links to nodes you do not already have in context, and "
    "skip the ones you do. This graph walk expands your view of the memory. "
    "Prefer it over more searches. Run another search only if the walk found "
    "nothing useful.\n\n"
    "Make at most 1 or 2 tool calls per turn, never more. If you make 2, aim "
    "them at different parts of the memory. Read the results of each turn "
    "before you choose what to touch next. Stop when you have enough "
    "evidence.\n\n"
    "End your run by replying with ONLY one JSON object, no other text:\n"
    '{"answer": string or null, "has_evidence": boolean, '
    '"cited_node_ids": [string], "cited_edge_ids": [string], '
    '"cited_unprocessed_ids": [string]}'
)

# Tool schemas exactly as the recall agent declares them.
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_knowledge",
            "description": "Search organized graph memory and unprocessed intake evidence.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "query": {"type": "string"},
                    "k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node",
            "description": "Fetch one graph node and its connections by record ID.",
            "parameters": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"record_id": {"type": "string"}},
                "required": ["record_id"],
            },
        },
    },
]

# First turn: system + user, nothing else. No tool results, so no DB is needed.
MESSAGES = [
    {"role": "system", "content": SYSTEM},
    {
        "role": "user",
        "content": "How did one Soviet engineer's death in 1966 contribute to America winning the Moon race?",
    },
]


def summarize(message: dict) -> list[tuple[str, str]]:
    out = []
    for t in message.get("tool_calls") or []:
        fn = t["function"]
        try:
            args = json.loads(fn["arguments"])
            arg = args.get("query") or args.get("record_id") or fn["arguments"]
        except (ValueError, KeyError, TypeError):
            arg = fn["arguments"]
        out.append((fn["name"], str(arg)))
    return out


def trial() -> tuple[str, list[tuple[str, str]]]:
    body = {
        "model": MODEL,
        "messages": MESSAGES,
        "tools": TOOLS,
        "temperature": TEMPERATURE,
        "seed": SEED,
        "max_completion_tokens": MAX_TOKENS,
        "parallel_tool_calls": False,
        "chat_template_kwargs": {"enable_thinking": True},
    }
    req = urllib.request.Request(
        f"{BASE_URL.rstrip('/')}/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read())
    choice = data["choices"][0]
    return choice["finish_reason"], summarize(choice["message"])


def main() -> int:
    print(f"target={BASE_URL} model={MODEL} temperature={TEMPERATURE} seed={SEED}")
    print("turn 1 only (system + user), no tool results, no database")
    print(
        "prompt: 'Make at most 1 or 2 tool calls per turn ... aim them at different parts.'"
    )
    print(f"running {TRIALS} identical trials\n")

    bug_trials = 0
    infra_miss = 0
    for i in range(TRIALS):
        try:
            finish, calls = trial()
        except (
            urllib.error.URLError,
            TimeoutError,
            KeyError,
            json.JSONDecodeError,
        ) as exc:
            infra_miss += 1
            print(f"  trial {i}: INFRA MISS ({type(exc).__name__}: {str(exc)[:60]})")
            continue
        args = [a for _, a in calls]
        dupes = {a for a in args if args.count(a) > 1}
        fanout = len(calls) > 2
        is_bug = fanout or bool(dupes)
        bug_trials += int(is_bug)
        flag = "BUG" if is_bug else "ok "
        print(
            f"  trial {i}: {flag} finish={finish} {len(calls)} calls (dups={len(calls) - len(set(args))})"
        )
        for name, arg in calls:
            mark = "  <-- duplicate" if arg in dupes else ""
            print(f"            {name}({arg}){mark}")

    answered = TRIALS - infra_miss
    rate = f"{bug_trials}/{answered}"
    print(
        f"\nbug in {rate} answered trials ({infra_miss} infra misses out of {TRIALS})"
    )
    if answered and bug_trials == answered:
        print("REPRODUCED 100% — identical request every trial (seed + greedy).")
    else:
        print("Did NOT reproduce in every trial.")
    return 0 if answered and bug_trials == answered else 1


if __name__ == "__main__":
    raise SystemExit(main())
