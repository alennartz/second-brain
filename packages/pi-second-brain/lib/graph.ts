import { Value } from "@sinclair/typebox/value";
import { maxTimestamp } from "../../../src/core/timestamps.ts";
import type { TSchema } from "@sinclair/typebox";
import {
  exploreGraphInput, findSimilarInput, findUnlinkedCooccurrencesInput, getNodeInput, mergeEdgesInput, mergeNodesInput,
  removeEdgeInput, renameEdgeTypeInput, searchMemoryInput, storeEdgeInput, storeNodeInput, updateNodeInput,
  type StoreNodeInput,
} from "./schemas.ts";
import type { EdgeId, EdgeRecord, NodeFields, NodeId, NodeRecord } from "../../../src/core/types.ts";
import type { MutationContext, Storage, StorageTransaction } from "../../../src/storage/storage.ts";

export type EditableNodeField = "name" | "type" | "description" | "content" | "source" | "summary";
export type StoreEdgeInput = { fromId: NodeId; edgeType: string; toId: NodeId; context?: string };
export type EdgeWriteResult =
  | { status: "created"; edge: EdgeRecord }
  | { status: "skipped"; reason: "self-edge" | "duplicate"; edge?: EdgeRecord };
export type MergeNodesResult = { survivor: NodeRecord; removedIds: readonly NodeId[] };
export type MergeEdgesResult = { survivor: EdgeRecord; removedIds: readonly EdgeId[] };
export type RemovedEdgeResult = { id: EdgeId; removed: boolean };
export type RenameEdgeTypeResult = { renamed: number; merged: number };
export type GraphResult = { nodes: readonly NodeRecord[]; edges: readonly EdgeRecord[] };
export type Cooccurrence = { fromId: NodeId; toId: NodeId; sharedNoteIds: readonly NodeId[] };

export type KnowledgeContext = MutationContext;

export type KnowledgeFunctions = {
  storeNode(input: StoreNodeInput): Promise<NodeRecord>;
  storeEdge(input: StoreEdgeInput): Promise<EdgeWriteResult>;
  updateNode(input: { id: NodeId; field: EditableNodeField; oldText: string; newText: string }): Promise<NodeRecord>;
  searchMemory(input: { query: string; limit?: number }): Promise<{ nodes: readonly NodeRecord[]; unprocessed: readonly unknown[] }>;
  getNode(input: { id: NodeId }): Promise<NodeRecord | undefined>;
  exploreGraph(input: { id: NodeId; depth?: number; limit?: number }): Promise<GraphResult>;
  findSimilar(input: { id: NodeId; limit?: number }): Promise<readonly NodeRecord[]>;
  findUnlinkedCooccurrences(input: { limit?: number }): Promise<readonly Cooccurrence[]>;
  mergeNodes(input: { survivorId: NodeId; loserIds: readonly NodeId[]; survivorFields?: NodeFields }): Promise<MergeNodesResult>;
  mergeEdges(input: { survivorId: EdgeId; loserIds: readonly EdgeId[]; context?: string }): Promise<MergeEdgesResult>;
  removeEdge(input: { id: EdgeId }): Promise<RemovedEdgeResult>;
  renameEdgeType(input: { fromType: string; toType: string }): Promise<RenameEdgeTypeResult>;
};

function assertValid(schema: TSchema, name: string, input: unknown): void {
  if (!Value.Check(schema, input)) throw new Error(`Invalid ${name} input`);
}
function bounded(value: number | undefined, fallback: number, max = 100): number {
  if (value === undefined) return fallback;
  if (!Number.isInteger(value) || value < 1 || value > max) throw new Error("Invalid result limit");
  return value;
}
function projectNode(node: NodeRecord): NodeRecord {
  const { id, table, kind, content, source, summary, name, type, description, dreamAge, createdAt, updatedAt, freshnessAt } = node;
  return Object.fromEntries(Object.entries({ id, table, kind, content, source, summary, name, type, description, dreamAge, createdAt, updatedAt, freshnessAt }).filter(([, v]) => v !== undefined)) as unknown as NodeRecord;
}
function validateFields(node: NodeRecord, fields: NodeFields): void {
  const kind = node.id.split(":")[0];
  const allowed = kind === "note" ? ["content", "source", "summary"] : ["name", "type", "description"];
  if (Object.keys(fields).some(key => !allowed.includes(key))) throw new Error("Field does not belong to node kind");
  const result = { ...node, ...fields };
  for (const field of kind === "note" ? ["content"] : ["name", "type"]) {
    if (typeof result[field as keyof NodeRecord] !== "string" || !(result[field as keyof NodeRecord] as string).trim()) throw new Error("Required node field is blank");
  }
}
async function requireNode(tx: StorageTransaction, id: NodeId): Promise<NodeRecord> {
  assertValid(getNodeInput, "getNode", { id });
  const node = await tx.getNode(id);
  if (!node) throw new Error(`Missing node ${id}`);
  return node;
}
async function requireEdge(tx: StorageTransaction, id: EdgeId): Promise<EdgeRecord> {
  assertValid(removeEdgeInput, "removeEdge", { id });
  if (/^(note|entity|intake_chunk):/.test(id)) throw new Error("Not an edge ID");
  const edge = await tx.getEdge(id);
  if (!edge) throw new Error(`Missing edge ${id}`);
  return edge;
}

