import { describe, expect, test } from "bun:test";
import { bindKnowledge, cancellableStorage, type KnowledgeFunctions } from "../packages/pi-second-brain/lib/graph.ts";
import type { Storage } from "../src/storage/storage.ts";
import { storeNodeOutput } from "../packages/pi-second-brain/lib/schemas.ts";
import { createEmbeddedStorage } from "../src/storage/embedded.ts";
import { EmbedderStub } from "../src/embeddings/embedder.ts";
import { mkdtemp, rm } from "node:fs/promises";
import { existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Value } from "@sinclair/typebox/value";

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "second-brain-knowledge-"));
  const storage = createEmbeddedStorage({ dbPath: join(root, "brain.surreal"), embeddingDimensions: 3, embedder: new EmbedderStub(() => [1, 0, 0]) });
  try { await storage.init(); } catch (error) { await storage.close(); await rm(root, { recursive: true, force: true }); throw error; }
  const graph = bindKnowledge(storage);
  const close = async () => { try { await storage.close(); } finally { await rm(root, { recursive: true, force: true }); } };
  return { graph, storage, close };
}
async function run(body: (graph: KnowledgeFunctions, storage: Storage) => Promise<void>) {
  const { graph, storage, close } = await fixture();
  try { await body(graph, storage); } finally { await close(); }
}
const entity = (name: string) => ({ kind: "entity" as const, name, type: "person" });
describe("KnowledgeGraph", () => {
  test("stores one node and returns a canonical ID before the next call", () => run(async g => {
    const a = await g.storeNode(entity("Ada"));
    expect(a.id).toMatch(/^entity:/);
    expect(await g.getNode({ id: a.id })).toEqual(a);
  }));
  test("stores notes independently instead of updating or merging", () => run(async g => {
    const a = await g.storeNode({ kind: "note", content: "same evidence" });
    const b = await g.storeNode({ kind: "note", content: "same evidence" });
    expect(a.id).not.toBe(b.id);
    expect(await g.getNode({ id: a.id })).toEqual(a);
  }));
  test("creates edges between existing canonical nodes", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    const result = await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: b.id });
    expect(result.status).toBe("created");
    expect(result.edge?.id).toMatch(/^[^:]+:.+$/);
  }));
  test("skips self edges with a structured reason", () => run(async g => {
    const a = await g.storeNode(entity("Ada"));
    expect(await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: a.id })).toMatchObject({ status: "skipped", reason: "self-edge" });
  }));
  test("skips duplicate ordered relationships", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    const input = { fromId: a.id, edgeType: "knows", toId: b.id };
    await g.storeEdge(input);
    expect(await g.storeEdge(input)).toMatchObject({ status: "skipped", reason: "duplicate" });
  }));
  for (const id of ["Ada", "note:missing", "intake_chunk:raw"]) {
    test(`rejects edge endpoint ${id} without creating nodes`, () => run(async g => {
      const a = await g.storeNode(entity("Ada"));
      await expect(g.storeEdge({ fromId: a.id, edgeType: "knows", toId: id })).rejects.toThrow();
      expect(await g.getNode({ id: a.id })).toEqual(a);
    }));
  }
  test("edits exactly one occurrence in a selected field", () => run(async g => {
    const n = await g.storeNode({ kind: "note", content: "Ada wrote notes" });
    const edited = await g.updateNode({ id: n.id, field: "content", oldText: "notes", newText: "programs" });
    expect(edited.content).toBe("Ada wrote programs");
    expect((await g.searchMemory({ query: "programs" })).nodes.map(n => n.id)).toContain(n.id);
  }));
  for (const oldText of ["missing", "Ada"]) {
    test(`does not write when exact edit '${oldText}' has zero or multiple matches`, () => run(async g => {
      const n = await g.storeNode({ kind: "note", content: "Ada and Ada" });
      await expect(g.updateNode({ id: n.id, field: "content", oldText, newText: "Grace" })).rejects.toThrow();
      expect(await g.getNode({ id: n.id })).toEqual(n);
    }));
  }
  test("rejects an edit that produces invalid node content", () => run(async g => {
    const n = await g.storeNode({ kind: "note", content: "evidence" });
    await expect(g.updateNode({ id: n.id, field: "content", oldText: "evidence", newText: "" })).rejects.toThrow();
    expect(await g.getNode({ id: n.id })).toEqual(n);
  }));
  test("retains earlier committed writes after a later mutation fails", () => run(async g => {
    const n = await g.storeNode(entity("Ada"));
    await expect(g.storeEdge({ fromId: n.id, edgeType: "knows", toId: "entity:missing" })).rejects.toThrow();
    expect(await g.getNode({ id: n.id })).toEqual(n);
  }));
  test("returns absent nodes without fabricating graph records", () => run(async g => {
    expect(await g.getNode({ id: "note:missing" })).toBeUndefined();
  }));
  test("searches memory with bounded public projections", () => run(async g => {
    const n = await g.storeNode({ kind: "note", content: "Ada programs" });
    const result = await g.searchMemory({ query: "Ada", limit: 1 });
    expect(result.nodes.map(n => n.id)).toContain(n.id);
    expect(result.nodes.length).toBeLessThanOrEqual(1);
    expect(JSON.stringify(result)).not.toMatch(/embedding|lease_token|lease_expires/);
    expect(result.unprocessed).toBeArray();
  }));
  test("searches queued evidence without exposing queue lease metadata", async () => {
    const { graph, storage, close } = await fixture();
    try {
      await storage.createIntakeChunks("intake-one", [{ chunk_index: 0, total_chunks: 1, content: "Ada wrote programs", source: "api", hints: [] }]);
      const result = await graph.searchMemory({ query: "Ada" });
      expect(result.unprocessed).toContainEqual(expect.objectContaining({ intake_id: "intake-one", content: "Ada wrote programs" }));
      expect(JSON.stringify(result.unprocessed)).not.toMatch(/lease_token|lease_expires|attempt_count|next_attempt/);
    } finally { await close(); }
  });
  test("explores graph neighbors and includes canonical edge IDs", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    const e = await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: b.id });
    const result = await g.exploreGraph({ id: a.id, depth: 1 });
    expect(result.nodes.map(n => n.id)).toContain(b.id);
    expect(result.edges.map(e => e.id)).toContain(e.edge!.id);
  }));
  test("finds similar nodes but excludes the source node", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    const result = await g.findSimilar({ id: a.id, limit: 1 });
    expect(result.map(n => n.id)).toEqual([b.id]);
    expect(JSON.stringify(result)).not.toContain("embedding");
  }));
  test("discovers cooccurring nodes and excludes already linked pairs", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    const note = await g.storeNode({ kind: "note", content: "Ada met Grace" });
    await g.storeEdge({ fromId: note.id, edgeType: "references", toId: a.id });
    await g.storeEdge({ fromId: note.id, edgeType: "references", toId: b.id });
    expect(await g.findUnlinkedCooccurrences({})).toContainEqual(expect.objectContaining({ sharedNoteIds: [note.id] }));
    await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: b.id });
    expect(await g.findUnlinkedCooccurrences({})).toEqual([]);
  }));
  test("merges identities, repoints edges, removes self edges and deduplicates collisions", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("A. Lovelace")), c = await g.storeNode(entity("Grace"));
    await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: b.id });
    await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: c.id });
    await g.storeEdge({ fromId: b.id, edgeType: "knows", toId: c.id });
    const result = await g.mergeNodes({ survivorId: a.id, loserIds: [b.id], survivorFields: { name: "Ada Lovelace" } });
    expect(result.survivor.id).toBe(a.id);
    expect(result.survivor.name).toBe("Ada Lovelace");
    expect(await g.getNode({ id: b.id })).toBeUndefined();
    expect((await g.exploreGraph({ id: a.id })).edges).toHaveLength(1);
  }));
  test("rejects an invalid identity merge atomically", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    await expect(g.mergeNodes({ survivorId: a.id, loserIds: [b.id, "entity:missing"] })).rejects.toThrow();
    expect(await g.getNode({ id: b.id })).toEqual(b);
  }));
  test("merges edges for one ordered pair and preserves survivor identity", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    const first = await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: b.id });
    const second = await g.storeEdge({ fromId: a.id, edgeType: "met", toId: b.id });
    const merged = await g.mergeEdges({ survivorId: first.edge!.id, loserIds: [second.edge!.id], context: "reconciled" });
    expect(merged.survivor.id).toBe(first.edge!.id);
    expect((await g.exploreGraph({ id: a.id })).edges).toHaveLength(1);
  }));
  test("rejects edge merges with a different ordered pair without deleting edges", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    const first = await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: b.id });
    const second = await g.storeEdge({ fromId: b.id, edgeType: "knows", toId: a.id });
    await expect(g.mergeEdges({ survivorId: first.edge!.id, loserIds: [second.edge!.id] })).rejects.toThrow();
    expect((await g.exploreGraph({ id: a.id })).edges).toHaveLength(2);
  }));
  test("removes one edge without deleting endpoint nodes", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    const e = await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: b.id });
    expect(await g.removeEdge({ id: e.edge!.id })).toMatchObject({ id: e.edge!.id, removed: true });
    expect((await g.exploreGraph({ id: a.id })).edges).toHaveLength(0);
    expect(await g.getNode({ id: b.id })).toEqual(b);
  }));
  test("globally renames edge types and merges collisions", () => run(async g => {
    const a = await g.storeNode(entity("Ada")), b = await g.storeNode(entity("Grace"));
    await g.storeEdge({ fromId: a.id, edgeType: "met", toId: b.id });
    await g.storeEdge({ fromId: a.id, edgeType: "knows", toId: b.id });
    expect(await g.renameEdgeType({ fromType: "met", toType: "knows" })).toMatchObject({ renamed: 1, merged: 1 });
    expect((await g.exploreGraph({ id: a.id })).edges).toHaveLength(1);
  }));
  test("bound knowledge functions return schema-valid structured results", () => run(async g => {
    const result = await g.storeNode(entity("Ada"));
    expect(Value.Check(storeNodeOutput, result)).toBe(true);
    expect(result).toMatchObject({ id: expect.stringMatching(/^entity:/) });
  }));
  test("validates arguments at the library boundary", () => run(async g => {
    await expect(g.storeNode({ kind: "entity", name: 12, type: "person" } as never)).rejects.toThrow();
    const result = await g.storeNode(entity("Ada"));
    expect(Value.Check(storeNodeOutput, result)).toBe(true);
  }));
  test("registers one extension file per knowledge tool for pi discovery", () => {
    const names = ["memory_search", "memory_get_node", "memory_explore", "memory_store_node", "memory_store_edge", "memory_update_node", "memory_find_similar", "memory_suggest_edges", "memory_merge_nodes", "memory_merge_edges", "memory_remove_edge", "memory_rename_edge_type"];
    for (const name of names) {
      const kebab = name.replace(/_/g, "-");
      const file = join(import.meta.dir, "..", "packages", "pi-second-brain", "extensions", `${kebab}.ts`);
      expect(existsSync(file)).toBe(true);
    }
  });
  test("rejects names and non-node IDs in graph reads", () => run(async g => {
    await expect(g.getNode({ id: "Ada" })).rejects.toThrow();
    await expect(g.exploreGraph({ id: "edge:one" })).rejects.toThrow();
    await expect(g.findSimilar({ id: "intake_chunk:one" })).rejects.toThrow();
  }));
  test("node reads omit private storage fields", () => run(async g => {
    const n = await g.storeNode(entity("Ada"));
    expect(JSON.stringify(await g.getNode({ id: n.id }))).not.toMatch(/embedding|lease_token|lease_expires/);
  }));
  test("library calls stop when the session signal is cancelled", () => run(async (_g, storage) => {
    const controller = new AbortController(); controller.abort();
    const cancelled = bindKnowledge(cancellableStorage(storage, controller.signal));
    await expect(cancelled.storeNode(entity("Ada"))).rejects.toThrow();
    expect((await bindKnowledge(storage).searchMemory({ query: "Ada" })).nodes).toEqual([]);
  }));
});
