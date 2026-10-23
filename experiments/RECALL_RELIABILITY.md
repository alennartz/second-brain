# Recall Reliability Campaign

## Goal

Improve reliability of tool-driven recall on the persisted Run 15 graph. The primary target is 9/9 HTTP 200 responses across the fixed recall probe set. Keep context coverage at or above 7/9 and preserve citation grounding.

## Metrics

- **Primary:** completed probes with HTTP 200, out of 9.
- **Coverage:** probes with at least one context node, out of 9.
- **Failures:** exhausted probes and HTTP 5xx responses, reported separately.
- **Context size:** total resolved nodes returned.
- **Latency:** per-probe elapsed time, median, p95, and total replay time.
- **Citation behavior:** malformed citations filtered, citations resolved, and unresolved-citation errors.
- **Quality veto:** reject a candidate if it removes context from a previously successful relevant probe, returns evidence without resolved citations, or claims a direct Apollo–Renaissance connection.

A candidate wins when it reduces failed probes by at least one, keeps context coverage at or above 7/9, passes the quality veto, and keeps p95 latency below 39.5 seconds. The goal is 9/9 HTTP 200 responses. Repeat a baseline/candidate pair when the result changes by only one probe or baseline repeats vary by more than one probe.

## Reference Configuration

- Model: `openai:gemma4-26b-a4b` at `jetson.ordernet`
- Embedding model: `openai:harrier-oss-v1-0.6b`
- `enable_thinking=false`, temperature `0.0`
- Database: `data/brain-experiment.db`, from completed run `15-ingest-name-refs-gemma4-thinking-off`
- Input: the nine fixed `RECALL_QUESTIONS` in `experiments/run_experiment.py`
- Each probe gets at most two HTTP attempts, with a 10-second wait after the first failure.
- No ingestion or graph probes run during a recall trial. Require zero ready, leased, retry-wait, paused, and active-lease counts before each replay.

No random seed is exposed by this SGLang setup. Keep question order fixed, keep temperature at zero, restart the API between replays, keep the Jetson model service loaded, and run no other model workload. The replay harness saves a result after each probe. API startup, model, database, and effective prompt settings go in each result file.

## Initial Reference Measurement

This measurement used the current working-tree recall code after removing table-prefix checks from `RecallOutput`. It is the reference for this campaign, not the earlier strict-validator result.

- Run: `experiments/data/15-ingest-name-refs-gemma4-thinking-off/recall-latest.json`
- Started: `2026-10-23T00:13:16Z`; finished: `2026-10-23T00:15:33Z`
- Results: **7/9 HTTP 200**, **7/9 with context**, **2/9 exhausted**, **21 resolved nodes**
- HTTP 502 responses: **4** across two failed probes and their retries
- Malformed edge IDs: **12** filtered without failing successful answers
- Probe time total: **127.10s**; median: **13.07s**; p95/max: **31.58s**
- Remaining failures: probe 1 returned no JSON object twice; probe 6 exceeded the 8-call limit twice at 9 attempted calls.
- Historical run 15 with strict table-prefix validation scored 2/9 with context and is not the campaign baseline.
- Recall source SHA-256: `623ba4f07a05ac8f1c1b4f7d1449ea4bac22f81ec2aade4ec5c9c0b4ca6dfe54`
- Repository `HEAD`: `35f101839d1d74ac7cf2ca1a65adb8d598ca144b`; the main working tree had 25 changed paths.

## Clean Campaign Snapshot

- Branch: `exp/recall-reliability-2026-10-22`
- Baseline snapshot commit: `b56c223`
- Isolated API source-path harness commit: `0688e5b`
- Verified API imports `second_brain` and `experiments.run_experiment` from this worktree; effective model settings match the reference.
- Snapshot recall source SHA-256: `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`
- Run 15 database seed SHA-256: `d50a9e507119d6750ee7cb4c15fa20315db9cb79f9be40872e66d64f7a6b50eb`
- The snapshot worktree is clean. Snapshot preparation applied repository formatting and fixed existing lint/type errors required by commit hooks. Those preparation changes are outside the candidate queue. The main worktree remains untouched.

## Isolation and Commands

