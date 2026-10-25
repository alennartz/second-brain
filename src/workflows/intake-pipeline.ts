import type { IngestBatch, IngestWorkflow } from "./workflows";
import type { IntakeQueueSnapshot } from "../core/types";

export type IntakeRequest = {
  text: string;
  hints?: readonly string[];
  source?: string;
  idempotencyKey?: string;
};
export type EnqueueResult = { chunksStored: number };
export type IntakeDraft = {
  content: string;
  chunkIndex: number;
  totalChunks: number;
  hints: readonly string[];
  source: string;
};
export type PipelineSnapshot = IntakeQueueSnapshot;
export interface IntakeQueue {
  stageIntake(request: IntakeRequest, chunks: readonly IntakeDraft[]): Promise<EnqueueResult>;
  claimIntakeBatch(): Promise<IngestBatch | undefined>;
  renewIntakeBatch(leaseToken: string): Promise<number>;
  deleteIntakeBatch(leaseToken: string): Promise<number>;
  releaseIntakeBatch(leaseToken: string, error?: string, retryDelayMs?: number): Promise<void>;
  intakeQueueSnapshot(): Promise<PipelineSnapshot>;
  pauseIntake(intakeId: string): Promise<number>;
  resumeIntake(intakeId: string): Promise<number>;
  discardIntake(intakeId: string): Promise<number>;
}
export interface WorkflowClock {
  now(): number;
  sleep(milliseconds: number, signal?: AbortSignal): Promise<void>;
}
export type IntakePipelineDependencies = {
  queue: IntakeQueue;
  workflow: IngestWorkflow;
  clock: WorkflowClock;
  settings: {
    chunkMaxChars: number;
    workers: number;
    pollMs: number;
    leaseRenewMs: number;
    retryBaseMs: number;
    retryCapMs: number;
    shutdownGraceMs: number;
  };
  onActivity?: () => void;
};
export interface IntakePipeline {
  enqueue(request: IntakeRequest): Promise<EnqueueResult>;
  start(): Promise<void>;
  stop(): Promise<void>;
  snapshot(): Promise<PipelineSnapshot>;
  pause(intakeId: string): Promise<number>;
  resume(intakeId: string): Promise<number>;
  discard(intakeId: string): Promise<number>;
}
function splitSource(text: string, max: number): string[] {
  const units = text.trim().split(/\n\s*\n/).flatMap(paragraph => paragraph.trim().match(/[^.!?]+[.!?]+(?:\s+|$)|[^.!?]+$/g) ?? [paragraph]);
  const chunks: string[] = [];
  for (const unit of units) {
    let rest = unit.trim();
    while (rest.length > max) {
      const space = rest.lastIndexOf(" ", max);
      const end = space > 0 ? space : max;
      chunks.push(rest.slice(0, end)); rest = rest.slice(end).trimStart();
    }
    if (!rest) continue;
    const previous = chunks.at(-1);
    if (previous && previous.length + rest.length + 1 <= max) chunks[chunks.length-1] = previous + " " + rest;
    else chunks.push(rest);
  }
  return chunks;
}
export function createIntakePipeline(d: IntakePipelineDependencies): IntakePipeline {
  const state = { running: false, workers: [] as Promise<void>[], poll: new AbortController(), active: new Set<AbortController>() };
  async function runBatch(batch: IngestBatch) {
    const controller = new AbortController(), heartbeat = new AbortController();
    const ownership = { valid: true, error: "" };
    state.active.add(controller);
    const renew = (async () => {
      while (!heartbeat.signal.aborted) {
        try { await d.clock.sleep(d.settings.leaseRenewMs, heartbeat.signal); }
        catch (error) { if (!heartbeat.signal.aborted) { ownership.valid = false; ownership.error = String(error); controller.abort(); } break; }
        if (heartbeat.signal.aborted) break;
        try { if (await d.queue.renewIntakeBatch(batch.leaseToken) <= 0) throw new Error("Lease ownership lost"); }
        catch (error) { ownership.valid = false; ownership.error = String(error); controller.abort(); break; }
      }
    })();
    try {
      let outcome;
      try { outcome = await d.workflow.run(batch, controller.signal); }
      catch (error) { outcome = { clean: false, aborted: controller.signal.aborted, errors: [String(error)] }; }
      heartbeat.abort(); await renew;
      if (outcome.clean && !outcome.aborted && !controller.signal.aborted && ownership.valid) await d.queue.deleteIntakeBatch(batch.leaseToken);
      else await d.queue.releaseIntakeBatch(batch.leaseToken, ownership.error || outcome.errors.join("; ") || "Batch aborted", Math.min(d.settings.retryCapMs, d.settings.retryBaseMs * 2 ** Math.min(30, batch.attemptCount ?? 0)));
    } finally { heartbeat.abort(); await renew; state.active.delete(controller); }
  }
  async function worker(signal: AbortSignal) {
    while (state.running && !signal.aborted) {
      try {
        const batch = await d.queue.claimIntakeBatch();
        if (batch) { await runBatch(batch); continue; }
      } catch { /* Queue outages retry at the polling interval. */ }
      try { await d.clock.sleep(d.settings.pollMs, signal); }
      catch { if (signal.aborted) break; }
    }
  }
  return {
    async enqueue(request) {
      if (!request.text.trim()) throw new Error("Intake text must not be blank");
      const contents = splitSource(request.text, d.settings.chunkMaxChars);
      const drafts = contents.map((content, chunkIndex) => ({ content, chunkIndex, totalChunks: contents.length, hints: request.hints ?? [], source: request.source ?? "api" }));
      const result = await d.queue.stageIntake(request, drafts); d.onActivity?.(); return result;
    },
    async start() { if (state.running) return; state.running = true; state.poll = new AbortController(); state.workers = Array.from({ length: d.settings.workers }, () => worker(state.poll.signal)); },
    async stop() {
      state.running = false; state.poll.abort();
      if (state.active.size) {
        const grace = new AbortController();
        try { await Promise.race([Promise.all(state.workers), d.clock.sleep(d.settings.shutdownGraceMs, grace.signal)]); }
        finally { grace.abort(); }
        for (const controller of state.active) controller.abort();
      }
      await Promise.all(state.workers); state.workers = [];
    },
    async snapshot() { return { ...await d.queue.intakeQueueSnapshot(), worker_count: state.running ? state.workers.length : 0, active_leases: state.active.size }; },
    pause: id => d.queue.pauseIntake(id), resume: id => d.queue.resumeIntake(id), discard: id => d.queue.discardIntake(id),
  };
}
