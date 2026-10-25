import type { AgentRuntime, AgentTool, WorkflowModelRef } from "../agent-runtime";
import type { EdgeId, NodeId } from "../core/types";

export type WorkflowModel = WorkflowModelRef;
export type WorkflowTool = AgentTool;
export type WorkflowRuntime = AgentRuntime;

export type WorkflowDependencies = {
  runtime: WorkflowRuntime;
  model: WorkflowModel;
  tools: readonly WorkflowTool[];
};

export type IngestBatch = {
  intakeId: string;
  leaseToken: string;
  chunks: readonly { id: string; chunkIndex: number; content: string; hints: readonly string[] }[];
};
export type IngestOutcome = { clean: boolean; aborted: boolean; errors: readonly string[] };
export interface IngestWorkflow {
  run(batch: IngestBatch, signal?: AbortSignal): Promise<IngestOutcome>;
}
export function createIngestWorkflow(_dependencies: WorkflowDependencies): IngestWorkflow {
  throw new Error("not implemented");
}

export type RecallAnswer = {
  answer: string;
  hasEvidence: boolean;
  nodeIds: readonly NodeId[];
  edgeIds: readonly EdgeId[];
  unprocessedIds: readonly NodeId[];
};
export interface RecallWorkflow {
  run(question: string, signal?: AbortSignal): Promise<RecallAnswer>;
}
export function createRecallWorkflow(_dependencies: WorkflowDependencies): RecallWorkflow {
  throw new Error("not implemented");
}

export type DreamPhaseResult = { aborted: boolean; errors: readonly string[]; touchedNodeIds?: readonly NodeId[] };
export interface DreamWorkflow {
  deduplicate(nodeIds: readonly string[], signal?: AbortSignal): Promise<DreamPhaseResult>;
  connect(nodeIds: readonly string[], signal?: AbortSignal): Promise<DreamPhaseResult>;
}
export function createDreamWorkflow(_dependencies: WorkflowDependencies): DreamWorkflow {
  throw new Error("not implemented");
}