The main working tree contains pre-existing changes. Do not clean, stash, or commit them. Run trials in a clean campaign worktree made from an exact snapshot of the current source. Keep its database as a fresh copy of the Run 15 database for each trial. This preserves the source graph and prevents cross-trial database state.

Use the same replay harness and command for every baseline and candidate run:

```bash
cd /tmp/second-brain-recall-campaign
PYTHONPATH=/tmp/second-brain-recall-campaign:/tmp/second-brain-recall-campaign/src \
TRIAL_ID=B00-1 EXPERIMENT_PORT=8102 \
BRAIN_REASONING_CHAT_TEMPLATE_KWARGS='{"enable_thinking":false}' \
.venv/bin/python -u /tmp/recall_campaign_runner.py
```

The runner writes each trial result and both logs under `/tmp/recall-reliability/`. It copies a fresh DB seed before each run. The launcher forwards `PYTHONPATH` to the API service so it imports this clean snapshot instead of the main editable install. Record the exact source hash, effective model settings, DB snapshot hash, API restart, and score for each trial. Port 8102 isolates the campaign from existing port-8101 progress polling. Runner SHA-256: `980a34ffef41037e8fb399ca53b47858a53abe679c8845d9c20e3dc61d954319`.

## Candidate Queue

| ID | Candidate | One change | Expected mechanism | Win threshold | Status |
|---|---|---|---|---|---|
| B00 | Repeat reference | No source change; replay all nine probes once | Measures run-to-run variation before interpreting a one-probe gain | Establish repeat range; if failures vary by more than one, repeat reference before E001 | Repeat required (B00-2) |
| E001 | Raise total tool-call cap | `RECALL_TOOL_CALL_LIMIT`: 8 → 9 | One failed probe attempted a ninth call; permitting that call can let the agent finish | At least 8/9 HTTP 200 and context coverage ≥7/9; no new failure or quality veto; p95 <39.5s | Queued after B00 |
| E002 | Stop on duplicate/skipped tool result | Add one system-prompt instruction to finalize immediately after a duplicate/skipped tool result | The failed budget probe repeated a node read before attempting another tool | Reduce tool-budget failures by ≥1 with no loss of context coverage or other successful probes | Queued; test only if E001 leaves this failure mode |
| E003 | Make final JSON requirement explicit on every path | Replace the final-output prompt sentence with a shorter rule that requires complete JSON even when evidence is absent | One probe returned a 17-character non-JSON response after search | Reduce no-JSON failures by ≥1; retain context coverage and citation grounding | Queued if no-JSON failure remains |
| E004 | Application-level output repair | One bounded retry after malformed final text | Current `TextOutput` parser failure becomes HTTP 502 without a PydanticAI output retry | Defer until prompt-only trials finish; requires a separate design for reusing evidence safely | Deferred |
| E005 | Native structured output | Change final output mode | A prior live probe returned truncated JSON at a 2,048-token cap | Do not retry without a new SGLang/PydanticAI mechanism or a verified token-budget change | Deferred |
| E006 | Repetition penalty | Change one supported inference parameter | Could reduce repeated tool calls | Defer until SGLang support and effective request behavior are verified | Deferred |

## Trial Log

- **B00 launcher setup:** the first systemd start failed before Python ran because `/tmp/recall-reliability/runs/` did not exist (`status=209/STDOUT`). No API started and no database was copied or queried. Created the output directory.
- **B00 launcher setup:** the first Python start rejected a mistyped expected DB hash before copying the seed or starting the API. No model calls occurred. Corrected the hash and verified it against the frozen seed.
- **B00-1: complete.** Clean snapshot commit `890e465`; recall source SHA-256 `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`. Measured replay: `2026-10-23T22:48:46Z`–`2026-10-23T22:50:37Z`, 111.03s. Score: 9/9 HTTP 200, 8/9 with context, 0 exhausted probes, 21 nodes, 0 HTTP 5xx, 12 malformed edge IDs filtered. Probe time: total 105.57s, median 11.39s, p95 20.57s. DB hash was unchanged. Manual review found no unsupported Apollo–Renaissance claim. Compared with the initial reference (2 failed probes), the failure count varied by two, so run B00-2 before E001.
- **B00-2: running.** Repeat the reference from the frozen DB seed. Results will be stored in `/tmp/recall-reliability/runs/B00-2.json`.