export async function storeNode(storage: Storage, input: StoreNodeInput, context?: KnowledgeContext): Promise<NodeRecord> {
  assertValid(storeNodeInput, "storeNode", input);
  validateFields({ id: input.kind + ":new" }, Object.fromEntries(Object.entries(input).filter(([key]) => key !== "kind")));
  return projectNode(await storage.withTransaction(tx => tx.createNode(input, context)));
}

export async function storeEdge(storage: Storage, input: StoreEdgeInput, context?: KnowledgeContext): Promise<EdgeWriteResult> {
  assertValid(storeEdgeInput, "storeEdge", input);
  return storage.withTransaction(async tx => {
    await requireNode(tx, input.fromId);
    await requireNode(tx, input.toId);
    if (input.fromId === input.toId) return { status: "skipped", reason: "self-edge" };
    const existing = await tx.findEdges(input.fromId, input.edgeType, input.toId);
    if (existing.length) return { status: "skipped", reason: "duplicate", edge: existing[0] };
    return { status: "created", edge: await tx.createEdge(input, context) };
  });
}

export async function updateNode(storage: Storage, input: { id: NodeId; field: EditableNodeField; oldText: string; newText: string }, context?: KnowledgeContext): Promise<NodeRecord> {
  assertValid(updateNodeInput, "updateNode", input);
  return storage.withTransaction(async tx => {
    const node = await requireNode(tx, input.id);
    const text = node[input.field];
    if (typeof text !== "string" || text.split(input.oldText).length !== 2) throw new Error("Exact edit requires one match");
    const fields = { [input.field]: text.replace(input.oldText, () => input.newText) };
    validateFields(node, fields);
    return projectNode((await tx.updateNodeFields(input.id, fields, context))!);
  });
}

export async function getNode(storage: Storage, input: { id: NodeId }): Promise<NodeRecord | undefined> {
  assertValid(getNodeInput, "getNode", input);
  const node = await storage.getNode(input.id);
  return node ? projectNode(node) : undefined;
}

export async function searchMemory(storage: Storage, input: { query: string; limit?: number }) {
  assertValid(searchMemoryInput, "searchMemory", input);
  if (!input.query.trim()) throw new Error("Search query must not be blank");
  const limit = bounded(input.limit, 10);
  const result = await storage.searchCandidates(input.query.trim(), limit);
  return {
    nodes: result.nodes.slice(0, limit).map(projectNode),
    unprocessed: result.unprocessed.slice(0, limit).map(({ id, intake_id, chunk_index, total_chunks, content, source, hints, created_at, captured_at }) => ({ id, intake_id, chunk_index, total_chunks, content, source, hints, ...(created_at ? { created_at } : {}), ...(captured_at ? { captured_at } : {}) })),
  };
}

export async function exploreGraph(storage: Storage, input: { id: NodeId; depth?: number; limit?: number }): Promise<GraphResult> {
  assertValid(exploreGraphInput, "exploreGraph", input);
  const limit = bounded(input.limit, 50);
  const depth = input.depth ?? 1;
  const root = await getNode(storage, { id: input.id });
  if (!root) return { nodes: [], edges: [] };
  const nodes = new Map([[root.id, root]]);
  const edges = new Map<string, EdgeRecord>();
  let frontier = [root.id];
  for (let step = 0; step < depth && frontier.length; step++) {
    const next: string[] = [];
    for (const id of frontier) {
      for (const edge of [...await storage.getIncomingEdges(id), ...await storage.getOutgoingEdges(id)]) {
        if (edges.size >= limit) break;
        const otherId = edge.from === id ? edge.to : edge.from;
        const other = await getNode(storage, { id: otherId });
        if (!other || (!nodes.has(otherId) && nodes.size >= limit)) continue;
        edges.set(edge.id, edge);
        if (!nodes.has(otherId)) { nodes.set(otherId, other); next.push(otherId); }
      }
    }
    frontier = next;
  }
  return { nodes: [...nodes.values()], edges: [...edges.values()] };
}

