import { describe, expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHttpServer } from "../src/http/server";
import type { HttpApplication } from "../src/http/contracts";
import { EmbedderStub } from "../src/embeddings/embedder";
import { createEmbeddedStorage } from "../src/storage/embedded";
import type { Storage } from "../src/storage/storage";

const chunks = [
  {
    chunk_index: 0,
    total_chunks: 1,
    content: "An offline capture that was already accepted.",
    source: "mobile",
    hints: ["offline"],
    captured_at: "2026-01-01T00:00:00Z",
  },
] as const;

async function withStorage<T>(body: (storage: Storage) => Promise<T>): Promise<T> {
  const root = await mkdtemp(join(tmpdir(), "second-brain-android-workflows-"));
  const embedder = new EmbedderStub(() => [1, 0, 0]);
  const storage = createEmbeddedStorage({
    dbPath: join(root, "brain.surreal"),
    embeddingDimensions: 3,
    embedder,
  });
  try {
    await storage.init();
    return await body(storage);
  } finally {
    await storage.close();
    await rm(root, { recursive: true, force: true });
  }
}

function application(overrides: Partial<HttpApplication> = {}): HttpApplication {
  return {
    enqueue: async () => ({ chunks_stored: 1 }),
    pipelineSnapshot: async () => ({
      ready: 0,
      leased: 0,
      retry_wait: 0,
      paused: 0,
      oldest_ready_at: null,
      oldest_retry_at: null,
      worker_count: 0,
      active_leases: 0,
      stuck_intakes: [],
      recent_errors: [],
    }),
    pause: async () => 0,
    resume: async () => 0,
    discard: async () => 0,
    startDream: async () => ({ job_id: "job", status: "pending", error: null }),
    getDreamJob: async () => undefined,
    recall: async () => ({ answer: "", context: null }),
    getGraph: async () => undefined,
    search: async () => { throw new Error("not implemented"); },
    refreshGraph: async () => { throw new Error("not implemented"); },
    ...overrides,
  };
}

function request(path: string, body: unknown): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body),
  });
}

describe("Android workflow server boundary", () => {
  test("search returns graph nodes separately from unprocessed chunks", async () => {
    const server = createHttpServer(application());

    const response = await server.handle(request("/search", { query: "garden", limit: 20 }));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      nodes: [{ id: "entity:garden", name: "Garden" }],
      unprocessed: [{ id: "intake_chunk:1", content: "Raw garden thought" }],
    });
  });

  test("search accepts a bounded query and forwards the optional limit", async () => {
    const seen: unknown[] = [];
    const server = createHttpServer(application({
      search: async requestBody => {
        seen.push(requestBody);
        throw new Error("not implemented");
      },
    }));

    const response = await server.handle(request("/search", { query: "garden", limit: 3 }));

    expect(response.status).toBe(200);
    expect(seen).toEqual([{ query: "garden", limit: 3 }]);
  });

  test("graph refresh returns found details and confirmed missing records in input order", async () => {
    const server = createHttpServer(application());

    const response = await server.handle(request("/graph/refresh", {
      ids: ["entity:garden", "entity:deleted"],
    }));

    expect(response.status).toBe(200);
    expect(await response.json()).toEqual({
      results: [
        {
          id: "entity:garden",
          status: "found",
          node: { id: "entity:garden", name: "Garden" },
          connections: [],
        },
        { id: "entity:deleted", status: "missing" },
      ],
    });
  });

  test("ingest returns 200 for a replay and 409 for a changed payload", async () => {
    const server = createHttpServer(application());
    const body = {
      text: "same capture",
      source: "mobile",
      hints: [],
      captured_at: "2026-01-01T00:00:00Z",
    };

    const first = await server.handle(request("/ingest", body));
    const changed = await server.handle(request("/ingest", { ...body, text: "edited capture" }));

    expect(first.status).toBe(200);
    expect(await first.json()).toEqual({ chunks_stored: 1 });
    expect(changed.status).toBe(409);
    expect(await changed.json()).toEqual({ detail: "Idempotency content conflict" });
  });
});

describe("Android workflow intake-key persistence", () => {
  test("keeps an accepted key after cleanup and rejects changed replays", async () => {
    await withStorage(async storage => {
      expect(await storage.createIntakeChunks("capture-1", chunks, "mobile-key")).toBe(1);
      const batch = await storage.claimIntakeBatch("worker", 1000, 60);
      expect(batch).toBeDefined();
      expect(await storage.deleteIntakeBatch(batch!.lease_token)).toBe(1);

      expect(await storage.createIntakeChunks("capture-replay", chunks, "mobile-key")).toBe(1);
      expect((await storage.intakeQueueSnapshot()).ready).toBe(0);
      await expect(
        storage.createIntakeChunks(
          "capture-edited",
          [{ ...chunks[0]!, content: "An edited capture." }],
          "mobile-key",
        ),
      ).rejects.toThrow(/idempotency/i);
    });
  });
});
