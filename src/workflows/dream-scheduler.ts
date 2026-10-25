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
  settings: {
    batchSize: number;
    idleMs: number;
    backoffFactor: number;
    maxDelayMs: number;
  };
};
export interface DreamScheduler {
  start(): void;
  stop(): Promise<void>;
  touchActivity(): void;
  runCycle(): Promise<DreamCycleResult>;
}
export function createDreamScheduler(_dependencies: DreamSchedulerDependencies): DreamScheduler {
  throw new Error("not implemented");
}