export async function findSimilar(storage: Storage, input: { id: NodeId; limit?: number }): Promise<readonly NodeRecord[]> {
  assertValid(findSimilarInput, "findSimilar", input);
  const limit = bounded(input.limit, 10);
  return (await storage.findSimilarCandidates(input.id, limit)).filter(n => n.id !== input.id).slice(0, limit).map(projectNode);
}

export async function findUnlinkedCooccurrences(storage: Storage, input: { limit?: number }): Promise<readonly Cooccurrence[]> {
  assertValid(findUnlinkedCooccurrencesInput, "findUnlinkedCooccurrences", input);
  return storage.findUnlinkedCooccurrenceCandidates(bounded(input.limit, 10));
}

export async function mergeNodes(storage: Storage, input: { survivorId: NodeId; loserIds: readonly NodeId[]; survivorFields?: NodeFields }): Promise<MergeNodesResult> {
  assertValid(mergeNodesInput, "mergeNodes", input);
  if (input.loserIds.includes(input.survivorId)) throw new Error("Survivor cannot be a loser");
  return storage.withTransaction(async tx => {
    const survivor = await requireNode(tx, input.survivorId);
    const losers = await Promise.all(input.loserIds.map(id => requireNode(tx, id)));
    for (const loser of losers) if (loser.id.split(":")[0] !== survivor.id.split(":")[0]) throw new Error("Cannot merge different node kinds");
    validateFields(survivor, input.survivorFields ?? {});
    const freshnessAt = maxTimestamp([survivor.freshnessAt, ...losers.map(node => node.freshnessAt)]);
    const allEdges = new Map<string, EdgeRecord>();
    for (const id of [input.survivorId, ...input.loserIds]) for (const edge of [...await tx.getIncomingEdges(id), ...await tx.getOutgoingEdges(id)]) allEdges.set(edge.id, edge);
    const loserIds = new Set(input.loserIds);
    const relationships = new Map<string, EdgeRecord>();
    for (const edge of allEdges.values()) {
      const from = loserIds.has(edge.from) ? input.survivorId : edge.from;
      const to = loserIds.has(edge.to) ? input.survivorId : edge.to;
      if (from === to) { await tx.deleteEdge(edge.id); continue; }
      const key = JSON.stringify([from, edge.edgeType, to]);
      const previous = relationships.get(key);
      if (previous) {
        const context = [...new Set([previous.context, edge.context].filter(Boolean))].join("\n");
        const edgeFreshness = maxTimestamp([previous.freshnessAt, edge.freshnessAt]);
        if (context || edgeFreshness) { await tx.updateEdgeFields(previous.id, { ...(context ? { context } : {}), ...(edgeFreshness ? { freshnessAt: edgeFreshness } : {}) }); relationships.set(key, { ...previous, ...(context ? { context } : {}), ...(edgeFreshness ? { freshnessAt: edgeFreshness } : {}) }); }
        await tx.deleteEdge(edge.id);
        continue;
      }
      let retained = edge;
      if (from !== edge.from || to !== edge.to) retained = (await tx.updateEdgeFields(edge.id, { in: from, out: to }))!;
      relationships.set(key, retained);
    }
    const updated = Object.keys(input.survivorFields ?? {}).length || freshnessAt !== survivor.freshnessAt ? (await tx.updateNodeFields(survivor.id, input.survivorFields ?? {}, freshnessAt ? { freshnessAt } : undefined))! : survivor;
    for (const id of input.loserIds) await tx.deleteNode(id);
    return { survivor: projectNode(updated), removedIds: input.loserIds };
  });
}

export async function mergeEdges(storage: Storage, input: { survivorId: EdgeId; loserIds: readonly EdgeId[]; context?: string }): Promise<MergeEdgesResult> {
  assertValid(mergeEdgesInput, "mergeEdges", input);
  if (input.loserIds.includes(input.survivorId)) throw new Error("Survivor cannot be a loser");
  return storage.withTransaction(async tx => {
    const survivor = await requireEdge(tx, input.survivorId);
    const losers = await Promise.all(input.loserIds.map(id => requireEdge(tx, id)));
    if (losers.some(edge => edge.from !== survivor.from || edge.to !== survivor.to)) throw new Error("Edges require the same ordered pair");
    const context = input.context ?? [...new Set([survivor.context, ...losers.map(e => e.context)].filter(Boolean))].join("\n");
    const freshnessAt = maxTimestamp([survivor.freshnessAt, ...losers.map(edge => edge.freshnessAt)]);
    const updated = context || freshnessAt ? (await tx.updateEdgeFields(survivor.id, { ...(context ? { context } : {}), ...(freshnessAt ? { freshnessAt } : {}) }))! : survivor;
    for (const edge of losers) await tx.deleteEdge(edge.id);
    return { survivor: updated, removedIds: input.loserIds };
  });
}

