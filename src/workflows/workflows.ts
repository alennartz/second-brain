import { createHash } from "node:crypto";
import { Type } from "@sinclair/typebox";
import { Value } from "@sinclair/typebox/value";
import { ingestPrompt, recallPrompt, dedupPrompt, connectPrompt } from "./prompts";
import type { AgentEvent, AgentRuntime, AgentTool } from "../agent-runtime";
import type { WorkflowModelRef } from "../core/config";
import { InvalidInputError, type EdgeId, type NodeId } from "../core/types";
import { maxTimestamp } from "../core/timestamps";
import { withKnowledgeContext } from "../../packages/pi-second-brain/lib/bridge.ts";

export type WorkflowModel = WorkflowModelRef;
export type WorkflowTool = AgentTool;
export type WorkflowRuntime = AgentRuntime;

export type IngestMutationDiagnostic = {
  intake_id: string;
  chunk_ids: readonly string[];
  tool_name: string;
  tool_call_id?: string;
  argument_keys: readonly string[];
  kind?: "note" | "entity";
  node_id?: string;
  field?: string;
  payload_hash: string;
  error: string;
};
export type WorkflowDependencies = {
  runtime: WorkflowRuntime;
  model: WorkflowModel;
  onIngestDiagnostic?: (diagnostic: IngestMutationDiagnostic) => void;
};

export type IngestBatch = {
  intakeId: string;
  leaseToken: string;
  attemptCount?: number;
  chunks: readonly { id: string; chunkIndex: number; content: string; hints: readonly string[]; capturedAt: string }[];
};
export type IngestOutcome = { clean: boolean; aborted: boolean; errors: readonly string[]; retryable?: boolean };
export interface IngestWorkflow {
  run(batch: IngestBatch, signal?: AbortSignal): Promise<IngestOutcome>;
}
const ingestNames = ["memory_search", "memory_get_node", "memory_explore", "memory_store_node", "memory_store_edge", "memory_update_node"];
const readNames = ["memory_search", "memory_get_node", "memory_explore"];
const errorText = (error: unknown) => error instanceof Error ? error.message : String(error);
const ingestMutationTools = new Set(["memory_store_node", "memory_store_edge", "memory_update_node"]);
const editableFields = new Set(["name", "type", "description", "content", "source", "summary"]);
function record(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : undefined;
}
function argumentsRecord(value: unknown): Record<string, unknown> {
  if (typeof value === "string") {
    try { return record(JSON.parse(value)) ?? {}; }
    catch { return {}; }
  }
  return record(value) ?? {};
}
function serializedArguments(value: unknown): string {
  try { return JSON.stringify(value) ?? String(value); }
  catch { return String(value); }
}
function diagnosticError(event: AgentEvent): string {
  const result = record(event.result);
  const structured = result?.structuredContent ?? event.result;
  const details = record(structured);
  const message = typeof details?.error === "string" ? details.error : "Tool execution failed";
  const normalized = message.replace(/\\s+/g, " ").trim();
  return normalized.length > 240 ? `${normalized.slice(0, 240)}…` : normalized;
}
function mutationDiagnostic(batch: IngestBatch, event: AgentEvent, args: Record<string, unknown>): IngestMutationDiagnostic {
  const rawId = args.id ?? args.survivorId;
  const nodeId = typeof rawId === "string" && /^(note|entity):[a-zA-Z0-9_⟨⟩-]+$/.test(rawId) ? rawId : undefined;
  const kind = args.kind === "note" || args.kind === "entity" ? args.kind : nodeId?.split(":")[0] as "note" | "entity" | undefined;
  const field = typeof args.field === "string" && editableFields.has(args.field) ? args.field : undefined;
  const toolName = String(event.toolName);
  const callId = typeof event.toolCallId === "string" ? event.toolCallId : undefined;
  const payload = serializedArguments(args);
  return {
    intake_id: batch.intakeId,
    chunk_ids: batch.chunks.map(chunk => chunk.id),
    tool_name: toolName,
    ...(callId ? { tool_call_id: callId } : {}),
    argument_keys: Object.keys(args).sort(),
    ...(kind ? { kind } : {}),
    ...(nodeId ? { node_id: nodeId } : {}),
    ...(field ? { field } : {}),
    payload_hash: createHash("sha256").update(payload).digest("hex"),
    error: diagnosticError(event),
  };
}
function resultErrors(result: Awaited<ReturnType<WorkflowRuntime["run"]>>, mutationOnly = false) {
  const toolErrors = result.toolResults.filter(t => t.isError && (!mutationOnly || ingestMutationTools.has(t.toolName)));
  return [...toolErrors.map(t => JSON.stringify(t.structuredContent) ?? "Tool execution failed"), ...(!result.settled ? ["Run did not settle"] : [])];
}
function isNonRetryableIngestError(error: string): boolean {
  return /Field does not belong to node kind|Required node field is blank|Exact edit requires one match|Invalid tool parameters|Invalid storeNode input/.test(error);
}
function nonRetryableOutcome(errors: readonly string[]): Pick<IngestOutcome, "retryable"> {
  return errors.some(isNonRetryableIngestError) ? { retryable: false } : {};
}
export function createIngestWorkflow(d: WorkflowDependencies, guidance: string): IngestWorkflow {
  const systemPrompt = `${ingestPrompt}\n\n${guidance}`;
  return { async run(batch, signal) {
    const diagnostics: IngestMutationDiagnostic[] = [];
    const pendingArguments = new Map<string, unknown>();
    const report = d.onIngestDiagnostic ?? (diagnostic => console.error("Ingest mutation failed", diagnostic));
    const onEvent = (event: AgentEvent) => {
      if (!ingestMutationTools.has(String(event.toolName))) return;
      const callId = typeof event.toolCallId === "string" ? event.toolCallId : undefined;
      if (event.type === "tool_execution_start") {
        if (callId) pendingArguments.set(callId, event.args);
        return;
      }
      if (event.type !== "tool_execution_end" || !event.isError) return;
      const args = argumentsRecord(event.args ?? (callId ? pendingArguments.get(callId) : undefined));
      const diagnostic = mutationDiagnostic(batch, event, args);
      diagnostics.push(diagnostic);
      report(diagnostic);
      if (callId) pendingArguments.delete(callId);
    };
    try {
      if (signal?.aborted) return { clean: false, aborted: true, errors: [] };
      const freshnessAt = maxTimestamp(batch.chunks.map(chunk => chunk.capturedAt));
      const result = await withKnowledgeContext(freshnessAt ? { freshnessAt } : {}, () => d.runtime.run({ model: d.model, systemPrompt, prompt: JSON.stringify({ ...batch, chunks: [...batch.chunks].sort((a,b) => a.chunkIndex-b.chunkIndex) }), toolNames: [...ingestNames], signal, onEvent }));
      const errors = [...resultErrors(result, true), ...diagnostics.map(diagnostic => `Ingest mutation failed: ${JSON.stringify(diagnostic)}`)];
      const aborted = result.aborted || !!signal?.aborted;
      return { clean: !aborted && !errors.length, aborted, errors, ...nonRetryableOutcome(errors) };
    } catch (error) {
      const errors = [errorText(error), ...diagnostics.map(diagnostic => `Ingest mutation failed: ${JSON.stringify(diagnostic)}`)];
      return { clean: false, aborted: !!signal?.aborted, errors, ...nonRetryableOutcome(errors) };
    }
  } };
}

