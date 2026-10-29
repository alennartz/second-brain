import { describe, expect, test } from "bun:test";
import { createDreamScheduler, type DreamSchedulerDependencies } from "../src/workflows/dream-scheduler";

function dependencies(): DreamSchedulerDependencies {
  return {
    workflow: {
      deduplicate: async () => ({ aborted: false, errors: [] }),
      connect: async () => ({ aborted: false, errors: [] }),
    },
    queue: {
      countNodes: async () => 2,
      selectDreamBatch: async kind => kind === "entity" ? [{ id: "entity:a", dreamAge: 0 }] : [{ id: "note:b", dreamAge: 0 }],
      incrementDreamAge: async () => {},
    },
    clock: { now: () => 0, sleep: async (_ms, signal) => new Promise<void>(resolve => signal?.addEventListener("abort", () => resolve(), { once: true })) },
    settings: { batchSize: 2, idleMs: 100, backoffFactor: 2, maxDelayMs: 800 },
  };
}

describe("dream scheduler cycle", () => {
  test("deduplicates before connecting and advances processed nodes' dream age", async () => {
    const deps = dependencies();
    const phases: string[] = [];
    const aged: string[] = [];
    const selections: [string, number][] = [];
    deps.queue.selectDreamBatch = async (kind, limit) => {
      selections.push([kind, limit]);
      return [{ id: kind === "entity" ? "entity:a" : "note:b", dreamAge: 0 }];
    };
    deps.workflow.deduplicate = async ids => { phases.push(`dedup:${ids.join(",")}`); return { aborted: false, errors: [], touchedNodeIds: ids }; };
    deps.workflow.connect = async ids => { phases.push(`connect:${ids.join(",")}`); return { aborted: false, errors: [] }; };
    deps.queue.incrementDreamAge = async ids => { aged.push(...ids); };
    const result = await createDreamScheduler(deps).runCycle();
    expect(phases).toEqual(["dedup:entity:a", "connect:note:b"]);
    expect(selections).toEqual([["entity", 2], ["all", 2]]);
    expect(aged).toContain("entity:a");
    expect(aged).toContain("note:b");
    expect(result).toEqual({ aborted: false, deduplication: "completed", connection: "completed", errors: [] });
  });
  test("skips both phases on an empty graph", async () => {
    const deps = dependencies();
    let calls = 0;
    deps.queue.countNodes = async () => 0;
    deps.queue.selectDreamBatch = async () => [];
    deps.workflow.deduplicate = deps.workflow.connect = async () => { calls++; return { aborted: false, errors: [] }; };
    const result = await createDreamScheduler(deps).runCycle();
    expect(result.deduplication).toBe("skipped");
    expect(result.connection).toBe("skipped");
    expect(calls).toBe(0);
  });
  test("reports a failed deduplication phase without crashing the scheduler", async () => {
    const deps = dependencies();
    deps.workflow.deduplicate = async () => { throw new Error("model failed"); };
    const result = await createDreamScheduler(deps).runCycle();
    expect(result.deduplication).toBe("failed");
    expect(result.errors.length).toBeGreaterThan(0);
    expect(result.aborted).toBe(false);
  });
  test("reports tool errors in the connection phase", async () => {
    const deps = dependencies();
    deps.workflow.connect = async () => ({ aborted: false, errors: ["edge write failed"] });
    const result = await createDreamScheduler(deps).runCycle();
    expect(result.connection).toBe("failed");
    expect(result.errors).toContain("edge write failed");
  });
  test("times out a workflow that does not settle", async () => {
    const deps = dependencies();
    deps.settings.cycleTimeoutMs = 5;
    let signal: AbortSignal | undefined;
    deps.workflow.deduplicate = async (_ids, suppliedSignal) => {
      signal = suppliedSignal;
      return new Promise(() => {});
    };
    const result = await createDreamScheduler(deps).runCycle();
    expect(result.deduplication).toBe("failed");
    expect(result.errors[0]).toContain("timed out");
    expect(signal?.aborted).toBe(true);
  });
  test("activity cancels the active phase and prevents the next phase", async () => {
    const deps = dependencies();
    let connects = 0;
    let cancelled = false;
    const scheduler = createDreamScheduler(deps);
    deps.workflow.deduplicate = async (_ids, signal) => {
      scheduler.touchActivity();
      cancelled = signal?.aborted === true;
      return { aborted: cancelled, errors: [] };
    };
    deps.workflow.connect = async () => { connects++; return { aborted: false, errors: [] }; };
    const result = await scheduler.runCycle();
    expect(cancelled).toBe(true);
    expect(result.aborted).toBe(true);
    expect(connects).toBe(0);
  });
  test("stop cancels an active cycle and waits for it to settle", async () => {
    const deps = dependencies();
    let enter!: () => void;
    const entered = new Promise<void>(resolve => { enter = resolve; });
    let cancelled = false;
    deps.workflow.deduplicate = async (_ids, signal) => {
      enter();
      return new Promise(resolve => signal?.addEventListener("abort", () => {
        cancelled = true;
        resolve({ aborted: true, errors: [] });
      }, { once: true }));
    };
    const scheduler = createDreamScheduler(deps);
    const cycle = scheduler.runCycle();
    await entered;
    await scheduler.stop();
    expect(cancelled).toBe(true);
    expect((await cycle).aborted).toBe(true);
  });
});

