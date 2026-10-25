import { describe, expect, test } from "bun:test";
import { createIntakePipeline, type IntakePipelineDependencies } from "../src/workflows/intake-pipeline";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
function fixture() {
  const waits: { ms: number; finish: () => void }[] = [];
  let notify = deferred<void>();
  const observed = async (predicate: () => boolean) => {
    while (!predicate()) { const next = notify; await next.promise; }
  };
  const wake = () => { const previous = notify; notify = deferred<void>(); previous.resolve(); };
  const batch = { intakeId: "capture", leaseToken: "owned", chunks: [{ id: "intake_chunk:a", chunkIndex: 0, content: "Capture", hints: [] }] };
  let claims = 0;
  const deps: IntakePipelineDependencies = {
    queue: {
      stageIntake: async (_r, chunks) => ({ chunksStored: chunks.length }),
      claimIntakeBatch: async () => claims++ === 0 ? batch : undefined,
      renewIntakeBatch: async () => 1,
      deleteIntakeBatch: async () => 1,
      releaseIntakeBatch: async () => {},
      intakeQueueSnapshot: async () => ({ ready: 0, leased: 0, retry_wait: 0, paused: 0, oldest_ready_at: null, oldest_retry_at: null, worker_count: 0, active_leases: 0, stuck_intakes: [], recent_errors: [] }),
      pauseIntake: async () => 0, resumeIntake: async () => 0, discardIntake: async () => 0,
    },
    workflow: { run: async () => ({ clean: true, aborted: false, errors: [] }) },
    clock: { now: () => 0, sleep: async (ms, signal) => {
      if (signal?.aborted || ms === 0) return;
      await new Promise<void>(resolve => {
        waits.push({ ms, finish: resolve });
        signal?.addEventListener("abort", () => resolve(), { once: true });
        wake();
      });
    } },
    settings: { chunkMaxChars: 40, workers: 1, pollMs: 101, leaseRenewMs: 37, retryBaseMs: 100, retryCapMs: 400, shutdownGraceMs: 0 },
  };
  return { deps, waits, observed, wake, batch };
}

describe("intake lease reliability", () => {
  test("renews an active lease and cancels the workflow when ownership is lost", async () => {
    const f = fixture();
    const entered = deferred<void>();
    const cancelled = deferred<void>();
    const renewals: string[] = [];
    const deleted: string[] = [];
    f.deps.queue.renewIntakeBatch = async token => { renewals.push(token); return 0; };
    f.deps.queue.deleteIntakeBatch = async token => { deleted.push(token); return 1; };
    f.deps.workflow.run = async (_batch, signal) => {
      entered.resolve();
      return new Promise(resolve => signal?.addEventListener("abort", () => {
        cancelled.resolve(); resolve({ clean: false, aborted: true, errors: [] });
      }, { once: true }));
    };
    const pipeline = createIntakePipeline(f.deps);
    await pipeline.start();
    await entered.promise;
    await f.observed(() => f.waits.some(wait => wait.ms === 37));
    f.waits.find(wait => wait.ms === 37)!.finish();
    await cancelled.promise;
    await pipeline.stop();
    expect(renewals).toContain("owned");
    expect(deleted).toEqual([]);
  });
  test.each([[0, 100], [1, 200], [2, 400], [8, 400]])("releases failed attempt %i with capped retry delay %i", async (attemptCount, expectedDelay) => {
    const f = fixture();
    const released = deferred<void>();
    let retry: number | undefined;
    let error: string | undefined;
    f.deps.queue.claimIntakeBatch = (() => {
      let claimed = false;
      return async () => {
        if (claimed) return undefined;
        claimed = true;
        return { ...f.batch, attemptCount };
      };
    })();
    f.deps.workflow.run = async () => { throw new Error("provider failed"); };
    f.deps.queue.releaseIntakeBatch = async (token, message, delay) => {
      expect(token).toBe("owned"); error = message; retry = delay; released.resolve();
    };
    const pipeline = createIntakePipeline(f.deps);
    await pipeline.start();
    await released.promise;
    await pipeline.stop();
    expect(error).toBeTruthy();
    expect(retry).toBe(expectedDelay);
  });
});
