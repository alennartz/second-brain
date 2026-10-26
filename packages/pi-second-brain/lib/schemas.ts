import { Type, type Static } from "@sinclair/typebox";

const nodeId = Type.String({ pattern: "^(note|entity):[a-zA-Z0-9_⟨⟩-]+$", description: "Canonical node ID with a note: or entity: prefix." });
const edgeId = Type.String({ pattern: "^[a-z_][a-z0-9_]*:[a-zA-Z0-9_⟨⟩-]+$", description: "Canonical edge ID with a type prefix." });
const text = Type.String({ minLength: 1 });
const edgeType = Type.String({ pattern: "^[a-z_][a-z0-9_]*$", description: "Relationship type: lowercase letters and underscores." });
const limit = Type.Optional(Type.Integer({ minimum: 1, maximum: 100, description: "Maximum results to return." }));

export const nodeFieldsSchema = Type.Object({
  name: Type.Optional(text),
  type: Type.Optional(text),
  description: Type.Optional(Type.String()),
  content: Type.Optional(text),
  source: Type.Optional(Type.String()),
  summary: Type.Optional(Type.String()),
}, { description: "Optional field updates applied to the surviving node." });

export const nodeSchema = Type.Object({
  id: nodeId,
  table: Type.Optional(Type.Union([Type.Literal("note"), Type.Literal("entity")])),
  kind: Type.Optional(Type.Union([Type.Literal("note"), Type.Literal("entity")])),
  name: Type.Optional(Type.String()),
  type: Type.Optional(Type.String()),
  description: Type.Optional(Type.String()),
  content: Type.Optional(Type.String()),
  source: Type.Optional(Type.String()),
  summary: Type.Optional(Type.String()),
  dreamAge: Type.Optional(Type.Number()),
  createdAt: Type.Optional(Type.String()),
  updatedAt: Type.Optional(Type.String()),
});

export const edgeSchema = Type.Object({
  id: edgeId,
  from: nodeId,
  to: nodeId,
  edgeType,
  table: Type.Optional(Type.String()),
  context: Type.Optional(Type.String()),
  createdAt: Type.Optional(Type.String()),
  updatedAt: Type.Optional(Type.String()),
});

const graph = Type.Object({ nodes: Type.Array(nodeSchema), edges: Type.Array(edgeSchema) });
const raw = Type.Object({
  id: Type.String(),
  intake_id: Type.String(),
  chunk_index: Type.Integer(),
  total_chunks: Type.Integer(),
  content: Type.String(),
  source: Type.String(),
  hints: Type.Array(Type.String()),
  created_at: Type.Optional(Type.String()),
});

export const storeNodeInput = Type.Union([
  Type.Object({ kind: Type.Literal("entity", { description: "Node kind selector." }), name: Type.String({ minLength: 1, description: "Entity name." }), type: Type.String({ minLength: 1, description: "Entity category." }), description: Type.Optional(Type.String({ description: "Optional entity description." })) }),
  Type.Object({ kind: Type.Literal("note", { description: "Node kind selector." }), content: Type.String({ minLength: 1, description: "Note text." }), source: Type.Optional(Type.String({ description: "Optional note origin." })), summary: Type.Optional(Type.String({ description: "Optional note digest." })) }),
]);
export type StoreNodeInput = Static<typeof storeNodeInput>;
export const storeNodeOutput = nodeSchema;

export const storeEdgeInput = Type.Object({ fromId: nodeId, toId: nodeId, edgeType, context: Type.Optional(Type.String({ description: "Optional context recorded on the relationship." })) });
export const storeEdgeOutput = Type.Union([
  Type.Object({ status: Type.Literal("created"), edge: edgeSchema }),
  Type.Object({ status: Type.Literal("skipped"), reason: Type.Union([Type.Literal("self-edge"), Type.Literal("duplicate")]), edge: Type.Optional(edgeSchema) }),
]);

export const updateNodeInput = Type.Object({
  id: nodeId,
  field: Type.Union(["name", "type", "description", "content", "source", "summary"].map(value => Type.Literal(value)), { description: "Node field to edit." }),
  oldText: Type.String({ minLength: 1, description: "Existing text to replace; must match exactly once." }),
  newText: Type.String({ description: "Replacement text." }),
});
export const updateNodeOutput = nodeSchema;

export const searchMemoryInput = Type.Object({ query: Type.String({ minLength: 1, description: "Text to search for." }), limit });
export const searchMemoryOutput = Type.Object({ nodes: Type.Array(nodeSchema), unprocessed: Type.Array(raw) });

export const getNodeInput = Type.Object({ id: nodeId });
export const getNodeOutput = Type.Union([nodeSchema, Type.Null()]);

export const exploreGraphInput = Type.Object({ id: nodeId, depth: Type.Optional(Type.Integer({ minimum: 0, maximum: 3, description: "Edge hops to follow." })), limit });
export const exploreGraphOutput = graph;

export const findSimilarInput = Type.Object({ id: nodeId, limit });
export const findSimilarOutput = Type.Array(nodeSchema);

export const findUnlinkedCooccurrencesInput = Type.Object({ limit });
export const findUnlinkedCooccurrencesOutput = Type.Array(Type.Object({ fromId: nodeId, toId: nodeId, sharedNoteIds: Type.Array(nodeId) }));

export const mergeNodesInput = Type.Object({
  survivorId: Type.String({ pattern: "^(note|entity):[a-zA-Z0-9_⟨⟩-]+$", description: "Node kept after the merge." }),
  loserIds: Type.Array(Type.String({ pattern: "^(note|entity):[a-zA-Z0-9_⟨⟩-]+$", description: "Node ID removed by the merge." }), { minItems: 1, uniqueItems: true, description: "Nodes folded into the survivor." }),
  survivorFields: Type.Optional(nodeFieldsSchema),
});
export const mergeNodesOutput = Type.Object({ survivor: nodeSchema, removedIds: Type.Array(nodeId) });

export const mergeEdgesInput = Type.Object({
  survivorId: Type.String({ pattern: "^[a-z_][a-z0-9_]*:[a-zA-Z0-9_⟨⟩-]+$", description: "Edge kept after the merge." }),
  loserIds: Type.Array(Type.String({ pattern: "^[a-z_][a-z0-9_]*:[a-zA-Z0-9_⟨⟩-]+$", description: "Edge ID removed by the merge." }), { minItems: 1, uniqueItems: true, description: "Edges folded into the survivor." }),
  context: Type.Optional(Type.String({ description: "Optional context recorded on the surviving edge." })),
});
export const mergeEdgesOutput = Type.Object({ survivor: edgeSchema, removedIds: Type.Array(edgeId) });

export const removeEdgeInput = Type.Object({ id: edgeId });
export const removeEdgeOutput = Type.Object({ id: edgeId, removed: Type.Boolean() });

export const renameEdgeTypeInput = Type.Object({ fromType: Type.String({ pattern: "^[a-z_][a-z0-9_]*$", description: "Existing relationship type." }), toType: Type.String({ pattern: "^[a-z_][a-z0-9_]*$", description: "New relationship type." }) });
export const renameEdgeTypeOutput = Type.Object({ renamed: Type.Integer(), merged: Type.Integer() });
