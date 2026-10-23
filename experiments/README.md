# Benchmark runs

Run benchmarks as supervised systemd user services. The runner saves state after
each operation, resumes unfinished work, and restarts after an unexpected exit.
It uses `data/brain-experiment.db`; it never touches the deployed `data/brain.db`.
The scratch API disables dream scheduling to isolate ingestion. It synchronously
stages every input first, then waits for the full ingestion queue to drain before
it starts recall or graph probes.

## Start and monitor

```bash
make bench-start NAME=06-baseline-gemma4 NOTES="current Jetson stack"
make bench-status NAME=06-baseline-gemma4
make bench-log NAME=06-baseline-gemma4
```

Set `EXPERIMENT_PORT` to override the default scratch port `8101`. Set
`BENCH_OP_TIMEOUT` to change the synchronous staging deadline (default `900` seconds).
Set `BENCH_PIPELINE_POLL` to change the queue-status poll interval (default `5` seconds).

## Interrupt and resume

```bash
make bench-stop NAME=06-baseline-gemma4
make bench-resume NAME=06-baseline-gemma4
```

`bench-stop` sends SIGTERM. The runner saves state and exits cleanly. Resume uses
its existing database and state. Intake requests use deterministic idempotency
keys, so a retry does not stage a duplicate. A new benchmark needs a new name.
Do not delete `experiments/data/<name>/state.json` or the scratch DB if you want
to resume.

## Durable state and artifacts

`experiments/data/<name>/state.json` is the source of truth. It records the
current phase, completed work, staged chunk counts, and accumulated runtime.
The phase JSON files update after each operation. Ingest rows record synchronous
staging time and chunk count. `state.json` records live queue counts while the
runner polls `/ingest/pipeline`. Retrieval starts only when ready, leased,
retry-wait, and paused counts all reach zero. `latency.json` separates staging, queue drain, end-to-end ingest, recall, and
graph times. The judge uses Pi's CLI and the configured `cheap` tier from
`model-tiers.json`. Pi reads provider settings and credentials from its own
configuration. Judge failures and unscored sections go to `judge_errors.json`;
they do not count as failed assertions. `llm_scores.json` contains only completed
judge sections. Graph probes that cannot resolve an entity through `/recall` are
reported as lookup failures, not as missing database nodes. The journal writer
replaces an existing entry with the same run name, so a crash at finalization
will not create duplicate entries.

Re-score saved graph probes without rerunning ingestion or retrieval:

```bash
.venv/bin/python experiments/run_experiment.py --judge-only 09-baseline-gemma4-plan
```

The judge-only mode uses the current `cheap` tier and updates `llm_scores.json`
and the matching journal entry. It requires the Pi CLI on `PATH` or `PI_CLI_PATH`.

The runner service is named `brain-benchmark-<name>.service`; the API runs in a
separate `brain-benchmark-api-<port>.service`. Systemd restarts both after
unexpected failure and keeps runner output in the run log. A normal interrupt
stops only the runner, so staged intake remains available for resume.
The API stops when the benchmark completes. User lingering is required to run
after logout; this machine has lingering enabled.
