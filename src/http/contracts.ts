export type IntakeBody = { text: string; hints?: string[]; source?: string };
export type RecallBody = { question: string; hints?: string[] };
export type Context = {
  nodes: Record<string, unknown>[];
  edges: Record<string, unknown>[];
  unprocessed: Record<string, unknown>[];
};
export type RecallResponse = { answer: string; context: Context | null };
export type GraphResponse = {
  node: Record<string, unknown>;
  connections: { edge: Record<string, unknown>; node: Record<string, unknown> }[];
};
export type DreamJob = {
  job_id: string;
  status: "pending" | "running" | "complete" | "failed";
  error: string | null;
};
export type PipelineSnapshot = {
  ready: number;
  leased: number;
  retry_wait: number;
  paused: number;
  oldest_ready_at: string | null;
  oldest_retry_at: string | null;
  worker_count: number;
  active_leases: number;
  stuck_intakes: Record<string, unknown>[];
  recent_errors: Record<string, unknown>[];
};
export interface HttpApplication {
  enqueue(request: IntakeBody & { idempotency_key?: string }): Promise<{ chunks_stored: number }>;
  pipelineSnapshot(): Promise<PipelineSnapshot>;
  pause(intakeId: string): Promise<number>;
  resume(intakeId: string): Promise<number>;
  discard(intakeId: string): Promise<number>;
  startDream(): Promise<DreamJob>;
  getDreamJob(jobId: string): Promise<DreamJob | undefined>;
  recall(request: RecallBody): Promise<RecallResponse>;
  getGraph(recordId: string): Promise<GraphResponse | undefined>;
}
export interface RecallEvidenceStore {
  getNode(id: string): Promise<Record<string, unknown> | undefined>;
  getEdge(id: string): Promise<Record<string, unknown> | undefined>;
  getUnprocessed(id: string): Promise<Record<string, unknown> | undefined>;
}
export interface RecallAnswerSource {
  run(question: string, signal?: AbortSignal, hints?: readonly string[]): Promise<{
    answer: string; hasEvidence: boolean;
    nodeIds: readonly string[]; edgeIds: readonly string[]; unprocessedIds: readonly string[];
  }>;
}
export function createRecallService(_workflow: RecallAnswerSource, _storage: RecallEvidenceStore): {
  recall(request: RecallBody): Promise<RecallResponse>;
} {
  throw new Error("not implemented");
}
export type HttpFailureKind = "unavailable" | "invalid" | "conflict" | "upstream";
export class HttpApplicationError extends Error {
  constructor(public readonly kind: HttpFailureKind, message: string) {
    super(message);
    throw new Error("not implemented");
  }
}
