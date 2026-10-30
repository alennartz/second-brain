import { describe, expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  EmbedderStub,
  type EmbedderResolver,
} from "../src/embeddings/embedder.ts";
import {
  createEmbeddedStorage,
  type EmbeddedStorageOptions,
} from "../src/storage/embedded.ts";
import type { Storage } from "../src/storage/storage.ts";

const note = (content: string, source = "api") => ({
  kind: "note" as const,
  content,
  source,
});

const entity = (name: string) => ({
  kind: "entity" as const,
  name,
  type: "person",
});

function vectorsFor(text: string): readonly number[] {
  if (text === "alpha") return [1, 0, 0];
  if (text.includes("semantic")) return [1, 0, 0];
  if (text.includes("lexical")) return [0, 1, 0];
  if (text.includes("Ada")) return [1, 0, 0];
  if (text.includes("Grace")) return [0.8, 0.6, 0];
  return [0, 0, 1];
}

type StorageFixture = {
  storage: Storage;
  embedder: EmbedderStub;
  root: string;
};

async function withStorage<T>(
  body: (fixture: StorageFixture) => Promise<T>,
  resolve: EmbedderResolver = (text) => vectorsFor(text),
  clock?: () => Date,
): Promise<T> {
  const root = await mkdtemp(join(tmpdir(), "second-brain-storage-"));
  const embedder = new EmbedderStub(resolve);
  const options: EmbeddedStorageOptions = {
    dbPath: join(root, "brain.surreal"),
    embeddingDimensions: 3,
    embedder,
    ...(clock ? { clock } : {}),
  };
  let storage: Storage | undefined;
  try {
    storage = createEmbeddedStorage(options);
    await storage.init();
    return await body({ storage, embedder, root });
  } finally {
    if (storage) await storage.close();
    await rm(root, { recursive: true, force: true });
  }
}

