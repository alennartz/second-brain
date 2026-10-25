import { describe, expect, test } from "bun:test";
import { createNodeEngines } from "@surrealdb/node";
import { mkdtemp, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Surreal } from "surrealdb";
import { EmbedderStub } from "../src/embeddings/embedder.ts";
import {
  createEmbeddedStorage,
  type EmbeddedStorageOptions,
} from "../src/storage/embedded.ts";
import type { Storage } from "../src/storage/storage.ts";

/**
 * The fixture writer uses the current Python Storage implementation.
 *
 * The test then opens the same file with the Bun SDK. This keeps the
 * compatibility check cross-engine instead of copying the schema in TypeScript.
 */
const PYTHON_FIXTURE_GENERATOR = String.raw`
from __future__ import annotations

import asyncio
import json
import sys

from second_brain.db import Storage
from second_brain.models import IntakeChunkDraft


class FixtureEmbedder:
    @staticmethod
    def vector(text: str) -> list[float]:
        if "Ada" in text or "Compatibility note" in text:
            return [1.0, 0.0, 0.0]
        if "entity" in text or "Compatibility entity" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]

    async def embed(self, text: str) -> list[float]:
        return self.vector(text)

    async def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.vector(text) for text in texts]


async def main(path: str) -> None:
    storage = Storage(
        url=f"surrealkv://{path}",
        embedder=FixtureEmbedder(),
        dimensions=3,
    )
    await storage.init()
    try:
        note = await storage.create_note(
            content="Compatibility note",
            source="python",
            summary="Persisted summary",
        )
        entity = await storage.create_entity(
            name="Compatibility entity",
            type="concept",
            description="Persisted entity",
        )
        derived = await storage.create_note(
            content="Derived compatibility note",
            source="python",
        )
        edge = await storage.create_edge(
            note["id"],
            "references",
            entity["id"],
            fields={"context": "The note names the entity"},
        )
        await storage.create_edge(
            entity["id"],
            "relates_to",
            note["id"],
            fields={"context": "The entity relates to the note"},
        )
        await storage.create_edge(derived["id"], "derived_from", note["id"])
        chunks = [
            IntakeChunkDraft(
                chunk_index=0,
                total_chunks=1,
                content="Queued compatibility evidence",
                source="python",
                hints=("compatibility",),
            )
        ]
        await storage.create_intake_chunks("compat-intake", chunks, "compat-key")
        print(json.dumps({"note": note["id"], "entity": entity["id"], "edge": edge["id"]}))
    finally:
        await storage.close()


asyncio.run(main(sys.argv[1]))
`;

type RawRecord = Record<string, unknown>;
type RawFixture = {
  db: Surreal;
  root: string;
  dbPath: string;
};

async function statementValue(db: Surreal, query: string): Promise<unknown> {
  const values = await db.query(query).collect();
  return values[0];
}

async function statementRows(db: Surreal, query: string): Promise<RawRecord[]> {
  const value = await statementValue(db, query);
  return Array.isArray(value) ? (value as RawRecord[]) : [];
}

async function runPythonFixture(root: string, dbPath: string): Promise<void> {
  const generatorPath = join(root, "generate-fixture.py");
  await writeFile(generatorPath, PYTHON_FIXTURE_GENERATOR, "utf8");
  const projectRoot = process.cwd();
  const child = Bun.spawn(
    ["uv", "run", "--project", projectRoot, "python", generatorPath, dbPath],
    {
      cwd: projectRoot,
      stdout: "pipe",
      stderr: "pipe",
    },
  );
  const [exitCode, stdout, stderr] = await Promise.all([
    child.exited,
    new Response(child.stdout).text(),
    new Response(child.stderr).text(),
  ]);
  if (exitCode !== 0) {
    throw new Error(`Python SurrealKV fixture failed (${exitCode}): ${stderr || stdout}`);
  }
}

async function openRawFixture(): Promise<RawFixture> {
  const root = await mkdtemp(join(tmpdir(), "second-brain-surreal-"));
  const dbPath = join(root, "brain.surreal");
  let db: Surreal | undefined;
  try {
    await runPythonFixture(root, dbPath);
    const connected = new Surreal({ engines: createNodeEngines() });
    db = connected;
    await connected.connect(`surrealkv://${dbPath}`);
    await connected.use({ namespace: "brain", database: "brain" });
    return { db: connected, root, dbPath };
  } catch (error) {
    if (db) await db.close().catch(() => undefined);
    await rm(root, { recursive: true, force: true });
    throw error;
  }
}

async function closeRawFixture(fixture: RawFixture): Promise<void> {
  try {
    await fixture.db.close();
  } finally {
    await rm(fixture.root, { recursive: true, force: true });
  }
}

