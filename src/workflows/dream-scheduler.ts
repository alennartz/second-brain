import type { DreamWorkflow } from "./workflows";
import type { WorkflowClock } from "./intake-pipeline";

export type DreamCycleResult = {
  aborted: boolean;
  deduplication: "completed" | "skipped" | "failed";
  connection: "completed" | "skipped" | "failed";
  errors: readonly string[];
};
export interface DreamQueue {
  countNodes(): Promise<number>;
  selectDreamBatch(kind: "entity" | "all", limit: number): Promise<readonly { id: string; dreamAge: number }[]>;
  incrementDreamAge(nodeIds: readonly string[]): Promise<void>;
}
export type DreamSchedulerDependencies = {
  workflow: DreamWorkflow;
  queue: DreamQueue;
  clock: WorkflowClock;
  onStateChange?: (state: { completedIdleCycles: number; maxIdleCycles: number; converged: boolean }) => void;
  settings: {
    batchSize: number;
    idleMs: number;
    backoffFactor: number;
    maxDelayMs: number;
    cycleTimeoutMs?: number;
  };
};
export interface DreamScheduler {
  start(): void;
  stop(): Promise<void>;
  touchActivity(): void;
  runCycle(): Promise<DreamCycleResult>;
  snapshot(): { completedIdleCycles: number; maxIdleCycles: number; converged: boolean };
}
export function createDreamScheduler(d: DreamSchedulerDependencies): DreamScheduler {
  const state = { running: false, loop: undefined as Promise<void> | undefined, cycle: undefined as Promise<DreamCycleResult> | undefined, active: undefined as AbortController | undefined, wait: undefined as AbortController | undefined, completedIdleCycles: 0, maxIdleCycles: 0, limitKnown: false, generation: 0 };
  const snapshot = () => ({ completedIdleCycles: state.completedIdleCycles, maxIdleCycles: state.maxIdleCycles, converged: state.limitKnown && state.completedIdleCycles >= state.maxIdleCycles });
  const notify = () => d.onStateChange?.(snapshot());
  async function cycle(controller: AbortController): Promise<DreamCycleResult> {
    const result: { aborted: boolean; deduplication: "completed" | "skipped" | "failed"; connection: "completed" | "skipped" | "failed"; errors: string[] } = { aborted: false, deduplication: "skipped", connection: "skipped", errors: [] };
    try { if (await d.queue.countNodes() === 0) return result; }
    catch (error) { return { ...result, deduplication: "failed", errors: [String(error)] }; }
    const processed = new Set<string>();
    for (const [kind, phase] of [["entity", "deduplication"], ["all", "connection"]] as const) {
      if (controller.signal.aborted) { result.aborted = true; break; }
      try {
        const batch = await d.queue.selectDreamBatch(kind, d.settings.batchSize);
        if (!batch.length) continue;
        const ids = batch.map(n => n.id);
        for (const id of ids) processed.add(id);
        const outcome = await (phase === "deduplication" ? d.workflow.deduplicate(ids, controller.signal) : d.workflow.connect(ids, controller.signal));
        result.aborted = outcome.aborted || controller.signal.aborted;
        result.errors.push(...outcome.errors);
        result[phase] = outcome.errors.length ? "failed" : result.aborted ? "skipped" : "completed";
        for (const id of outcome.touchedNodeIds ?? []) processed.add(id);
      } catch (error) { result[phase] = "failed"; result.errors.push(String(error)); result.aborted = controller.signal.aborted; }
      if (result.aborted || (phase === "deduplication" && result.deduplication === "failed")) break;
    }
    if (result.aborted) return result;
    if (processed.size) {
      try { await d.queue.incrementDreamAge([...processed].filter(id => /^(note|entity):/.test(id))); }
      catch (error) { result.errors.push(String(error)); }
    }
    return result;
  }
  function runCycle(): Promise<DreamCycleResult> {
    if (state.cycle) return state.cycle;
    if (state.active) return Promise.resolve({ aborted: true, deduplication: "failed", connection: "skipped", errors: ["Dream cycle is still stopping"] });
    const controller = new AbortController(); state.active = controller;
    const operation = cycle(controller);
    const waits: Promise<DreamCycleResult>[] = [operation];
    let timer: ReturnType<typeof setTimeout> | undefined;
    const timeoutMs = d.settings.cycleTimeoutMs;
    if (timeoutMs !== undefined && timeoutMs > 0) waits.push(new Promise(resolve => {
      timer = setTimeout(() => {
        resolve({ aborted: true, deduplication: "failed", connection: "skipped", errors: [`Dream cycle timed out after ${timeoutMs}ms`] });
        controller.abort();
      }, timeoutMs);
    }));
    let promise!: Promise<DreamCycleResult>;
    promise = Promise.race(waits).finally(() => {
      if (timer) clearTimeout(timer);
      state.cycle = undefined;
    });
    void operation.then(() => { if (state.active === controller) state.active = undefined; }, () => { if (state.active === controller) state.active = undefined; });
    state.cycle = promise;
    return promise;
  }
  async function loop() {
    while (state.running) {
      if (!state.limitKnown) {
        try {
          state.maxIdleCycles = Math.ceil(Math.sqrt(await d.queue.countNodes() / d.settings.batchSize));
          state.limitKnown = true;
          notify();
        } catch {
          await Promise.resolve();
          continue;
        }
      }
      if (!state.running) break;
      const controller = new AbortController();
      state.wait = controller;
      const generation = state.generation;
      try {
        if (snapshot().converged) {
          await new Promise<void>(resolve => {
            if (controller.signal.aborted) { resolve(); return; }
            controller.signal.addEventListener("abort", () => resolve(), { once: true });
          });
        } else {
          await d.clock.sleep(Math.min(d.settings.maxDelayMs, d.settings.idleMs * d.settings.backoffFactor ** state.completedIdleCycles), controller.signal);
        }
      } catch {
        if (state.running && !controller.signal.aborted) continue;
      } finally {
        if (state.wait === controller) state.wait = undefined;
      }
      if (!state.running) break;
      if (controller.signal.aborted || generation !== state.generation) continue;
      let result: DreamCycleResult;
      try { result = await runCycle(); }
      catch { continue; }
      if (!result.aborted && generation === state.generation) { state.completedIdleCycles++; notify(); }
    }
  }
  return {
    runCycle, snapshot,
    start() { if (state.running) return; state.running = true; state.loop = loop(); },
    async stop() { state.running = false; state.wait?.abort(); state.active?.abort(); await state.cycle; await state.loop; state.loop = undefined; },
    touchActivity() { state.generation++; state.completedIdleCycles = 0; state.limitKnown = false; state.wait?.abort(); state.active?.abort(); notify(); },
  };
}