describe("Storage graph boundary", () => {
  test("opens and closes an isolated database without leaking its driver", async () => {
    await withStorage(async ({ storage }) => {
      expect(storage).toHaveProperty("createNode");
      expect(storage).not.toHaveProperty("query");
    });
  });

  test("persists independent note and entity records with canonical IDs", async () => {
    await withStorage(async ({ storage }) => {
      const createdNote = await storage.createNode(note("Ada writes programs"));
      const createdEntity = await storage.createNode(entity("Ada"));

      expect(createdNote.id).toMatch(/^note:/);
      expect(createdEntity.id).toMatch(/^entity:/);
      expect(createdNote.id).not.toBe(createdEntity.id);
      expect(createdNote).toMatchObject({
        kind: "note",
        content: "Ada writes programs",
        source: "api",
      });
      expect(createdEntity).toMatchObject({
        kind: "entity",
        name: "Ada",
        type: "person",
      });
      expect(await storage.getNode(createdNote.id)).toEqual(createdNote);
      expect(await storage.getNode(createdEntity.id)).toEqual(createdEntity);
      expect(JSON.stringify(createdNote)).not.toMatch(/embedding|RecordID|datetime/);
    });
  });

  test("updates fields without replacing unrelated state and re-embeds searchable text", async () => {
    await withStorage(async ({ storage, embedder }) => {
      const created = await storage.createNode(note("Original text", "cli"));
      const callsBeforeSummary = embedder.calls.length;

      const withSummary = await storage.updateNodeFields(created.id, {
        summary: "Short summary",
      });
      expect(withSummary).toMatchObject({
        id: created.id,
        content: "Original text",
        source: "cli",
        summary: "Short summary",
      });
      expect(embedder.calls.length).toBe(callsBeforeSummary);

      const callsBeforeContent = embedder.calls.length;
      const updated = await storage.updateNodeFields(created.id, {
        content: "Updated text",
      });
      expect(updated).toMatchObject({
        id: created.id,
        content: "Updated text",
        summary: "Short summary",
      });
      expect(embedder.calls.length).toBe(callsBeforeContent + 1);
      expect(embedder.calls.at(-1)?.text).toBe("Updated text");
    });
  });

  test("re-embeds entity name or description changes", async () => {
    await withStorage(async ({ storage, embedder }) => {
      const created = await storage.createNode({
        kind: "entity",
        name: "Ada",
        type: "person",
      });
      const afterCreate = embedder.calls.length;
      await storage.updateNodeFields(created.id, { name: "Grace" });
      await storage.updateNodeFields(created.id, { description: "New description" });
      expect(embedder.calls.slice(afterCreate).map((call) => call.text)).toEqual([
        "Grace",
        "New description",
      ]);
    });
  });

  test("rolls back a failed re-embedding call and preserves the prior record", async () => {
    let fail = false;
    await withStorage(
      async ({ storage }) => {
        const created = await storage.createNode(note("Stable text"));
        fail = true;

        await expect(
          storage.updateNodeFields(created.id, { content: "Rejected text" }),
        ).rejects.toThrow("embedding unavailable");
        expect(await storage.getNode(created.id)).toEqual(created);
      },
      (text) => {
        if (fail && text === "Rejected text") throw new Error("embedding unavailable");
        return vectorsFor(text);
      },
    );
  });

  test("deletes one node without fabricating a missing record", async () => {
    await withStorage(async ({ storage }) => {
      const created = await storage.createNode(note("To remove"));
      await storage.deleteNode(created.id);
      expect(await storage.getNode(created.id)).toBeUndefined();
      await expect(storage.deleteNode(created.id)).resolves.toBeUndefined();
    });
  });

  test("persists directed relations and exposes both traversal directions", async () => {
    await withStorage(async ({ storage }) => {
      const from = await storage.createNode(note("Source"));
      const to = await storage.createNode(entity("Target"));
      const edge = await storage.createEdge({
        fromId: from.id,
        edgeType: "references",
        toId: to.id,
        context: "The source names the target",
      });

      expect(edge.id).toMatch(/^references:/);
      expect(edge).toMatchObject({
        from: from.id,
        to: to.id,
        edgeType: "references",
        context: "The source names the target",
      });
      expect(await storage.getEdge(edge.id)).toEqual(edge);
      expect(await storage.getOutgoingEdges(from.id)).toContainEqual(edge);
      expect(await storage.getIncomingEdges(to.id)).toContainEqual(edge);
      expect(await storage.findEdges(from.id, "references", to.id)).toContainEqual(edge);

      await storage.deleteEdge(edge.id);
      expect(await storage.getEdge(edge.id)).toBeUndefined();
      expect(await storage.getNode(from.id)).toEqual(from);
      expect(await storage.getNode(to.id)).toEqual(to);
    });
  });

  test("fuses lexical and vector candidates into bounded public search results", async () => {
    await withStorage(async ({ storage, embedder }) => {
      const lexical = await storage.createNode(note("alpha lexical evidence"));
      const semantic = await storage.createNode(note("semantic only evidence"));
      await storage.createNode(note("unrelated evidence"));

      const callsBeforeSearch = embedder.calls.length;
      const result = await storage.searchCandidates("alpha", 2);
      const ids = result.nodes.map((candidate) => candidate.id);
      expect(ids).toEqual(expect.arrayContaining([lexical.id, semantic.id]));
      expect(result.nodes.length).toBeLessThanOrEqual(2);
      expect(embedder.calls.slice(callsBeforeSearch).map((call) => call.text)).toEqual(["alpha"]);
      expect(result.unprocessed).toEqual([]);
      expect(JSON.stringify(result)).not.toMatch(/embedding|lease_token|lease_expires/);
    });
  });

  test("returns queued evidence separately from graph candidates", async () => {
    await withStorage(async ({ storage }) => {
      const graphNode = await storage.createNode(note("Ada graph evidence"));
      await storage.createIntakeChunks("capture-search", [
        {
          chunk_index: 0,
          total_chunks: 1,
          content: "Ada queued evidence",
          source: "api",
          hints: ["queued"],
        },
      ]);

      const result = await storage.searchCandidates("Ada", 10);
      expect(result.nodes.map((candidate) => candidate.id)).toContain(graphNode.id);
      expect(result.unprocessed).toContainEqual(
        expect.objectContaining({
          intake_id: "capture-search",
          content: "Ada queued evidence",
          captured_at: expect.any(String),
        }),
      );
      expect(JSON.stringify(result.unprocessed)).not.toMatch(
        /embedding|lease_token|lease_expires|attempt_count/,
      );
    });
  });

  test("returns similar candidates without returning the source or vectors", async () => {
    await withStorage(async ({ storage }) => {
      const source = await storage.createNode(entity("Ada"));
      const nearest = await storage.createNode(entity("Grace"));
      await storage.createNode(note("unrelated evidence"));

      const result = await storage.findSimilarCandidates(source.id, 2);
      expect(result.map((candidate) => candidate.id)).not.toContain(source.id);
      expect(result.map((candidate) => candidate.id)).toContain(nearest.id);
      expect(JSON.stringify(result)).not.toMatch(/embedding/);
    });
  });

  test("uses lexical and vector evidence within the source node kind", async () => {
    await withStorage(
      async ({ storage }) => {
        const source = await storage.createNode({
          kind: "entity",
          name: "Astra",
          type: "model",
          description: "A model with an older description",
        });
        const exactName = await storage.createNode({
          kind: "entity",
          name: "Astra",
          type: "model",
          description: "A completely different description",
        });
        const misleadingNote = await storage.createNode(
          note("Astra is mentioned in unrelated evidence"),
        );

        const result = await storage.findSimilarCandidates(source.id, 1);
        expect(result.map((candidate) => candidate.id)).toEqual([exactName.id]);
        expect(result.map((candidate) => candidate.id)).not.toContain(
          misleadingNote.id,
        );
      },
      (text) => {
        if (text.includes("older description")) return [1, 0, 0];
        if (text.includes("completely different")) return [0, 1, 0];
        return [0, 0, 1];
      },
    );
  });
});

