import { Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";
import { ingestPrompt, recallPrompt, dedupPrompt, connectPrompt } from "./prompts";
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
  attemptCount?: number;
  chunks: readonly { id: string; chunkIndex: number; content: string; hints: readonly string[] }[];
};
export type IngestOutcome = { clean: boolean; aborted: boolean; errors: readonly string[] };
export interface IngestWorkflow {
  run(batch: IngestBatch, signal?: AbortSignal): Promise<IngestOutcome>;
}
const ingestNames = ["searchMemory", "getNode", "exploreGraph", "storeNode", "storeEdge", "updateNode"];
const readNames = ["searchMemory", "getNode", "exploreGraph"];
const selectTools = (d: WorkflowDependencies, names: readonly string[]) => d.tools.filter(t => names.includes(t.name));
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const ingestMutationTools = new Set(["storeNode", "storeEdge", "updateNode"]);
function resultErrors(result: Awaited<ReturnType<WorkflowRuntime["run"]>>, mutationOnly = false) {
  const toolErrors = result.toolResults.filter(t => t.isError && (!mutationOnly || ingestMutationTools.has(t.toolName)));
  return [...toolErrors.map(t => JSON.stringify(t.structuredContent)), ...(!result.settled ? ["Run did not settle"] : [])];
}
export function createIngestWorkflow(d: WorkflowDependencies): IngestWorkflow {
  return { async run(batch, signal) {
    try {
      if (signal?.aborted) return { clean: false, aborted: true, errors: [] };
      const result = await d.runtime.run({ model: d.model, systemPrompt: ingestPrompt, prompt: JSON.stringify({ ...batch, chunks: [...batch.chunks].sort((a,b) => a.chunkIndex-b.chunkIndex) }), tools: selectTools(d, ingestNames), signal });
      const errors = resultErrors(result, true);
      const aborted = result.aborted || !!signal?.aborted;
      return { clean: !aborted && !errors.length, aborted, errors };
    } catch (error) { return { clean: false, aborted: !!signal?.aborted, errors: [errorText(error)] }; }
  } };
}

export type RecallAnswer = {
  answer: string;
  hasEvidence: boolean;
  nodeIds: readonly NodeId[];
  edgeIds: readonly EdgeId[];
  unprocessedIds: readonly NodeId[];
};
export interface RecallWorkflow {
  run(question: string, signal?: AbortSignal, hints?: readonly string[]): Promise<RecallAnswer>;
}
const answerSchema = Type.Object({ answer: Type.String({ minLength: 1 }), hasEvidence: Type.Boolean(), nodeIds: Type.Array(Type.String()), edgeIds: Type.Array(Type.String()), unprocessedIds: Type.Array(Type.String()) });
export function createRecallWorkflow(d: WorkflowDependencies): RecallWorkflow {
  return { async run(question, signal, hints = []) {
    signal?.throwIfAborted();
    const state: { answer?: RecallAnswer } = {};
    const nodes = new Set<string>(), edges = new Set<string>(), raw = new Set<string>();
    const collect = (value: unknown) => {
      if (!value || typeof value !== "object") return;
      const v = value as Record<string, unknown>;
      for (const [key, set] of [["nodes", nodes], ["edges", edges], ["unprocessed", raw]] as const) {
        if (Array.isArray(v[key])) for (const item of v[key]) if (typeof item?.id === "string") set.add(item.id);
      }
      if (typeof v.id === "string" && /^(note|entity):/.test(v.id)) nodes.add(v.id);
    };
    const tools: WorkflowTool[] = selectTools(d, readNames).map(tool => ({ ...tool, execute: async (args, executionSignal) => {
      const result = await tool.execute(args, executionSignal);
      if (!result.isError) collect(result.structuredContent);
      return result;
    } }));
    tools.push({ name: "answerRecall", description: "Submit a validated answer with citations from collected evidence", parameters: answerSchema, outputSchema: answerSchema, execute: async (args, executionSignal) => {
      signal?.throwIfAborted(); executionSignal.throwIfAborted();
      if (!Value.Check(answerSchema, args)) throw new Error("Invalid recall answer");
      const answer = args as RecallAnswer;
      if (answer.nodeIds.some(id => !nodes.has(id)) || answer.edgeIds.some(id => !edges.has(id)) || answer.unprocessedIds.some(id => !raw.has(id))) throw new Error("Unknown citation");
      const count = answer.nodeIds.length + answer.edgeIds.length + answer.unprocessedIds.length;
      if (answer.hasEvidence !== (count > 0)) throw new Error("Evidence flag does not match citations");
      state.answer = answer;
      return { toolName: "answerRecall", structuredContent: answer, stop: true };
    } });
    const result = await d.runtime.run({ model: d.model, systemPrompt: recallPrompt, prompt: JSON.stringify({ question, hints }), tools, signal });
    if (signal?.aborted || result.aborted || !result.settled || !state.answer) throw new Error("Recall did not return a validated answer");
    return state.answer;
  } };
}

export type DreamPhaseResult = { aborted: boolean; errors: readonly string[]; touchedNodeIds?: readonly NodeId[] };
export interface DreamWorkflow {
  deduplicate(nodeIds: readonly string[], signal?: AbortSignal): Promise<DreamPhaseResult>;
  connect(nodeIds: readonly string[], signal?: AbortSignal): Promise<DreamPhaseResult>;
}
export function createDreamWorkflow(d: WorkflowDependencies): DreamWorkflow {
  async function run(ids: readonly string[], signal: AbortSignal | undefined, systemPrompt: string, names: readonly string[]): Promise<DreamPhaseResult> {
    try {
      if (signal?.aborted) return { aborted: true, errors: [] };
      const result = await d.runtime.run({ model: d.model, systemPrompt, prompt: JSON.stringify(ids), tools: selectTools(d, names), signal });
      const touched = new Set<string>();
      for (const tool of result.toolResults) {
        if (tool.isError) continue;
        const value = tool.structuredContent as { id?: string; survivor?: { id?: string } } | undefined;
        const id = value?.survivor?.id ?? value?.id;
        if (id && /^(note|entity):/.test(id)) touched.add(id);
      }
      return { aborted: result.aborted || !!signal?.aborted, errors: resultErrors(result), touchedNodeIds: [...touched] };
    } catch (error) { return { aborted: !!signal?.aborted, errors: [errorText(error)] }; }
  }
  return {
    deduplicate: (ids, signal) => run(ids, signal, dedupPrompt, ["findSimilar", "getNode", "exploreGraph", "mergeNodes", "mergeEdges", "updateNode", "removeEdge", "renameEdgeType"]),
    connect: (ids, signal) => run(ids, signal, connectPrompt, ["findSimilar", "findUnlinkedCooccurrences", "getNode", "exploreGraph", "storeEdge", "updateNode"]),
  };
}
