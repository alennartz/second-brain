import { describe, expect, test } from "bun:test";
import { createNodeEngines } from "@surrealdb/node";
import { Surreal } from "surrealdb";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { EmbedderStub } from "../src/embeddings/embedder.ts";
import { createEmbeddedStorage } from "../src/storage/embedded.ts";

async function openRaw(dbPath: string): Promise<Surreal> {
  const db = new Surreal({ engines: createNodeEngines() });
  await db.connect(`surrealkv://${dbPath}`);
  await db.use({ namespace: "brain", database: "brain" });
  return db;
}

async function rows(db: Surreal, query: string): Promise<Record<string, unknown>[]> {
  const result = await db.query(query).collect();
  const value = result[0];
  if (Array.isArray(value)) return value as Record<string, unknown>[];
  return value && typeof value === "object" ? [value as Record<string, unknown>] : [];
}

describe("fresh SurrealKV storage", () => {
  test("initializes the latest schema, indexes, relations, and queue state", async () => {
    const root = await mkdtemp(join(tmpdir(), "second-brain-surreal-latest-"));
    const dbPath = join(root, "brain.surreal");
    const storage = createEmbeddedStorage({
      dbPath,
      embeddingDimensions: 3,
      embedder: new EmbedderStub(() => [1, 0, 0]),
    });
    try {
      await storage.init();
      const note = await storage.createNode({
        kind: "note",
        content: "Fresh latest note",
        source: "test",
        summary: "Summary",
      });
      const entity = await storage.createNode({
        kind: "entity",
        name: "Fresh entity",
        type: "concept",
        description: "Description",
      });
      const edge = await storage.createEdge({
        fromId: note.id,
        edgeType: "references",
        toId: entity.id,
        context: "The note names the entity",
      });
      await storage.createIntakeChunks("fresh-intake", [
        {
          chunk_index: 0,
          total_chunks: 1,
          content: "Queued fresh evidence",
          source: "test",
          hints: ["fresh"],
        },
      ], "fresh-key");
      await storage.close();

      const db = await openRaw(dbPath);
      try {
        const notes = await rows(db, "SELECT * FROM note");
        const entities = await rows(db, "SELECT * FROM entity");
        const relations = await rows(db, "SELECT * FROM references");
        const chunks = await rows(db, "SELECT * FROM intake_chunk");
        const keys = await rows(db, "SELECT * FROM intake_key");
        expect(notes).toHaveLength(1);
        expect(notes[0]).toMatchObject({
          content: "Fresh latest note",
          source: "test",
          embedding: [1, 0, 0],
          dream_age: 0,
        });
        expect(String(notes[0]?.id)).toMatch(/^note:/);
        expect(entities[0]).toMatchObject({
          name: "Fresh entity",
          type: "concept",
          embedding: [1, 0, 0],
          dream_age: 0,
        });
        expect(String(entities[0]?.id)).toMatch(/^entity:/);
        expect(relations).toHaveLength(1);
        expect(String(relations[0]?.id)).toBe(edge.id);
        expect(String(relations[0]?.in)).toBe(note.id);
        expect(String(relations[0]?.out)).toBe(entity.id);
        expect(chunks[0]).toMatchObject({
          intake_id: "fresh-intake",
          chunk_index: 0,
          total_chunks: 1,
          content: "Queued fresh evidence",
          source: "test",
          hints: ["fresh"],
          embedding: [1, 0, 0],
          state: "ready",
          attempt_count: 0,
          paused: false,
          idempotency_key: "fresh-key",
        });
        expect(keys[0]).toMatchObject({
          intake_id: "fresh-intake",
          fingerprint: expect.any(String),
          chunk_count: 1,
        });

        const noteInfo = await rows(db, "INFO FOR TABLE note");
        const entityInfo = await rows(db, "INFO FOR TABLE entity");
        const intakeInfo = await rows(db, "INFO FOR TABLE intake_chunk");
        const serialized = JSON.stringify({ noteInfo, entityInfo, intakeInfo });
        expect(serialized).toContain("note_content_fts");
        expect(serialized).toContain("note_embedding_hnsw");
        expect(serialized).toContain("entity_name_fts");
        expect(serialized).toContain("entity_embedding_hnsw");
        expect(serialized).toContain("intake_chunk_content_fts");
        expect(serialized).toContain("intake_chunk_embedding_hnsw");
        expect(serialized).toContain("intake_chunk_intake_id");
        expect(serialized).toContain("intake_chunk_state");
      } finally {
        await db.close();
      }
    } finally {
      await storage.close().catch(() => undefined);
      await rm(root, { recursive: true, force: true });
    }
  });

  test("reopens a fresh database without migration and preserves normalized records", async () => {
    const root = await mkdtemp(join(tmpdir(), "second-brain-surreal-reopen-"));
    const dbPath = join(root, "brain.surreal");
    const embedder = new EmbedderStub(() => [0, 1, 0]);
    const first = createEmbeddedStorage({ dbPath, embeddingDimensions: 3, embedder });
    let noteId: string;
    try {
      await first.init();
      const note = await first.createNode({ kind: "note", content: "Reopen me" });
      noteId = note.id;
      expect(JSON.stringify(note)).not.toMatch(/embedding|RecordID|datetime/);
    } finally {
      await first.close();
    }

    const second = createEmbeddedStorage({ dbPath, embeddingDimensions: 3, embedder });
    try {
      await second.init();
      const note = await second.getNode(noteId!);
      expect(note).toMatchObject({ id: noteId!, kind: "note", content: "Reopen me" });
      expect(JSON.stringify(note)).not.toMatch(/embedding|RecordID|datetime/);
      const result = await second.searchCandidates("Reopen", 10);
      expect(result.nodes.map((candidate) => candidate.id)).toContain(noteId!);
    } finally {
      await second.close();
      await rm(root, { recursive: true, force: true });
    }
  });
});
