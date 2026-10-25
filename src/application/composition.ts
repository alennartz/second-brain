import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import type { Settings } from "../core/config";
import type { Embedder } from "../embeddings/embedder";
import type { Storage } from "../storage/storage";
import type { NodeRecord, EdgeRecord } from "../core/types";
import { createSdkAgentRuntime } from "../agent-runtime";
import { createEmbeddedStorage } from "../storage/embedded";
import { createKnowledgeGraph, type KnowledgeGraph } from "../knowledge";
import { createIngestWorkflow, createRecallWorkflow, createDreamWorkflow } from "../workflows/workflows";
import { createIntakePipeline, type IntakePipeline, type WorkflowClock } from "../workflows/intake-pipeline";
import { createDreamScheduler, type DreamScheduler } from "../workflows/dream-scheduler";
import { createRecallService, HttpApplicationError } from "../http/contracts";
import type { CompositionFactories } from "./runtime";

export const systemClock: WorkflowClock = {
  now: () => Date.now(),
  sleep(milliseconds, signal) {
    return new Promise(resolve => {
      if (signal?.aborted) { resolve(); return; }
      const finish = () => { clearTimeout(timer); signal?.removeEventListener("abort", finish); resolve(); };
      const timer = setTimeout(finish, milliseconds);
      signal?.addEventListener("abort", finish, { once: true });
    });
  },
};
function nodeWire(node: NodeRecord): Record<string, unknown> {
  const { kind, dreamAge, createdAt, updatedAt, ...fields } = node;
  return { ...fields, ...(dreamAge === undefined ? {} : { dream_age: dreamAge }), ...(createdAt === undefined ? {} : { created_at: createdAt }), ...(updatedAt === undefined ? {} : { updated_at: updatedAt }) };
}
function edgeWire(edge: EdgeRecord): Record<string, unknown> {
  const { edgeType, ...fields } = edge;
  return { ...fields, table: edge.id.split(":")[0] };
}
const toolNames = ["searchMemory", "getNode", "exploreGraph", "storeNode", "storeEdge", "updateNode", "findSimilar", "findUnlinkedCooccurrences", "mergeNodes", "mergeEdges", "removeEdge", "renameEdgeType"] as const;
export function createProductionFactories(settings: Settings, modelRuntime: ModelRuntime, embedder: Embedder, cwd: string, agentDir: string): CompositionFactories<Embedder, Storage, KnowledgeGraph, IntakePipeline, DreamScheduler> {
  const runtime = createSdkAgentRuntime({ modelRuntime, cwd, agentDir });
  const workflowDependencies = (knowledge: KnowledgeGraph, model: Settings["ingestModel"]) => ({ runtime, model, tools: knowledge.tools(toolNames) });
  return {
    createModelRuntime: () => modelRuntime,
    createEmbedder: () => embedder,
    createStorage: () => createEmbeddedStorage({ dbPath: settings.dbPath, embeddingDimensions: settings.embeddingDimensions, embedder }),
    createKnowledge: storage => createKnowledgeGraph(storage),
    createPipeline({ storage, knowledge }) {
      return createIntakePipeline({
        workflow: createIngestWorkflow(workflowDependencies(knowledge, settings.ingestModel)), clock: systemClock,
        settings: { chunkMaxChars: settings.intake.chunkChars, workers: settings.intake.workerConcurrency, pollMs: settings.intake.pollIntervalSeconds * 1000, leaseRenewMs: settings.intake.leaseSeconds * 1000 / 3, retryBaseMs: settings.intake.retryBaseDelaySeconds * 1000, retryCapMs: settings.intake.retryMaxDelaySeconds * 1000, shutdownGraceMs: settings.intake.shutdownGraceSeconds * 1000 },
        queue: {
          async stageIntake(request, chunks) { return { chunksStored: await storage.createIntakeChunks(crypto.randomUUID(), chunks.map(c => ({ content: c.content, chunk_index: c.chunkIndex, total_chunks: c.totalChunks, hints: c.hints, source: c.source })), request.idempotencyKey) }; },
          async claimIntakeBatch() {
            const batch = await storage.claimIntakeBatch(`worker-${process.pid}`, settings.intake.processingBatchChars, settings.intake.leaseSeconds);
            return batch ? { intakeId: batch.intake_id, leaseToken: batch.lease_token, attemptCount: Math.max(...batch.chunks.map(c => c.attempt_count)), chunks: batch.chunks.map(c => ({ id: c.id, chunkIndex: c.chunk_index, content: c.content, hints: c.hints })) } : undefined;
          },
          renewIntakeBatch: token => storage.renewIntakeBatch(token, settings.intake.leaseSeconds),
          deleteIntakeBatch: token => storage.deleteIntakeBatch(token),
          releaseIntakeBatch: (token, error, delay) => storage.releaseIntakeBatch(token, error ?? "Batch aborted", new Date(systemClock.now() + (delay ?? 0)).toISOString()),
          intakeQueueSnapshot: () => storage.intakeQueueSnapshot(),
          pauseIntake: id => storage.setIntakePaused(id, true), resumeIntake: id => storage.setIntakePaused(id, false), discardIntake: id => storage.deleteIntake(id),
        },
      });
    },
    createScheduler({ storage, knowledge }) {
      const scheduler = createDreamScheduler({ workflow: createDreamWorkflow(workflowDependencies(knowledge, settings.dreamModel)), queue: { countNodes: () => storage.countNodes(), selectDreamBatch: async (kind, limit) => (await storage.selectDreamBatch(kind, limit)).map(node => ({ id: node.id, dreamAge: node.dreamAge ?? 0 })), incrementDreamAge: ids => storage.incrementDreamAge(ids) }, clock: systemClock, settings: { batchSize: settings.dream.batchSize, idleMs: settings.dream.idleTimeoutMinutes * 60000, backoffFactor: settings.dream.delayMultiplier, maxDelayMs: settings.dream.maxDelayMinutes * 60000 } });
      return settings.dream.enabled ? scheduler : { ...scheduler, start() {} };
    },
    createApplication({ storage, knowledge, pipeline, scheduler, dreamJobs }) {
      const pendingDreamJobs = new Set<Promise<void>>();
      const recall = createRecallService(createRecallWorkflow(workflowDependencies(knowledge, settings.recallModel)), {
        getNode: async id => { const node = await storage.getNode(id); return node ? nodeWire(node) : undefined; },
        getEdge: async id => { const edge = await storage.getEdge(id); return edge ? edgeWire(edge) : undefined; },
        getUnprocessed: async id => { const record = (await storage.getIntakeChunks([id]))[0]; if (!record) return undefined; return Object.fromEntries(["id", "intake_id", "chunk_index", "total_chunks", "content", "source", "hints", "created_at"].map(key => [key, record[key as keyof typeof record]])); },
      });
      return {
        async enqueue(request) {
          if (!request.text.trim() || request.text.length > settings.intake.maxRequestChars) throw new HttpApplicationError("invalid", "Invalid intake text length");
          try {
            const result = await pipeline.enqueue({ text: request.text, hints: request.hints, source: request.source, idempotencyKey: request.idempotency_key });
            scheduler.touchActivity(); return { chunks_stored: result.chunksStored };
          } catch (error) { throw new HttpApplicationError(String(error).toLowerCase().includes("idempotency") ? "conflict" : "unavailable", String(error)); }
        },
        pipelineSnapshot: async () => { const snapshot = await pipeline.snapshot(); return { ...snapshot, stuck_intakes: [...snapshot.stuck_intakes], recent_errors: [...snapshot.recent_errors] }; },
        pause: id => pipeline.pause(id), resume: id => pipeline.resume(id), discard: id => pipeline.discard(id),
        async startDream() {
          const job = { job_id: crypto.randomUUID(), status: "pending" as const, error: null };
          dreamJobs.set(job.job_id, job);
          let settle!: () => void;
          const completion = new Promise<void>(resolve => { settle = resolve; });
          pendingDreamJobs.add(completion);
          completion.then(() => pendingDreamJobs.delete(completion));
          queueMicrotask(() => {
            dreamJobs.set(job.job_id, { ...job, status: "running" });
            void scheduler.runCycle().then(result => {
              const error = result.errors.length ? result.errors.join("\n") : result.aborted ? "Dream cycle cancelled" : null;
              dreamJobs.set(job.job_id, { ...job, status: error ? "failed" : "complete", error });
              settle();
            }, error => {
              dreamJobs.set(job.job_id, { ...job, status: "failed", error: String(error) });
              settle();
            });
          });
          return job;
        },
        async waitForDreamJobs() {
          while (pendingDreamJobs.size) await Promise.all([...pendingDreamJobs]);
        },
        getDreamJob: async id => dreamJobs.get(id),
        recall: async request => { scheduler.touchActivity(); return recall.recall(request); },
        async getGraph(id) {
          const node = await storage.getNode(id); if (!node) return undefined;
          const edges = [...await storage.getIncomingEdges(id), ...await storage.getOutgoingEdges(id)];
          const connections = [];
          for (const edge of edges) { const other = await storage.getNode(edge.from === id ? edge.to : edge.from); if (other) connections.push({ edge: edgeWire(edge), node: nodeWire(other) }); }
          return { node: nodeWire(node), connections };
        },
      };
    },
  };
}
