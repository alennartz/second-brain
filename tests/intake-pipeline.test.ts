import { describe, expect, test } from "bun:test";
import { createIntakePipeline, type IntakePipelineDependencies, type PipelineSnapshot } from "../src/workflows/intake-pipeline";
import type { IngestOutcome } from "../src/workflows/workflows";

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>(done => { resolve = done; });
  return { promise, resolve };
}
const empty: PipelineSnapshot = {
  ready: 0, leased: 0, retry_wait: 0, paused: 0,
  oldest_ready_at: null, oldest_retry_at: null, worker_count: 0, active_leases: 0,
  stuck_intakes: [], recent_errors: [],
};
function dependencies(): IntakePipelineDependencies {
  return {
    queue: {
      stageIntake: async (_request, chunks) => ({ chunksStored: chunks.length }),
      claimIntakeBatch: async () => undefined,
      renewIntakeBatch: async () => 1,
      deleteIntakeBatch: async () => 1,
      releaseIntakeBatch: async () => {},
      intakeQueueSnapshot: async () => empty,
      pauseIntake: async () => 2, resumeIntake: async () => 2, discardIntake: async () => 2,
    },
    workflow: { run: async () => ({ clean: true, aborted: false, errors: [] }) },
    clock: { now: () => 0, sleep: async (_ms, signal) => new Promise<void>(resolve => { signal?.addEventListener("abort", () => resolve(), { once: true }); }) },
    settings: { chunkMaxChars: 40, workers: 1, pollMs: 100, leaseRenewMs: 100, retryBaseMs: 100, retryCapMs: 800, shutdownGraceMs: 500 },
  };
}
const batch = {
  intakeId: "capture", leaseToken: "lease", chunks: [
    { id: "intake_chunk:a", chunkIndex: 0, content: "First.", hints: ["topic"], capturedAt: "2026-01-01T00:00:00Z" },
    { id: "intake_chunk:b", chunkIndex: 1, content: "Second.", hints: [], capturedAt: "2026-01-01T00:00:00Z" },
  ],
};

describe("intake pipeline staging", () => {
  test("stages bounded source chunks in order before returning acknowledgement", async () => {
    const deps = dependencies();
    const text = "One short paragraph.\n\nAnother short paragraph.\n\nThird paragraph.";
    const stored = deferred<void>();
    let drafts: Parameters<typeof deps.queue.stageIntake>[1] = [];
    deps.queue.stageIntake = async (_request, chunks) => { drafts = chunks; await stored.promise; return { chunksStored: chunks.length }; };
    const pipeline = createIntakePipeline(deps);
    let returned = false;
    const pending = pipeline.enqueue({ text, hints: ["topic"], source: "api", capturedAt: "2026-01-01T00:00:00Z" }).then(value => { returned = true; return value; });
    await Promise.resolve();
    expect(returned).toBe(false);
    stored.resolve();
    const result = await pending;
    expect(result.chunksStored).toBe(drafts.length);
    expect(drafts.length).toBeGreaterThan(1);
    expect(drafts.every(chunk => chunk.content.length <= 40)).toBe(true);
    expect(drafts.map(chunk => chunk.content).join("")).toBe(text.trim());
    expect(drafts.map(chunk => chunk.chunkIndex)).toEqual(drafts.map((_chunk, index) => index));
    expect(drafts.every(chunk => chunk.totalChunks === drafts.length && chunk.hints[0] === "topic")).toBe(true);
    expect(drafts.every(chunk => chunk.capturedAt === "2026-01-01T00:00:00Z")).toBe(true);
  });
  test("rejects blank text without staging evidence", async () => {
    const deps = dependencies();
    let calls = 0;
    deps.queue.stageIntake = async () => { calls++; return { chunksStored: 0 }; };
    const pipeline = createIntakePipeline(deps);
    await expect(pipeline.enqueue({ text: " \n\t", capturedAt: "2026-01-01T00:00:00Z" })).rejects.toThrow();
    expect(calls).toBe(0);
  });
  test("propagates staging failures without reporting an acknowledgement", async () => {
    const deps = dependencies();
    deps.queue.stageIntake = async () => { throw new Error("embedding failed"); };
    const pipeline = createIntakePipeline(deps);
    await expect(pipeline.enqueue({ text: "Capture.", capturedAt: "2026-01-01T00:00:00Z" })).rejects.toThrow("embedding failed");
  });
  test("passes the idempotency key to atomic queue staging", async () => {
    const deps = dependencies();
    let key: string | undefined;
    deps.queue.stageIntake = async request => { key = request.idempotencyKey; return { chunksStored: 1 }; };
    const pipeline = createIntakePipeline(deps);
    expect(await pipeline.enqueue({ text: "Capture.", capturedAt: "2026-01-01T00:00:00Z", idempotencyKey: "mobile-retry" })).toEqual({ chunksStored: 1 });
    expect(key).toBe("mobile-retry");
  });
});