describe("dream scheduler lifecycle", () => {
  test("start and stop tolerate repeated calls and create no duplicate idle waits", async () => {
    const deps = dependencies();
    let sleeps = 0;
    deps.clock.sleep = async (_ms, signal) => {
      sleeps++;
      return new Promise<void>(resolve => signal?.addEventListener("abort", () => resolve(), { once: true }));
    };
    const scheduler = createDreamScheduler(deps);
    scheduler.start();
    scheduler.start();
    await scheduler.stop();
    await scheduler.stop();
    expect(sleeps).toBeLessThanOrEqual(1);
  });
  test("increases idle delays to the cap and resets the delay after activity", async () => {
    const deps = dependencies();
    deps.queue.countNodes = async () => 1000;
    let now = 0;
    deps.clock.now = () => now;
    const waits: { milliseconds: number; finish: () => void }[] = [];
    let observed!: () => void;
    let next = new Promise<void>(resolve => { observed = resolve; });
    deps.clock.sleep = async (milliseconds, signal) => new Promise<void>(resolve => {
      waits.push({ milliseconds, finish: () => { now += milliseconds; resolve(); } });
      signal?.addEventListener("abort", () => resolve(), { once: true });
      observed();
    });
    const scheduler = createDreamScheduler(deps);
    scheduler.start();
    await next;
    for (let index = 0; index < 4; index++) {
      next = new Promise<void>(resolve => { observed = resolve; });
      waits[index]!.finish();
      await next;
    }
    expect(waits.map(wait => wait.milliseconds)).toEqual([100, 200, 400, 800, 800]);
    next = new Promise<void>(resolve => { observed = resolve; });
    scheduler.touchActivity();
    await next;
    expect(waits.at(-1)!.milliseconds).toBe(100);
    await scheduler.stop();
  });
  test("uses an idle delay and cancels that wait on activity", async () => {
    const deps = dependencies();
    let signal: AbortSignal | undefined;
    let delay: number | undefined;
    let enter!: () => void;
    const entered = new Promise<void>(resolve => { enter = resolve; });
    deps.clock.sleep = async (ms, suppliedSignal) => {
      delay = ms;
      signal = suppliedSignal;
      enter();
      return new Promise<void>(resolve => suppliedSignal?.addEventListener("abort", () => resolve(), { once: true }));
    };
    const scheduler = createDreamScheduler(deps);
    scheduler.start();
    await entered;
    scheduler.touchActivity();
    expect(delay).toBe(100);
    expect(signal?.aborted).toBe(true);
    await scheduler.stop();
  });
});
