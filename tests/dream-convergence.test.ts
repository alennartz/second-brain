import { expect, test } from "bun:test";
import { createDreamScheduler } from "../src/workflows/dream-scheduler";

test("limits idle cycles to ceil(sqrt(nodes / batchSize)) and resets on activity", async () => {
  const waits: (() => void)[] = [];
  let notify!: () => void;
  let next = new Promise<void>(resolve => { notify = resolve; });
  let now = 0;
  let converge!: () => void;
  const converged = new Promise<void>(resolve => { converge = resolve; });
  const scheduler = createDreamScheduler({
    workflow: {
      deduplicate: async () => ({ aborted: false, errors: [] }),
      connect: async () => ({ aborted: false, errors: [] }),
    },
    queue: {
      countNodes: async () => 8,
      selectDreamBatch: async () => [{ id: "entity:a", dreamAge: 0 }],
      incrementDreamAge: async () => {},
    },
    onStateChange: state => { if (state.converged) converge(); },
    clock: {
      now: () => now,
      sleep: async (ms, signal) => new Promise<void>(resolve => {
        waits.push(() => { now += ms; resolve(); });
        signal?.addEventListener("abort", () => resolve(), { once: true });
        notify();
      }),
    },
    settings: { batchSize: 2, idleMs: 100, backoffFactor: 2, maxDelayMs: 800 },
  });
  scheduler.start();
  await next;
  expect(scheduler.snapshot().maxIdleCycles).toBe(2);
  for (let cycle = 0; cycle < 2; cycle++) {
    next = new Promise<void>(resolve => { notify = resolve; });
    waits[cycle]!();
    if (cycle === 0) await next;
    else await converged;
  }
  expect(scheduler.snapshot()).toMatchObject({ completedIdleCycles: 2, converged: true });
  scheduler.touchActivity();
  expect(scheduler.snapshot()).toMatchObject({ completedIdleCycles: 0, converged: false });
  await scheduler.stop();
});