describe("intake pipeline controls", () => {
  test.each(["pause", "resume", "discard"] as const)("%s affects only the selected intake and returns its affected count", async operation => {
    const deps = dependencies();
    const calls: string[] = [];
    const method = `${operation}Intake` as "pauseIntake" | "resumeIntake" | "discardIntake";
    deps.queue[method] = async id => { calls.push(id); return 2; };
    const pipeline = createIntakePipeline(deps);
    expect(await pipeline[operation]("capture-a")).toBe(2);
    expect(calls).toEqual(["capture-a"]);
  });
  test("reports queued retries and errors through the public snapshot", async () => {
    const deps = dependencies();
    deps.queue.intakeQueueSnapshot = async () => ({ ...empty, ready: 2, retry_wait: 1, recent_errors: [{ intake_id: "capture", error: "failed" }] });
    const result = await createIntakePipeline(deps).snapshot();
    expect(result.ready).toBe(2);
    expect(result.retry_wait).toBe(1);
    expect(result.recent_errors).toEqual([{ intake_id: "capture", error: "failed" }]);
  });
  test("start and stop are safe when repeated and stop exposes no live workers", async () => {
    const pipeline = createIntakePipeline(dependencies());
    await pipeline.start();
    await pipeline.start();
    await pipeline.stop();
    await pipeline.stop();
    expect((await pipeline.snapshot()).worker_count).toBe(0);
    expect((await pipeline.snapshot()).active_leases).toBe(0);
  });
});

describe("intake pipeline acknowledgement", () => {
  test.each([
    { clean: true, aborted: false, errors: [] },
    { clean: false, aborted: false, errors: ["write failed"] },
    { clean: false, aborted: true, errors: [] },
  ] satisfies IngestOutcome[])("acknowledges only a clean completed batch: %j", async outcome => {
    const deps = dependencies();
    const entered = deferred<void>();
    const completed = deferred<IngestOutcome>();
    const settled = deferred<void>();
    const deleted: string[] = [];
    const released: string[] = [];
    let claims = 0;
    deps.queue.claimIntakeBatch = async () => claims++ === 0 ? batch : undefined;
    deps.queue.deleteIntakeBatch = async token => { deleted.push(token); settled.resolve(); return 2; };
    deps.queue.releaseIntakeBatch = async token => { released.push(token); settled.resolve(); };
    deps.workflow.run = async received => { expect(received).toEqual(batch); entered.resolve(); return completed.promise; };
    const pipeline = createIntakePipeline(deps);
    await pipeline.start();
    await entered.promise;
    expect(deleted).toEqual([]);
    expect(released).toEqual([]);
    completed.resolve(outcome);
    await settled.promise;
    await pipeline.stop();
    expect(deleted).toEqual(outcome.clean ? ["lease"] : []);
    expect(released).toEqual(outcome.clean ? [] : ["lease"]);
  });
  test("stop cancels an active workflow and releases its unacknowledged lease", async () => {
    const deps = dependencies();
    deps.settings.shutdownGraceMs = 0;
    const wait = deps.clock.sleep;
    deps.clock.sleep = async (milliseconds, signal) => milliseconds === 0 ? undefined : wait(milliseconds, signal);
    const entered = deferred<void>();
    let claims = 0;
    let cancelled = false;
    const released: string[] = [];
    deps.queue.claimIntakeBatch = async () => claims++ === 0 ? batch : undefined;
    deps.queue.releaseIntakeBatch = async token => { released.push(token); };
    deps.workflow.run = async (_batch, signal) => {
      entered.resolve();
      return new Promise(resolve => signal?.addEventListener("abort", () => { cancelled = true; resolve({ clean: false, aborted: true, errors: [] }); }, { once: true }));
    };
    const pipeline = createIntakePipeline(deps);
    await pipeline.start();
    await entered.promise;
    await pipeline.stop();
    expect(cancelled).toBe(true);
    expect(released).toEqual(["lease"]);
  });
});