describe("Storage intake boundary", () => {
  const chunks = [
    {
      chunk_index: 0,
      total_chunks: 2,
      content: "Ada wrote the first program.",
      source: "api",
      hints: ["history"],
      captured_at: "2026-01-01T00:00:00+02:00",
    },
    {
      chunk_index: 1,
      total_chunks: 2,
      content: "Grace reviewed the second program.",
      source: "api",
      hints: ["history"],
      captured_at: "2026-01-01T00:00:00+02:00",
    },
  ] as const;

  test("stages searchable chunks, leases them contiguously, then acknowledges them", async () => {
    await withStorage(async ({ storage }) => {
      expect(await storage.createIntakeChunks("capture-1", chunks, "retry-1")).toBe(2);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(2);

      const batch = await storage.claimIntakeBatch("worker-1", 10_000, 300);
      expect(batch).toBeDefined();
      expect(batch?.intake_id).toBe("capture-1");
      expect(batch?.chunks.map((chunk) => chunk.chunk_index)).toEqual([0, 1]);
      expect(batch?.chunks.every((chunk) => chunk.state === "leased")).toBe(true);
      expect(batch?.chunks.every((chunk) => chunk.lease_token === batch.lease_token)).toBe(true);
      expect(batch?.chunks.map(chunk => chunk.captured_at)).toEqual(["2026-01-01T00:00:00+02:00", "2026-01-01T00:00:00+02:00"]);

      expect(await storage.renewIntakeBatch(batch!.lease_token, 300)).toBe(2);
      expect((await storage.intakeQueueSnapshot()).leased).toBe(2);
      await storage.releaseIntakeBatch(
        batch!.lease_token,
        "temporary failure",
        "1970-01-01T00:00:00.000Z",
      );
      expect((await storage.intakeQueueSnapshot()).retry_wait).toBe(2);
      expect((await storage.intakeQueueSnapshot()).recent_errors).toEqual([
        expect.objectContaining({ intake_id: "capture-1", error: "temporary failure" }),
      ]);

      const retry = await storage.claimIntakeBatch("worker-1", 10_000, 300);
      expect(retry?.chunks.map((chunk) => chunk.chunk_index)).toEqual([0, 1]);
      expect(await storage.deleteIntakeBatch(retry!.lease_token)).toBe(2);
      expect(await storage.getIntakeChunks([batch!.chunks[0]!.id])).toEqual([]);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(0);
      expect((await storage.intakeQueueSnapshot()).leased).toBe(0);
      expect((await storage.intakeQueueSnapshot()).retry_wait).toBe(0);
      expect(await storage.createIntakeChunks("capture-replay", chunks, "retry-1")).toBe(2);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(0);
      expect(await storage.searchIntakeChunks("program", 10)).toEqual([]);
    });
  });

  test("reclaims expired leases and rejects stale ownership operations", async () => {
    let now = new Date("2026-01-01T00:00:00.000Z");
    await withStorage(
      async ({ storage }) => {
        await storage.createIntakeChunks("capture-expiry", [chunks[0]!]);
        const first = await storage.claimIntakeBatch("worker-old", 10_000, 60);
        expect(first).toBeDefined();

        now = new Date("2026-01-01T00:01:01.000Z");
        const reclaimed = await storage.claimIntakeBatch("worker-new", 10_000, 60);
        expect(reclaimed).toBeDefined();
        expect(reclaimed?.lease_token).not.toBe(first?.lease_token);
        expect(reclaimed?.chunks[0]?.lease_token).toBe(reclaimed?.lease_token);

        expect(await storage.renewIntakeBatch(first!.lease_token, 60)).toBe(0);
        expect(await storage.deleteIntakeBatch(first!.lease_token)).toBe(0);
        await storage.releaseIntakeBatch(
          first!.lease_token,
          "stale worker failure",
          "2026-01-01T00:00:00.000Z",
        );
        expect((await storage.intakeQueueSnapshot()).leased).toBe(1);
        expect((await storage.intakeQueueSnapshot()).retry_wait).toBe(0);
        expect((await storage.intakeQueueSnapshot()).recent_errors).toEqual([]);

        expect(await storage.deleteIntakeBatch(reclaimed!.lease_token)).toBe(1);
        expect((await storage.intakeQueueSnapshot()).leased).toBe(0);
      },
      (text) => vectorsFor(text),
      () => now,
    );
  });

  test("enforces idempotent replay by content fingerprint", async () => {
    await withStorage(async ({ storage, embedder }) => {
      const first = await storage.createIntakeChunks("capture-2", [chunks[0]!], "mobile-retry");
      const callsAfterFirst = embedder.calls.length;
      const replay = await storage.createIntakeChunks("capture-2", [chunks[0]!], "mobile-retry");
      expect(first).toBe(1);
      expect(replay).toBe(1);
      expect(embedder.calls.length).toBe(callsAfterFirst);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(1);

      const changed = { ...chunks[0]!, content: "Different source content." };
      await expect(
        storage.createIntakeChunks("capture-2", [changed], "mobile-retry"),
      ).rejects.toThrow();
      const changedCapture = { ...chunks[0]!, captured_at: "2026-01-02T00:00:00Z" };
      await expect(
        storage.createIntakeChunks("capture-2", [changedCapture], "mobile-retry"),
      ).rejects.toThrow();
      expect(await storage.searchIntakeChunks("Ada", 10)).toHaveLength(1);
    });
  });

  test("does not leave partial queue rows when batch embedding fails", async () => {
    await withStorage(
      async ({ storage }) => {
        await expect(
          storage.createIntakeChunks("capture-3", chunks, "failed-batch"),
        ).rejects.toThrow("batch embedding failed");
        expect(await storage.searchIntakeChunks("program", 10)).toEqual([]);
        expect((await storage.intakeQueueSnapshot()).ready).toBe(0);
        expect(await storage.createIntakeChunks("capture-recovery", [{ chunk_index: 0, total_chunks: 1, content: "Recovery", source: "api", hints: [], captured_at: "2026-01-01T00:00:00Z" }], "failed-batch")).toBe(1);
      },
      (text) => {
        if (text.includes("Grace")) throw new Error("batch embedding failed");
        return vectorsFor(text);
      },
    );
  });

  test("pauses, resumes, and discards only the selected intake", async () => {
    await withStorage(async ({ storage }) => {
      await storage.createIntakeChunks("capture-a", [chunks[0]!]);
      await storage.createIntakeChunks("capture-b", [chunks[1]!]);

      expect(await storage.setIntakePaused("capture-a", true)).toBe(1);
      expect((await storage.intakeQueueSnapshot()).paused).toBe(1);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(1);
      expect(await storage.setIntakePaused("capture-a", false)).toBe(1);
      expect((await storage.intakeQueueSnapshot()).paused).toBe(0);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(2);

      expect(await storage.deleteIntake("capture-a")).toBe(1);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(1);
      expect(await storage.deleteIntake("capture-b")).toBe(1);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(0);
    });
  });
});

