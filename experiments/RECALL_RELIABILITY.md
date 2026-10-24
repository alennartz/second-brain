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
TRIAL_ID=E008-1 EXPERIMENT_PORT=8102 \
BRAIN_REASONING_CHAT_TEMPLATE_KWARGS='{"enable_thinking":false}' \
.venv/bin/python -u /tmp/recall_campaign_runner.py
```

The runner writes each trial result and both logs under `/tmp/recall-reliability/`. It copies a fresh DB seed before each run. The launcher forwards `PYTHONPATH` to the API service so it imports this clean snapshot instead of the main editable install. Record the exact source hash, effective model settings, DB snapshot hash, API restart, and score for each trial. Port 8102 isolates the campaign from existing port-8101 progress polling. Runner SHA-256: `fe1eb2e2939264fd6984e93ea57cd313aafa338db04cad11a72ee3589c0d49f4`.

## Candidate Queue

| ID | Candidate | One change | Expected mechanism | Win threshold | Status |
|---|---|---|---|---|---|
| B00 | Repeat reference | No source change; replay all nine probes | Measures run-to-run variation | Completed three isolated repeats; failures ranged 0–4 and context 4–8 | Complete; high variance |
| E001 | Replace pseudo-schema with valid JSON examples | Replace only the final-output format block in the recall system prompt | Baseline produced eight no-JSON failures and two schema failures; the prompt currently shows type names rather than valid JSON values | Across three replays, reduce format-related 502s to ≤1 total, keep median context ≥7/9, preserve supported answers, and keep p95 <39.5s | Rejected |
| E002 | Stop after a denied search | Change only the `search_knowledge` budget/duplicate response instruction to require immediate final JSON | The model called search again after `search_skipped reason=budget`, then exceeded the eight-call limit | Across three replays, no tool-budget 502s; median context ≥7/9; no quality veto; p95 <39.5s | Rejected; ignored in E002-2 |
| E003 | Raise total tool-call cap | `RECALL_TOOL_CALL_LIMIT`: 8 → 9 | The model attempted call 9 and exceeded the current limit; one extra call can return a denial before the agent finishes | Across three replays, no tool-limit 502s; median context ≥7/9; no quality veto; p95 <39.5s | Rejected; overrun moved to call 10 |
| E004 | Normalize no-evidence output | For `has_evidence=false`, discard model answer text and citations instead of rejecting the whole output | One probe produced valid JSON that failed the no-evidence consistency validator | Remove that schema 502 without returning model claims or context; no other failure increase | Deferred; target not reproduced |
| E005 | Raise total tool-call cap to request limit | `RECALL_TOOL_CALL_LIMIT`: 8 → 12 | Cap 9 still failed on call 10; the existing request limit is 12 | Across three replays, no tool-limit 502s; median context ≥7/9; no quality veto; p95 <39.5s | Rejected; request limit bound first |
| E006 | Return cached node on duplicate read | Cache successfully fetched nodes and return the cached node on duplicate `get_node` calls | The model repeated `get_node` many times before hitting the request limit | Across three replays, no duplicate-driven usage-limit 502s; median context ≥7/9; no quality veto; p95 <39.5s | Rejected; duplicate cache did not stop loop |
| E007 | PydanticAI output retry for parser errors | Make `RecallOutputError` inherit `ModelRetry` | Installed PydanticAI turns parser `ModelRetry` into an output retry; the current custom exception bypasses that path | Across three replays, ≤1 format 502 total; median context ≥7/9; no added tool-budget failures versus paired reference; p95 <39.5s | Won; `c5a64e7` |
| E008 | Finalize after tool-budget exhaustion | On `UsageLimitExceeded`, make one no-tool finalizer call using a bounded evidence snapshot | The exception carries no run history; tool results remain available through `RecallDeps` | Across three replays, zero usage-limit 502s; context ≥8/9; cite only buffered IDs; preserve cross-domain isolation; p95 <39.5s | Ready; design recorded |
| E009 | Native structured output | Change final output mode | A prior live probe returned truncated JSON at a 2,048-token cap | Do not retry without a new SGLang/PydanticAI mechanism or a verified token-budget change | Deferred |
| E010 | Repetition penalty | Change one supported inference parameter | Could reduce repeated tool calls | Defer until SGLang support and effective request behavior are verified | Deferred |

## Trial Log

- **B00 launcher setup:** the first systemd start failed before Python ran because `/tmp/recall-reliability/runs/` did not exist (`status=209/STDOUT`). No API started and no database was copied or queried. Created the output directory.
- **B00 launcher setup:** the first Python start rejected a mistyped expected DB hash before copying the seed or starting the API. No model calls occurred. Corrected the hash and verified it against the frozen seed.
- **B00-1: complete.** Clean snapshot commit `890e465`; recall source SHA-256 `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`. Measured replay: `2026-10-23T22:48:46Z`–`2026-10-23T22:50:37Z`, 111.03s. Score: 9/9 HTTP 200, 8/9 with context, 0 exhausted probes, 21 nodes, 0 HTTP 5xx, 12 malformed edge IDs filtered. Probe time: total 105.57s, median 11.39s, p95 20.57s. DB hash was unchanged. Manual review found no unsupported Apollo–Renaissance claim. Compared with the initial reference (2 failed probes), the failure count varied by two, so run B00-2 before E001.
- **B00-1 metadata correction:** the initial artifact timestamp and commit came from failed preflight attempts, not the successful replay. Corrected the artifact using its monotonic replay duration. The measured start is `2026-10-23T22:48:46Z`; execution commit `890e465`; runner SHA-256 `980a34ffef41037e8fb399ca53b47858a53abe679c8845d9c20e3dc61d954319`.
- **B00-2: complete.** Clean snapshot commit `d7b2436`; source hash unchanged; DB hash unchanged. Score: 9/9 attempts, 6 HTTP 502 responses, 3/9 exhausted, 5/9 with context, 11 nodes. Probe time: total 111.20s, median 11.22s, p95 31.55s. Failures: probe 1 returned no JSON at `22:53:55.381Z` and `22:54:07.634Z`; probe 2 hit the 8-call limit at `22:54:09.625Z` and `22:54:30.756Z`; probe 7 returned no JSON at `22:55:16.379Z` and `22:55:27.760Z`. The failure count varied from 0 to 3 across the current references. Run B00-3 before E001.
- **B00-3: complete.** Source hash and DB hash unchanged. Score: 9 attempts, 8 HTTP 502 responses, 4/9 exhausted, 4/9 with context, 8 nodes. Probe time: total 119.78s, median 12.93s, p95 29.69s. Failures: probe 1 no JSON at `22:57:03.812Z` and `22:57:15.059Z`; probe 2 tool limit at `22:57:16.647Z` and `22:57:36.576Z`; probe 7 no JSON at `22:58:19.736Z` and `22:58:31.055Z`; probe 9 schema mismatch at `22:58:39.695Z` and `22:58:56.482Z`. The final mismatch was `has_evidence=false` with non-null answer text or citations. Across B00-1/2/3, errors were 0/3/4 and context was 8/5/4. The format failures totaled 10; tool-budget failures totaled 4.
- **E001 hypothesis:** replacing the pseudo-schema with valid JSON examples will reduce final-format failures because the current prompt describes JSON types instead of showing valid JSON values.
- **E001 prompt block to test:** `Return one complete JSON object and no other text. When no relevant evidence exists, return exactly {"answer":null,"has_evidence":false,"cited_node_ids":[],"cited_edge_ids":[],"cited_unprocessed_ids":[]}. With evidence, use a JSON string for answer, set has_evidence to true, and copy exact IDs from tool results into the matching citation arrays.`
- **E001-1: complete.** Candidate source hash `658041f4598f2360e09e26e725740dd95c6b78e0916e7d717efaa8f5d6e4b6b2`; DB hash unchanged. Results: 9 probes, 7 HTTP 502 attempts, 3/9 exhausted, 6/9 with context, 19 nodes. Probe time: total 166.20s, median 13.91s, p95 33.42s. The API logged five no-JSON failures and two tool-limit failures; one no-JSON failure recovered on retry. There were no schema-validation failures. UTC failure attempts: no JSON at `23:03:08.423Z` (recovered), `23:03:54.527Z`, `23:04:06.481Z`, `23:05:28.128Z`, and `23:05:40.253Z`; tool limit at `23:04:55.267Z` and `23:05:16.535Z`. This single replay does not meet the threshold. Run E001-2 with the same prompt.
- **E001-2: complete.** Candidate source hash unchanged; DB hash unchanged. Results: 6 HTTP 502 attempts, 3/9 exhausted, 5/9 with context, 18 nodes. Probe time: total 136.25s, median 13.80s, p95 31.30s. Failures: probe 4 no JSON at `23:07:07.451Z` and `23:07:18.824Z`; probe 8 tool limit at `23:08:01.169Z` and `23:08:21.442Z`; probe 9 no JSON at `23:08:32.466Z` and `23:08:43.698Z`.
- **E001-1/2: rejected.** The valid-example prompt produced 5 and 4 no-JSON 502s, plus 2 tool-limit 502s in each replay. Both runs had 3 exhausted probes. Context was 6/9 then 5/9. Combined, these runs had 13 HTTP 502 attempts over 18 probes, worse than the baseline rate of 14 over 27. The predeclared threshold of at most one format-related 502 across three runs was already impossible. The prompt also did not fix the tool-call loop.
- **E002 hypothesis:** replacing the search-denial reply with an explicit stop-and-finalize instruction will reduce tool-limit failures because the model keeps searching after the application denies budgeted searches.
- **E002 replacement text:** `Search budget is exhausted. Stop using tools now and return the final JSON from evidence already collected.`
- **E001 rollback:** restored `recall.py` to baseline SHA-256 `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`. The API stopped, the port-8102 owner lock is clear, and the frozen DB seed is unchanged. E001's log-only result commit is `7cb5930`.
- **E002 hypothesis:** replacing the search-denial reply with an explicit stop-and-finalize instruction will reduce tool-limit failures because the model keeps searching after the application denies budgeted searches.
- **E002 replacement text:** `Search budget is exhausted. Stop using tools now and return the final JSON from evidence already collected.`
- **E002-1: complete.** Candidate source hash `3f99582b9d874a8d6452b45af819820efa32f143e5f827a1402b7e1f343b02e3`; DB hash unchanged. Results: 9 probes, 3 HTTP 502 attempts, 1/9 exhausted, 8/9 with context, 24 nodes. Probe time: total 134.16s, median 14.75s, p95 28.69s. No search-budget skips or tool-limit errors occurred. Probe 1 returned no JSON at `23:11:32.342Z` and `23:11:44.877Z`. Probe 9 had one schema failure at `23:13:17.822Z`, then succeeded on retry. Manual review found no direct Apollo–Renaissance claim; cited context supported the substantive answers.
- **E002-2: complete.** Candidate hash and DB hash unchanged. Results: 6 HTTP 502 attempts, 3/9 exhausted, 6/9 with context, 15 nodes. Probe time: total 135.85s, median 12.99s, p95 33.28s. The model ignored the stop instruction and issued three skipped searches at local `19:15:08–19:15:10`; it also repeated `get_node` at `19:15:39` and `19:16:01`. UTC failures: probe 1 no JSON at `23:14:22.442Z` and `23:14:34.369Z`; probes 5 and 6 exceeded the tool limit at `23:15:02.692Z`, `23:15:21.298Z`, `23:15:29.758Z`, and `23:15:50.911Z`.
- **E002: rejected.** E002-1 had no tool-limit failures, but E002-2 had four. Combined, E002 had 9 HTTP 502 attempts and 4 exhausted probes across 18 probes. The candidate did not meet its three-run threshold and did not stop the denied search loop.
- **E003 hypothesis:** raising the global cap from 8 to 9 will permit the observed ninth call to return its tool result and let the agent finalize. The search and node budgets remain unchanged.
- **E002 rollback:** restored `recall.py` to baseline SHA-256 `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`. The API stopped, the port-8102 owner lock is clear, and the frozen DB seed is unchanged.
- **E003-1: complete.** Candidate source hash `99926a34df2feca8d647644a758aebb1b8549b327fe611adb82d4588dfe5b0a8`; DB hash unchanged. Results: 4 HTTP 502 attempts, 2/9 exhausted, 7/9 with context, 18 nodes. Probe time: total 118.15s, median 10.04s, p95 33.54s. Probe 1 returned no JSON at `23:20:21.592Z` and `23:20:33.476Z`; probe 6 exceeded the raised 9-call limit at `23:21:10.606Z` and `23:21:32.292Z`. Four duplicate node reads were skipped; the model still attempted call 10.
- **E003: rejected.** Raising the cap moved the failure from call 9 to call 10. The predeclared no-tool-limit threshold was already impossible after E003-1. Do not test cap 10 without a new mechanism.
- **E003 rollback:** restored `RECALL_TOOL_CALL_LIMIT=8`; `recall.py` hash is back to baseline `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`. The API stopped and the owner lock is clear.
- **E004 hypothesis:** normalizing `has_evidence=false` output to a null answer and empty citations will turn the observed schema 502 into a safe no-evidence response. The app will discard model claims and return no context.
- **E004-1: complete.** Candidate source hash `edf6bc26b4f36fc01daeec547bfe304a424884cec16b586ad634c395984c28a7`; DB hash unchanged. Results: 4 HTTP 502 attempts, 2/9 exhausted, 7/9 with context, 17 nodes. Probe time: total 115.78s, median 10.48s, p95 31.25s. No no-evidence schema mismatch occurred. Probe 1 returned no JSON at `23:26:02.141Z` and `23:26:13.925Z`; probe 6 hit the 8-call limit at `23:26:50.607Z` and `23:27:10.858Z`. Manual review found no direct Apollo–Renaissance claim.
- **E004-2: complete.** Candidate source hash and DB hash unchanged. Results: 4 HTTP 502 attempts, 2/9 exhausted, 7/9 with context, 17 nodes. Probe time: total 114.58s, median 9.67s, p95 31.04s. There were no schema failures. Probe 1 returned no JSON at `23:28:47.311Z` and `23:28:58.725Z`; probe 6 exceeded the tool-call limit at `23:29:35.542Z` and `23:29:55.986Z`. The no-evidence answer passed manual review.
- **E004-3: complete.** Candidate source hash and DB hash unchanged. Results: 4 HTTP 502 attempts, 2/9 exhausted, 7/9 with context, 17 nodes. Probe time: total 115.31s, median 9.51s, p95 31.11s. Probe 1 returned no JSON at `23:31:31.061Z` and `23:31:43.276Z`; probe 6 hit the 8-call limit at `23:32:20.054Z` and `23:32:40.614Z`.
- **E004: deferred, not a measured win.** Across three replays, no schema 502 occurred, but the normalization path was not exercised. The cross-domain probe returned three context nodes and a supported no-connection answer each time. The direct model-validation probe confirmed normalization, but that does not establish benchmark impact. Revert E004.
- **E004 rollback:** restored the baseline validator; `recall.py` hash is `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`. The API stopped, the owner lock is clear, and the frozen DB seed is unchanged.
- **E005 hypothesis:** the cap of 9 failed on call 10; setting it to the existing request limit of 12 could allow the agent to receive enough tool results and finalize. Keep per-tool search and node budgets unchanged.
- **E005-1: complete.** Candidate source hash `34f0fd1d05599ca02e0d1a97d9c6ff21c86e644687d6302e7354055762dae1b1`; DB hash unchanged. Results: 4 HTTP 502 attempts, 2/9 exhausted, 7/9 with context, 17 nodes. Probe time: total 121.76s, median 9.72s, p95 38.20s. Probe 1 returned no JSON at `23:39:19.611Z` and `23:39:31.187Z`; probe 6 hit `request_limit=12` at `23:40:08.162Z` and `23:40:32.008Z`. The model made 10 duplicate-node reads. The higher tool cap removed the tool-call-limit error but moved the failure to the request limit.
- **E005: rejected.** The trial still failed two probes and did not improve reliability. Do not raise the cap again without a new mechanism.
- **E005 rollback:** restored `RECALL_TOOL_CALL_LIMIT=8`; `recall.py` hash is back to baseline `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`. The API stopped, the owner lock is clear, and the frozen DB seed is unchanged.
- **E006 hypothesis:** caching an enriched node and returning it on duplicate `get_node` calls will replace repeated denial results with the evidence already collected and may stop the loop.
- **E006 change:** add one node cache to `RecallDeps`; populate it after the first successful read; return the cached node on duplicate reads. Keep call and node budgets unchanged.
- **E006-1: complete.** Candidate source hash `585efb4585d144b3012fb53209a53dd3c9fdb5c0f6bfadb0b26a62ab17966158`; DB hash unchanged. Results: 4 HTTP 502 attempts, 2/9 exhausted, 7/9 with context, 17 nodes. Probe time: total 116.54s, median 9.72s, p95 30.27s. The cache returned two duplicate nodes, but the agent still hit the tool-call limit. Probe 1 no JSON at `23:48:12.262Z` and `23:48:25.047Z`; probe 6 hit the 8-call limit at `23:49:02.321Z` and `23:49:22.600Z`.
- **E006: rejected.** Cached results did not stop duplicate tool calls. Do not repeat this candidate without a new mechanism.
- **E006 rollback:** restored `recall.py` to baseline SHA-256 `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`. The API stopped and the owner lock is clear.
- **E007 mechanism research:** installed PydanticAI's `execute_output_function()` converts `ModelRetry` from a `TextOutput` parser into `ToolRetryError`. `_agent_graph` consumes one output retry and sends a correction prompt. The default output retry budget is one. `RecallOutputError` is not `ModelRetry`, so the current parser error bypasses this path and becomes HTTP 502.
- **E007 hypothesis:** making `RecallOutputError` inherit `ModelRetry` will trigger the built-in output retry with the same conversation and evidence.
- **E007-1: complete.** Candidate source hash `d3060a74ebb3679afd6f64106260f66e090210bbc4d21025394ca2329c133ab3`; DB hash unchanged. Results: 2 HTTP 502 attempts, 1/9 exhausted, 8/9 with context, 18 nodes. Probe time: total 108.90s, median 9.60s, p95 31.54s. The first probe emitted no JSON at `23:58:23Z`; PydanticAI retried at `23:58:24Z`, then fetched a node and completed with HTTP 200. Probe 6 still hit the tool limit at `23:59:04.568Z` and `23:59:25.290Z`. No format-related 502s occurred.
- **E007-2: complete.** Candidate source hash unchanged; DB hash unchanged. Results: 2 HTTP 502 attempts, 1/9 exhausted, 8/9 with context, 18 nodes. Probe time: total 109.73s, median 9.65s, p95 31.56s. PydanticAI retried the malformed no-JSON response and the probe completed; no format-related 502 occurred. Probe 6 still exceeded the 8-call limit at `00:02:33.344Z` and `00:02:54.161Z`.
- **E007-3: complete.** Candidate source hash unchanged; DB hash unchanged. Results: 2 HTTP 502 attempts, 1/9 exhausted, 8/9 with context, 18 nodes. Probe time: total 109.63s, median 9.69s, p95 31.64s. One no-JSON response at `00:06:55Z` triggered the PydanticAI retry and recovered. Probe 6 still exceeded the 8-call limit at `00:07:36.142Z` and `00:07:56.504Z`.
- **E007 aggregate:** all four candidate runs had 8/9 context, one exhausted probe, and no format-related 502. The first three runs had more tool-limit errors than the initial baseline sample. Two paired rechecks showed the same tool-limit failures on both sides; each candidate recovered the separate no-JSON probe. Accept E007 based on the paired checks.

- **B00-4: complete.** Reference source hash `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`; DB hash unchanged. Results: 4 HTTP 502 attempts, 2/9 exhausted, 7/9 with context, 17 nodes. Probe time: total 116.60s, median 9.82s, p95 32.01s. Probe 1 no JSON at `00:11:52.701Z` and `00:12:04.361Z`; probe 6 hit the 8-call limit at `00:12:42.435Z` and `00:13:02.987Z`.
- **E007-3 vs B00-4:** the candidate recovered probe 1 with one PydanticAI output retry; the reference exhausted both attempts. Probe 6 hit the same tool-call limit in both runs. Context improved from 7/9 to 8/9; HTTP 502 attempts fell from 4 to 2.
- **B00-5: complete.** Reference source hash `22bac9af8293ff1941acf7126cc2b7a372e23f608361d985228e38f57cd463b0`; DB hash unchanged. Results: 4 HTTP 502 attempts, 2/9 exhausted, 7/9 with context, 17 nodes. Probe time: total 115.53s, median 9.55s, p95 32.08s. Probe 1 no JSON at `00:15:43.292Z` and `00:15:54.808Z`; probe 6 hit the 8-call limit at `00:16:32.072Z` and `00:16:52.773Z`.
- **E007-4: complete.** Candidate source hash unchanged; DB hash unchanged. Results: 2 HTTP 502 attempts, 1/9 exhausted, 8/9 with context, 18 nodes. Probe time: total 110.37s, median 9.62s, p95 31.22s. The parser retry recovered probe 1; probe 6 hit the same tool-call limit as B00-5 at `00:21:13.540Z` and `00:21:33.881Z`.
- **E007-4 vs B00-5:** the candidate recovered probe 1 with one PydanticAI output retry; the reference exhausted both attempts. Probe 6 hit the same tool-call limit in both runs. Context improved from 7/9 to 8/9; HTTP 502 attempts fell from 4 to 2.
- **E007 win:** both paired runs recovered one probe with the built-in output retry, raised context by one, and kept tool-budget failures equal to the paired reference. Across four candidate replays, no format-related 502 occurred. Commit: `c5a64e7` (`fix(recall): E007 retry invalid output (2 paired rescues)`). Committed recall.py SHA-256: `a33211427e1f8a4f6a00ff76ca9ae1a76c0fef4852694486c8d3357a43594b03`. Rollback: revert `c5a64e7`, or restore `RecallOutputError(RuntimeError)` and remove the `ModelRetry` import.
- **Active reference after E007:** 8/9 HTTP 200, 8/9 with context, 18 nodes, one exhausted probe, two tool-limit 502 attempts, and p95 31.56s. Use this reference for E008.
- **E008 mechanism research:** PydanticAI's `UsageLimitExceeded` stores only an error message, not the failed run's message history. `search_memory()` returns bounded graph nodes and unprocessed chunks; `get_node()` returns an enriched node. `RecallDeps` persists across those tool calls, so it can buffer the evidence for recovery.
- **E008 mechanism:** `UsageLimitExceeded` carries only an error message. `RecallDeps` can preserve results returned by tools. The current budgets bound the snapshot to at most 16 unique graph nodes (two searches × five results plus six reads) and 10 unprocessed chunks (two searches × five results).
- **E008 hypothesis:** after a usage-limit error, one no-tool finalizer can answer from the bounded evidence snapshot and avoid another exploration loop.
- **E008 implementation plan:** store graph nodes and unprocessed chunks in `RecallDeps` as tools return them. When exploration raises `UsageLimitExceeded`, fail closed if the buffer is empty. Otherwise, call a finalizer with the original question and serialized evidence. Register no tools on the finalizer. Permit citations only for buffered IDs. Return `RecallOutput` through the existing parser. Keep API-side citation resolution and all database writes unchanged.
- **E008 success criteria:** zero usage-limit 502s across three replays, median context ≥8/9, no unsupported cross-domain claim, and p95 <39.5s.
- **E008-1: ready.** Implement this single recovery path in `src/second_brain/agents/recall.py`, then run the nine probes against the frozen DB.