export type RecallAnswer = {
  answer: string;
  nodeIds?: readonly NodeId[];
  edgeIds?: readonly EdgeId[];
  unprocessedIds?: readonly NodeId[];
};
export interface RecallWorkflow {
  run(question: string, signal?: AbortSignal, hints?: readonly string[]): Promise<RecallAnswer>;
}
const answerSchema = Type.Object({
  answer: Type.String({ minLength: 1, description: "Final answer text for the user." }),
  nodeIds: Type.Optional(Type.Array(Type.String(), { description: "Cited note or entity IDs returned by this session's read-tool results." })),
  edgeIds: Type.Optional(Type.Array(Type.String(), { description: "Cited edge IDs returned by this session's read-tool results." })),
  unprocessedIds: Type.Optional(Type.Array(Type.String(), { description: "Cited raw evidence chunk IDs returned by this session's read-tool results." })),
});
export function createRecallWorkflow(d: WorkflowDependencies, guidance: string): RecallWorkflow {
  const systemPrompt = `${recallPrompt}\n\n${guidance}`;
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
      description: "Submit the final answer and any citation IDs. The workflow validates each citation against this session's read-tool results.",
      promptSnippet: "Submit the final recall answer with optional citation IDs.",
      promptGuidelines: [
        "After reading evidence, call answerRecall to submit the final answer.",
        "Use only IDs returned by memory_search, memory_get_node, or memory_explore in answerRecall citation arrays.",
        "When no evidence exists, omit citation arrays from answerRecall.",
      ],
      parameters: answerSchema, outputSchema: answerSchema, execute: async (args, executionSignal) => {
      signal?.throwIfAborted(); executionSignal.throwIfAborted();
      if (!Value.Check(answerSchema, args)) throw new InvalidInputError("Invalid recall answer");
      const answer = args as RecallAnswer;
      const nodeIds = answer.nodeIds ?? [], edgeIds = answer.edgeIds ?? [], unprocessedIds = answer.unprocessedIds ?? [];
      if (nodeIds.some(id => !nodes.has(id)) || edgeIds.some(id => !edges.has(id)) || unprocessedIds.some(id => !raw.has(id))) throw new InvalidInputError("Unknown citation");
      const normalized: RecallAnswer = {
        answer: answer.answer,
        ...(nodeIds.length ? { nodeIds } : {}),
        ...(edgeIds.length ? { edgeIds } : {}),
        ...(unprocessedIds.length ? { unprocessedIds } : {}),
      };
      state.answer = normalized;
      return { toolName: "answerRecall", structuredContent: normalized, stop: true };
    } });
    const followUpState = { requested: false };
    const result = await d.runtime.run({
      model: d.model,
      systemPrompt,
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
export type DreamGuidance = { deduplicate: string; connect: string };
export function createDreamWorkflow(d: WorkflowDependencies, guidance: DreamGuidance): DreamWorkflow {
  const deduplicationPrompt = `${dedupPrompt}\n\n${guidance.deduplicate}`;
  const connectionPrompt = `${connectPrompt}\n\n${guidance.connect}`;
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
    deduplicate: (ids, signal) => run(ids, signal, deduplicationPrompt, ["memory_find_similar", "memory_get_node", "memory_explore", "memory_merge_nodes", "memory_merge_edges", "memory_update_node", "memory_remove_edge", "memory_rename_edge_type"]),
    connect: (ids, signal) => run(ids, signal, connectionPrompt, ["memory_find_similar", "memory_suggest_edges", "memory_get_node", "memory_explore", "memory_store_edge", "memory_update_node"]),
  };
}
