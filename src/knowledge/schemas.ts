import { Type, type TSchema } from "@sinclair/typebox";
const nodeId = Type.String({ pattern: "^(note|entity):[a-zA-Z0-9_⟨⟩-]+$" });
const edgeId = Type.String({ pattern: "^[a-z_][a-z0-9_]*:[a-zA-Z0-9_⟨⟩-]+$" });
const text = Type.String({ minLength: 1 });
const edgeType = Type.String({ pattern: "^[a-z_][a-z0-9_]*$" });
const limit = Type.Optional(Type.Integer({ minimum: 1, maximum: 100 }));
export const nodeFieldsSchema = Type.Object({ name: Type.Optional(text), type: Type.Optional(text), description: Type.Optional(Type.String()), content: Type.Optional(text), source: Type.Optional(Type.String()), summary: Type.Optional(Type.String()) });
export const nodeSchema = Type.Object({ id: nodeId, table: Type.Optional(Type.Union([Type.Literal("note"), Type.Literal("entity")])), kind: Type.Optional(Type.Union([Type.Literal("note"), Type.Literal("entity")])), name: Type.Optional(Type.String()), type: Type.Optional(Type.String()), description: Type.Optional(Type.String()), content: Type.Optional(Type.String()), source: Type.Optional(Type.String()), summary: Type.Optional(Type.String()), dreamAge: Type.Optional(Type.Number()), createdAt: Type.Optional(Type.String()), updatedAt: Type.Optional(Type.String()) });
export const edgeSchema = Type.Object({ id: edgeId, from: nodeId, to: nodeId, edgeType, table: Type.Optional(Type.String()), context: Type.Optional(Type.String()), createdAt: Type.Optional(Type.String()), updatedAt: Type.Optional(Type.String()) });
const graph = Type.Object({ nodes: Type.Array(nodeSchema), edges: Type.Array(edgeSchema) });
const raw = Type.Object({ id: Type.String(), intake_id: Type.String(), chunk_index: Type.Integer(), total_chunks: Type.Integer(), content: Type.String(), source: Type.String(), hints: Type.Array(Type.String()), created_at: Type.Optional(Type.String()) });
export const inputSchemas: Record<string, TSchema> = {
  storeNode: Type.Union([Type.Object({ kind: Type.Literal("entity"), name: text, type: text, description: Type.Optional(Type.String()) }), Type.Object({ kind: Type.Literal("note"), content: text, source: Type.Optional(Type.String()), summary: Type.Optional(Type.String()) })]),
  storeEdge: Type.Object({ fromId: nodeId, toId: nodeId, edgeType, context: Type.Optional(Type.String()) }),
  updateNode: Type.Object({ id: nodeId, field: Type.Union(["name", "type", "description", "content", "source", "summary"].map(v => Type.Literal(v))), oldText: text, newText: Type.String() }),
  searchMemory: Type.Object({ query: text, limit }), getNode: Type.Object({ id: nodeId }),
  exploreGraph: Type.Object({ id: nodeId, depth: Type.Optional(Type.Integer({ minimum: 0, maximum: 3 })), limit }),
  findSimilar: Type.Object({ id: nodeId, limit }), findUnlinkedCooccurrences: Type.Object({ limit }),
  mergeNodes: Type.Object({ survivorId: nodeId, loserIds: Type.Array(nodeId, { minItems: 1, uniqueItems: true }), survivorFields: Type.Optional(nodeFieldsSchema) }),
  mergeEdges: Type.Object({ survivorId: edgeId, loserIds: Type.Array(edgeId, { minItems: 1, uniqueItems: true }), context: Type.Optional(Type.String()) }),
  removeEdge: Type.Object({ id: edgeId }), renameEdgeType: Type.Object({ fromType: edgeType, toType: edgeType }),
};
export const outputSchemas: Record<string, TSchema> = {
  storeNode: nodeSchema, updateNode: nodeSchema,
  storeEdge: Type.Union([Type.Object({ status: Type.Literal("created"), edge: edgeSchema }), Type.Object({ status: Type.Literal("skipped"), reason: Type.Union([Type.Literal("self-edge"), Type.Literal("duplicate")]), edge: Type.Optional(edgeSchema) })]),
  searchMemory: Type.Object({ nodes: Type.Array(nodeSchema), unprocessed: Type.Array(raw) }),
  getNode: Type.Union([nodeSchema, Type.Null()]), exploreGraph: graph, findSimilar: Type.Array(nodeSchema),
  findUnlinkedCooccurrences: Type.Array(Type.Object({ fromId: nodeId, toId: nodeId, sharedNoteIds: Type.Array(nodeId) })),
  mergeNodes: Type.Object({ survivor: nodeSchema, removedIds: Type.Array(nodeId) }), mergeEdges: Type.Object({ survivor: edgeSchema, removedIds: Type.Array(edgeId) }),
  removeEdge: Type.Object({ id: edgeId, removed: Type.Boolean() }), renameEdgeType: Type.Object({ renamed: Type.Integer(), merged: Type.Integer() }),
};
