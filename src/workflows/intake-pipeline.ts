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
export function createIntakePipeline(_dependencies: IntakePipelineDependencies): IntakePipeline {
  throw new Error("not implemented");
}
