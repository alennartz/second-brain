# Benchmark runs

Run benchmarks as supervised systemd user services. The runner saves state after
each operation, resumes unfinished work, and restarts after an unexpected exit.
It uses `data/brain-experiment.db`; it never touches the deployed `data/brain.db`.

## Start and monitor

```bash
make bench-start NAME=06-baseline-gemma4 NOTES="current Jetson stack"
make bench-status NAME=06-baseline-gemma4
make bench-log NAME=06-baseline-gemma4
```

Set `EXPERIMENT_PORT` to override the default scratch port `8101`. Set
`BENCH_OP_TIMEOUT` to change the per-operation deadline (default `900` seconds).

## Interrupt and resume

```bash
make bench-stop NAME=06-baseline-gemma4
make bench-resume NAME=06-baseline-gemma4
```

`bench-stop` sends SIGTERM. The runner saves state and exits cleanly. Resume uses
its existing database and state. An interrupted ingest keeps its server job ID,
so resume polls that job instead of submitting a duplicate. A new benchmark needs
a new name. Do not delete `experiments/data/<name>/state.json` or the scratch DB
if you want to resume.

## Durable state and artifacts

`experiments/data/<name>/state.json` is the source of truth. It records the
current phase, completed work, in-flight ingest job, and accumulated runtime.
The phase JSON files update after each operation. `latency.json`, `llm_scores.json`,
and the journal entry appear as their phases complete. The journal writer replaces
an existing entry with the same run name, so a crash at finalization will not
create duplicate entries.

The runner service is named `brain-benchmark-<name>.service`; the API runs in a
separate `brain-benchmark-api-<port>.service`. Systemd restarts both after
unexpected failure and keeps runner output in the run log. A normal interrupt
stops only the runner, so an in-flight server job remains available for resume.
The API stops when the benchmark completes. User lingering is required to run
after logout; this machine has lingering enabled.
