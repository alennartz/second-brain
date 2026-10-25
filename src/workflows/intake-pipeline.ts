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
function paragraphUnits(text: string): string[] {
  // Keep blank-line separators attached to the paragraph before them.
  const boundary = /(?:\r?\n[ \t]*){2,}/g;
  const units: string[] = [];
  let start = 0;
  for (const match of text.matchAll(boundary)) {
    const end = match.index! + match[0].length;
    const unit = text.slice(start, end);
    if (unit && unit.trim()) units.push(unit);
    start = end;
  }
  const last = text.slice(start);
  if (last && last.trim()) units.push(last);
  return units;
}

function sentenceUnits(text: string): string[] {
  // Split only when punctuation is followed by whitespace, and retain that whitespace.
  const units: string[] = [];
  let start = 0;
  let index = 0;
  while (index < text.length) {
    if (".!?".includes(text[index]!) && index + 1 < text.length && /\s/.test(text[index + 1]!)) {
      let next = index + 1;
      while (next < text.length && /\s/.test(text[next]!)) next++;
      const unit = text.slice(start, next);
      if (unit && unit.trim()) units.push(unit);
      start = next;
      index = next;
      continue;
    }
    index++;
  }
  const last = text.slice(start);
  if (last && last.trim()) units.push(last);
  return units;
}

function splitLongUnit(unit: string, max: number): string[] {
  const pieces: string[] = [];
  let start = 0;
  while (start < unit.length) {
    const remaining = unit.slice(start);
    if (remaining.length <= max) {
      pieces.push(remaining);
      break;
    }
    const window = unit.slice(start, start + max);
    let splitAt = -1;
    for (let index = 0; index < window.length; index++) if (/\s/.test(window[index]!)) splitAt = index;
    // Keep the separator attached to the preceding piece.
    const cut = splitAt <= 0 ? max : splitAt + 1;
    pieces.push(unit.slice(start, start + cut));
    start += cut;
  }
  return pieces.filter(piece => piece && piece.trim());
}

function splitSource(text: string, max: number): string[] {
  if (max <= 0) throw new Error("chunk maximum must be positive");
  const stripped = text.trim();
  if (!stripped) return [];
  const units: string[] = [];
  for (const paragraph of paragraphUnits(stripped)) {
    if (paragraph.length <= max) {
      units.push(paragraph);
      continue;
    }
    const sentences = sentenceUnits(paragraph);
    if (sentences.length === 1 && sentences[0] === paragraph) {
      units.push(...splitLongUnit(paragraph, max));
      continue;
    }
    for (const sentence of sentences) {
      if (sentence.length <= max) units.push(sentence);
      else units.push(...splitLongUnit(sentence, max));
    }
  }
  const chunks: string[] = [];
  let current = "";
  for (const unit of units) {
    if (!unit || !unit.trim()) continue;
    const pieces = unit.length > max ? splitLongUnit(unit, max) : [unit];
    for (const piece of pieces) {
      if (!piece || !piece.trim()) continue;
      if (current && current.length + piece.length > max) {
        chunks.push(current);
        current = "";
      }
      current += piece;
    }
  }
  if (current) chunks.push(current);
  return chunks;
}
export function createIntakePipeline(d: IntakePipelineDependencies): IntakePipeline {
  const state = { running: false, workers: [] as Promise<void>[], poll: new AbortController(), shutdown: new AbortController(), active: new Set<AbortController>() };
  async function runBatch(batch: IngestBatch, shutdownSignal: AbortSignal) {
    const controller = new AbortController(), heartbeat = new AbortController();
    const ownership = { valid: true, error: "" };
    const abortOnShutdown = () => controller.abort();
    if (shutdownSignal.aborted) controller.abort();
    else shutdownSignal.addEventListener("abort", abortOnShutdown, { once: true });
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
    } finally { heartbeat.abort(); await renew; shutdownSignal.removeEventListener("abort", abortOnShutdown); state.active.delete(controller); }
  }
  async function worker(signal: AbortSignal) {
    while (state.running && !signal.aborted) {
      try {
        const batch = await d.queue.claimIntakeBatch();
        if (batch) {
          if (signal.aborted || state.shutdown.signal.aborted || !state.running) {
            await d.queue.releaseIntakeBatch(batch.leaseToken, "Pipeline stopping", 0);
          } else {
            await runBatch(batch, state.shutdown.signal);
          }
          continue;
        }
      } catch (error) {
        console.error("Intake pipeline worker failed", error);
      }
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
    async start() {
      if (state.running) return;
      state.running = true;
      state.poll = new AbortController();
      state.shutdown = new AbortController();
      state.workers = Array.from({ length: d.settings.workers }, () => worker(state.poll.signal));
    },
    async stop() {
      if (!state.running && !state.workers.length) return;
      state.running = false;
      state.poll.abort();
      state.shutdown.abort();
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