export async function removeEdge(storage: Storage, input: { id: EdgeId }): Promise<RemovedEdgeResult> {
  assertValid(removeEdgeInput, "removeEdge", input);
  if (/^(note|entity|intake_chunk):/.test(input.id)) throw new Error("Not an edge ID");
  return storage.withTransaction(async tx => {
    const edge = await tx.getEdge(input.id);
    if (edge) await tx.deleteEdge(input.id);
    return { id: input.id, removed: !!edge };
  });
}

export async function renameEdgeType(storage: Storage, input: { fromType: string; toType: string }): Promise<RenameEdgeTypeResult> {
  assertValid(renameEdgeTypeInput, "renameEdgeType", input);
  if (input.fromType === input.toType) return { renamed: 0, merged: 0 };
  return storage.withTransaction(async tx => {
    const edges = await tx.getEdgesByType(input.fromType);
    let merged = 0;
    for (const edge of edges) {
      const collisions = await tx.findEdges(edge.from, input.toType, edge.to);
      if (collisions.length) {
        const survivor = collisions[0]!;
        const context = [...new Set([survivor.context, edge.context].filter(Boolean))].join("\n");
        const freshnessAt = maxTimestamp([survivor.freshnessAt, edge.freshnessAt]);
        if (context || freshnessAt) await tx.updateEdgeFields(survivor.id, { ...(context ? { context } : {}), ...(freshnessAt ? { freshnessAt } : {}) });
        await tx.deleteEdge(edge.id);
        merged++;
      } else await tx.updateEdgeFields(edge.id, { edge_type: input.toType });
    }
    return { renamed: edges.length, merged };
  });
}

export function normalizeArguments<T>(input: T): T {
  if (!input || typeof input !== "object" || Array.isArray(input)) return input;
  const result = { ...input } as Record<string, unknown>;
  for (const key of ["id", "fromId", "toId", "survivorId", "edgeType", "fromType", "toType", "query"]) if (typeof result[key] === "string") result[key] = (result[key] as string).trim();
  for (const key of ["limit", "depth"]) if (typeof result[key] === "string" && /^\d+$/.test(result[key] as string)) result[key] = Number(result[key]);
  return result as unknown as T;
}

export function prepareToolArguments<T>(args: unknown): T {
  return normalizeArguments(args) as T;
}

export function cancellableStorage(storage: Storage, signal: AbortSignal): Storage {
  function scope<T extends object>(target: T): T {
    return new Proxy(target, {
      get(object, key) {
        const value = Reflect.get(object, key);
        if (typeof value !== "function") return value;
        return (...args: unknown[]) => { signal.throwIfAborted(); return value.apply(object, args); };
      },
    });
  }
  return new Proxy(storage, {
    get(target, key) {
      if (key === "withTransaction") return <T>(operation: (tx: StorageTransaction) => Promise<T>) => storage.withTransaction(async tx => {
        signal.throwIfAborted();
        const result = await operation(scope(tx));
        signal.throwIfAborted();
        return result;
      });
      const value = Reflect.get(target, key);
      if (typeof value !== "function") return value;
      return (...args: unknown[]) => { signal.throwIfAborted(); return value.apply(target, args); };
    },
  });
}

export function bindKnowledge(storage: Storage, context?: KnowledgeContext): KnowledgeFunctions {
  return {
    storeNode: input => storeNode(storage, input, context),
    storeEdge: input => storeEdge(storage, input, context),
    updateNode: input => updateNode(storage, input, context),
    searchMemory: input => searchMemory(storage, input),
    getNode: input => getNode(storage, input),
    exploreGraph: input => exploreGraph(storage, input),
    findSimilar: input => findSimilar(storage, input),
    findUnlinkedCooccurrences: input => findUnlinkedCooccurrences(storage, input),
    mergeNodes: input => mergeNodes(storage, input),
    mergeEdges: input => mergeEdges(storage, input),
    removeEdge: input => removeEdge(storage, input),
    renameEdgeType: input => renameEdgeType(storage, input),
  };
}