describe("SurrealKV compatibility fixture", () => {
  test("reads Python-produced records, vectors, graph relations, and queue state", async () => {
    const fixture = await openRawFixture();
    try {
      const notes = await statementRows(fixture.db, "SELECT * FROM note");
      const entities = await statementRows(fixture.db, "SELECT * FROM entity");
      const chunks = await statementRows(fixture.db, "SELECT * FROM intake_chunk");
      const keys = await statementRows(fixture.db, "SELECT * FROM intake_key");
      const relations = await statementRows(fixture.db, "SELECT * FROM references");
      const related = await statementRows(fixture.db, "SELECT * FROM relates_to");
      const derived = await statementRows(fixture.db, "SELECT * FROM derived_from");
      const compatibilityNote = notes.find(
        (record) => record.content === "Compatibility note",
      );

      expect(notes).toHaveLength(2);
      expect(compatibilityNote).toMatchObject({
        content: "Compatibility note",
        source: "python",
        embedding: [1, 0, 0],
        dream_age: 0,
      });
      expect(String(compatibilityNote?.id)).toMatch(/^note:/);
      expect(entities[0]).toMatchObject({
        name: "Compatibility entity",
        type: "concept",
        embedding: [0, 1, 0],
        dream_age: 0,
      });
      expect(String(entities[0]?.id)).toMatch(/^entity:/);
      expect(relations).toHaveLength(1);
      expect(String(relations[0]?.in)).toMatch(/^note:/);
      expect(String(relations[0]?.out)).toMatch(/^entity:/);
      expect(String(relations[0]?.id)).toMatch(/^references:/);
      expect(relations[0]).toMatchObject({ dream_age: 0 });
      expect(related).toHaveLength(1);
      expect(String(related[0]?.id)).toMatch(/^relates_to:/);
      expect(derived).toHaveLength(1);
      expect(String(derived[0]?.id)).toMatch(/^derived_from:/);
      expect(chunks[0]).toMatchObject({
        intake_id: "compat-intake",
        chunk_index: 0,
        total_chunks: 1,
        content: "Queued compatibility evidence",
        source: "python",
        hints: ["compatibility"],
        embedding: [0, 0, 1],
        state: "ready",
        attempt_count: 0,
        paused: false,
        idempotency_key: "compat-key",
      });
      expect(keys[0]).toMatchObject({
        intake_id: "compat-intake",
        fingerprint: expect.any(String),
        chunk_count: 1,
      });
    } finally {
      await closeRawFixture(fixture);
    }
  });

  test("retains full-text and HNSW indexes created by Python", async () => {
    const fixture = await openRawFixture();
    try {
      const noteInfo = await statementValue(fixture.db, "INFO FOR TABLE note");
      const entityInfo = await statementValue(fixture.db, "INFO FOR TABLE entity");
      const intakeInfo = await statementValue(
        fixture.db,
        "INFO FOR TABLE intake_chunk",
      );
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
      await closeRawFixture(fixture);
    }
  });

  test("reopens the same Python-produced SurrealKV file with all data intact", async () => {
    const fixture = await openRawFixture();
    const { dbPath, root } = fixture;
    await fixture.db.close();

    const reopened = new Surreal({ engines: createNodeEngines() });
    try {
      await reopened.connect(`surrealkv://${dbPath}`);
      await reopened.use({ namespace: "brain", database: "brain" });
      const notes = await statementRows(reopened, "SELECT * FROM note");
      const relations = await statementRows(reopened, "SELECT * FROM references");
      const related = await statementRows(reopened, "SELECT * FROM relates_to");
      const derived = await statementRows(reopened, "SELECT * FROM derived_from");
      const chunks = await statementRows(reopened, "SELECT * FROM intake_chunk");
      expect(notes.find((record) => record.content === "Compatibility note")).toMatchObject({
        content: "Compatibility note",
        embedding: [1, 0, 0],
      });
      expect(relations).toHaveLength(1);
      expect(related).toHaveLength(1);
      expect(derived).toHaveLength(1);
      expect(chunks[0]).toMatchObject({
        state: "ready",
        embedding: [0, 0, 1],
      });
    } finally {
      await reopened.close();
      await rm(root, { recursive: true, force: true });
    }
  });

  test("requires the storage adapter to normalize existing SDK values at its boundary", async () => {
    const fixture = await openRawFixture();
    await fixture.db.close();
    let storage: Storage | undefined;
    try {
      const options: EmbeddedStorageOptions = {
        dbPath: fixture.dbPath,
        embeddingDimensions: 3,
        embedder: new EmbedderStub((text) =>
          text.includes("Compatibility") ? [1, 0, 0] : [0, 0, 1],
        ),
      };
      storage = createEmbeddedStorage(options);
      await storage.init();
      const nodes = await storage.searchCandidates("Compatibility", 10);
      const note = nodes.nodes.find((candidate) => candidate.id.startsWith("note:"));
      expect(note).toBeDefined();
      const node = await storage.getNode(note!.id);
      expect(node?.id).toMatch(/^note:/);
      expect(JSON.stringify(node)).not.toMatch(/RecordId|datetime|embedding/);
    } finally {
      if (storage) await storage.close();
      await rm(fixture.root, { recursive: true, force: true });
    }
  });
});