describe("Storage transaction boundary", () => {
  test("enumerates edge types inside and outside an atomic graph transaction", async () => {
    await withStorage(async ({ storage }) => {
      const a = await storage.createNode(entity("Ada"));
      const b = await storage.createNode(entity("Grace"));
      const edge = await storage.createEdge({ fromId: a.id, edgeType: "references", toId: b.id });
      await storage.createEdge({ fromId: a.id, edgeType: "relates_to", toId: b.id });
      expect(await storage.getEdgesByType("references")).toEqual([edge]);
      expect(await storage.getEdgesByType("missing_type")).toEqual([]);
      await storage.withTransaction(async tx => {
        expect(await tx.getEdgesByType("references")).toEqual([edge]);
        await tx.deleteEdge(edge.id);
      });
      expect(await storage.getEdgesByType("references")).toEqual([]);
    });
  });
  test("returns normalized unlinked cooccurrence candidates and excludes linked pairs", async () => {
    await withStorage(async ({ storage }) => {
      const a = await storage.createNode(entity("Ada"));
      const b = await storage.createNode(entity("Grace"));
      const source = await storage.createNode(note("Ada met Grace"));
      await storage.createEdge({ fromId: source.id, edgeType: "references", toId: a.id });
      await storage.createEdge({ fromId: source.id, edgeType: "references", toId: b.id });
      const candidates = await storage.findUnlinkedCooccurrenceCandidates(1);
      expect(candidates).toHaveLength(1);
      expect([candidates[0]!.fromId, candidates[0]!.toId].sort()).toEqual([a.id, b.id].sort());
      expect(candidates[0]!.sharedNoteIds).toEqual([source.id]);
      expect(JSON.stringify(candidates)).not.toMatch(/embedding|lease_token|RecordId/);
      await storage.createEdge({ fromId: a.id, edgeType: "relates_to", toId: b.id });
      expect(await storage.findUnlinkedCooccurrenceCandidates(1)).toEqual([]);
    });
  });
  test("commits a composite graph mutation as one domain transaction", async () => {
    await withStorage(async ({ storage }) => {
      const result = await storage.withTransaction(async (transaction) => {
        const from = await transaction.createNode(note("Transaction source"));
        const to = await transaction.createNode(entity("Transaction target"));
        const edge = await transaction.createEdge({
          fromId: from.id,
          edgeType: "references",
          toId: to.id,
        });
        return { from, to, edge };
      });

      expect(await storage.getNode(result.from.id)).toEqual(result.from);
      expect(await storage.getNode(result.to.id)).toEqual(result.to);
      expect(await storage.getEdge(result.edge.id)).toEqual(result.edge);
    });
  });

  test("rolls back staged intake rows when a composite callback rejects", async () => {
    await withStorage(async ({ storage }) => {
      await expect(
        storage.withTransaction(async (transaction) => {
          await transaction.createIntakeChunks("transaction-intake", [
            {
              chunk_index: 0,
              total_chunks: 1,
              content: "Transaction evidence",
              source: "api",
              hints: [],
            },
          ]);
          throw new Error("intake transaction failed");
        }),
      ).rejects.toThrow("intake transaction failed");
      expect(await storage.searchIntakeChunks("Transaction", 10)).toEqual([]);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(0);
    });
  });

  test("rolls back every graph mutation when a composite callback rejects", async () => {
    let attemptedNodeId: string | undefined;
    await withStorage(async ({ storage }) => {
      await expect(
        storage.withTransaction(async (transaction) => {
          const from = await transaction.createNode(note("Rolled back source"));
          attemptedNodeId = from.id;
          const to = await transaction.createNode(entity("Rolled back target"));
          await transaction.createEdge({
            fromId: from.id,
            edgeType: "references",
            toId: to.id,
          });
          throw new Error("composite mutation failed");
        }),
      ).rejects.toThrow("composite mutation failed");

      expect(attemptedNodeId).toBeDefined();
      expect(await storage.getNode(attemptedNodeId!)).toBeUndefined();
      expect((await storage.searchCandidates("Rolled back", 10)).nodes).toEqual([]);
    });
  });

  test("keeps an earlier committed call after a later transaction failure", async () => {
    await withStorage(async ({ storage }) => {
      const committed = await storage.createNode(note("Already committed"));
      await expect(
        storage.withTransaction(async (transaction) => {
          await transaction.createNode(note("Transient write"));
          throw new Error("later failure");
        }),
      ).rejects.toThrow("later failure");
      expect(await storage.getNode(committed.id)).toEqual(committed);
      expect((await storage.searchCandidates("Transient write", 10)).nodes.some(node => node.content === "Transient write")).toBe(false);
    });
  });
});
