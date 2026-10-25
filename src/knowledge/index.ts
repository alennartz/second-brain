import type { NodeId, EdgeId, NodeRecord, EdgeRecord, NodeFields, MemorySearchResult } from "../core/types.ts";
import type { Storage } from "../storage/storage.ts";
import type { AgentTool } from "../agent-runtime/index.ts";
export type { NodeId, EdgeId, NodeRecord, EdgeRecord } from "../core/types.ts";

export type EditableNodeField = "name" | "type" | "description" | "content" | "source" | "summary";
export type StoreNodeInput =
  | { kind: "entity"; name: string; type: string; description?: string }
  | { kind: "note"; content: string; source?: string; summary?: string };
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
export type KnowledgeToolName = "searchMemory" | "getNode" | "exploreGraph" | "storeNode" | "storeEdge" | "updateNode" | "findSimilar" | "findUnlinkedCooccurrences" | "mergeNodes" | "mergeEdges" | "removeEdge" | "renameEdgeType";
export interface KnowledgeGraph {
  storeNode(input: StoreNodeInput): Promise<NodeRecord>;
  storeEdge(input: StoreEdgeInput): Promise<EdgeWriteResult>;
  updateNode(input: { id: NodeId; field: EditableNodeField; oldText: string; newText: string }): Promise<NodeRecord>;
  searchMemory(input: { query: string; limit?: number }): Promise<MemorySearchResult>;
  getNode(input: { id: NodeId }): Promise<NodeRecord | undefined>;
  exploreGraph(input: { id: NodeId; depth?: number; limit?: number }): Promise<GraphResult>;
  findSimilar(input: { id: NodeId; limit?: number }): Promise<readonly NodeRecord[]>;
  findUnlinkedCooccurrences(input: { limit?: number }): Promise<readonly Cooccurrence[]>;
  mergeNodes(input: { survivorId: NodeId; loserIds: readonly NodeId[]; survivorFields?: NodeFields }): Promise<MergeNodesResult>;
  mergeEdges(input: { survivorId: EdgeId; loserIds: readonly EdgeId[]; context?: string }): Promise<MergeEdgesResult>;
  removeEdge(input: { id: EdgeId }): Promise<RemovedEdgeResult>;
  renameEdgeType(input: { fromType: string; toType: string }): Promise<RenameEdgeTypeResult>;
  tools(names: readonly KnowledgeToolName[]): readonly AgentTool[];
}
export function createKnowledgeGraph(_storage: Storage): KnowledgeGraph {
  throw new Error("not implemented");
}
