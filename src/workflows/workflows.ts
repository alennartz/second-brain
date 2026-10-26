import { Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";
import { ingestPrompt, recallPrompt, dedupPrompt, connectPrompt } from "./prompts";
import type { AgentEvent, AgentRuntime, AgentTool } from "../agent-runtime";
import type { WorkflowModelRef } from "../core/config";
import { InvalidInputError, type EdgeId, type NodeId } from "../core/types";

export type WorkflowModel = WorkflowModelRef;
export type WorkflowTool = AgentTool;
export type WorkflowRuntime = AgentRuntime;

export type WorkflowDependencies = {
  runtime: WorkflowRuntime;
  model: WorkflowModel;
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
      const result = await d.runtime.run({ model: d.model, systemPrompt: ingestPrompt, prompt: JSON.stringify({ ...batch, chunks: [...batch.chunks].sort((a,b) => a.chunkIndex-b.chunkIndex) }), toolNames: [...ingestNames], signal });
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
const answerSchema = Type.Object({
  answer: Type.String({ minLength: 1, description: "Final answer text for the user." }),
  hasEvidence: Type.Boolean({ description: "True only when at least one citation ID is present." }),
  nodeIds: Type.Array(Type.String(), { description: "Cited note or entity IDs from this session's tool results." }),
  edgeIds: Type.Array(Type.String(), { description: "Cited edge IDs from this session's tool results." }),
  unprocessedIds: Type.Array(Type.String(), { description: "Cited raw evidence chunk IDs from this session's tool results." }),
});
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
    const tools: WorkflowTool[] = [];
    const onEvent = (event: AgentEvent) => {
      if (event.type !== "tool_execution_end" || event.isError || !readNames.includes(event.toolName as string)) return;
      collect((event.result as { structuredContent?: unknown } | undefined)?.structuredContent);
    };
    tools.push({ name: "answerRecall", label: "Answer Recall",
      description: "Submit the final validated answer directly. Use only citation IDs returned by the read tools. Set hasEvidence to false when all citation arrays are empty.",
      promptSnippet: "Submit the final recall answer with validated citation IDs.",
      parameters: answerSchema, outputSchema: answerSchema, execute: async (args, executionSignal) => {
      signal?.throwIfAborted(); executionSignal.throwIfAborted();
      if (!Value.Check(answerSchema, args)) throw new InvalidInputError("Invalid recall answer");
      const answer = args as RecallAnswer;
      if (answer.nodeIds.some(id => !nodes.has(id)) || answer.edgeIds.some(id => !edges.has(id)) || answer.unprocessedIds.some(id => !raw.has(id))) throw new InvalidInputError("Unknown citation");
      const count = answer.nodeIds.length + answer.edgeIds.length + answer.unprocessedIds.length;
      if (answer.hasEvidence !== (count > 0)) throw new InvalidInputError("Evidence flag does not match citations");
      state.answer = answer;
      return { toolName: "answerRecall", structuredContent: answer, stop: true };
    } });
    const followUpState = { requested: false };
    const result = await d.runtime.run({
      model: d.model,
      systemPrompt: recallPrompt,
      prompt: JSON.stringify({ question, hints }),
      toolNames: [...readNames],
      customTools: tools,
      signal,
      onEvent,
      followUp: current => {
        if (followUpState.requested || state.answer || current.aborted || !current.settled) return undefined;
        followUpState.requested = true;
        return "Continue by calling answerRecall.";
      },
    });
    if (signal?.aborted || result.aborted || !result.settled || !state.answer) throw new InvalidInputError("Recall did not return a validated answer");
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
      const result = await d.runtime.run({ model: d.model, systemPrompt, prompt: JSON.stringify(ids), toolNames: [...names], signal });
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
