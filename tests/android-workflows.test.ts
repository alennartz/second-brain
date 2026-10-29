import { describe, expect, test } from "bun:test";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHttpServer } from "../src/http/server";
import { HttpApplicationError, type HttpApplication } from "../src/http/contracts";
import { EmbedderStub } from "../src/embeddings/embedder";
import { createEmbeddedStorage } from "../src/storage/embedded";
import type { Storage } from "../src/storage/storage";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { parseSettings } from "../src/core/config";
import { createProductionFactories } from "../src/application/composition";
import { searchMemory } from "../packages/pi-second-brain/lib/graph";

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

async function withStorage<T>(body: (storage: Storage, reopen: () => Promise<Storage>) => Promise<T>): Promise<T> {
  const root = await mkdtemp(join(tmpdir(), "second-brain-android-workflows-"));
  const embedder = new EmbedderStub(() => [1, 0, 0]);
  let storage = createEmbeddedStorage({
    dbPath: join(root, "brain.surreal"),
    embeddingDimensions: 3,
    embedder,
  });
  try {
    await storage.init();
    return await body(storage, async () => {
      await storage.close();
      storage = createEmbeddedStorage({ dbPath: join(root, "brain.surreal"), embeddingDimensions: 3, embedder });
      await storage.init();
      return storage;
    });
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
    search: async () => ({ nodes: [{ id: "entity:garden", name: "Garden" }], unprocessed: [{ id: "intake_chunk:1", content: "Raw garden thought" }] }),
    refreshGraph: async () => ({ results: [{ id: "entity:garden", status: "found", node: { id: "entity:garden", name: "Garden" }, connections: [] }, { id: "entity:deleted", status: "missing" }] }),
    ...overrides,
  };
}

function productionApplication(storage: Storage): HttpApplication {
  const embedder = new EmbedderStub(() => [1, 0, 0]);
  const settings = parseSettings({ BRAIN_INGEST_MODEL: "openai/gpt-4o:off", BRAIN_RECALL_MODEL: "openai/gpt-4o:off", BRAIN_DREAM_MODEL: "openai/gpt-4o:off", BRAIN_DREAM_ENABLED: "false" });
  const modelRuntime = { getModel() { throw new Error("Graph operations must not generate an answer"); } } as unknown as ModelRuntime;
  const factories = createProductionFactories(settings, modelRuntime, embedder, process.cwd(), process.cwd());
  const dependencies = { storage, modelRuntime };
  return factories.createApplication({ ...dependencies, pipeline: factories.createPipeline(dependencies), scheduler: factories.createScheduler(dependencies), dreamJobs: new Map() });
}

function request(path: string, body: unknown, key?: string): Request {
  return new Request(`http://localhost${path}`, {
    method: "POST",
    headers: { "content-type": "application/json", ...(key ? { "idempotency-key": key } : {}) },
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
        return { nodes: [], unprocessed: [] };
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
    const accepted = new Map<string, string>();
    const server = createHttpServer(application({ enqueue: async body => {
      const key = body.idempotency_key!;
      const original = accepted.get(key);
      if (original !== undefined && original !== body.text) throw new HttpApplicationError("conflict", "Idempotency content conflict");
      accepted.set(key, body.text);
      return { chunks_stored: 1 };
    } }));
    const body = {
      text: "same capture",
      source: "mobile",
      hints: [],
      captured_at: "2026-01-01T00:00:00Z",
    };

    const first = await server.handle(request("/ingest", body, "mobile-key"));
    const replay = await server.handle(request("/ingest", body, "mobile-key"));
    const changed = await server.handle(request("/ingest", { ...body, text: "edited capture" }, "mobile-key"));
    expect(replay.status).toBe(200);
    expect(await replay.json()).toEqual({ chunks_stored: 1 });

    expect(first.status).toBe(200);
    expect(await first.json()).toEqual({ chunks_stored: 1 });
    expect(changed.status).toBe(409);
    expect((await changed.json()).detail).toEqual(expect.any(String));
  });
});

describe("Android workflow application graph operations", () => {
  test("production search rejects whitespace-only queries as invalid input", async () => {
    await withStorage(async storage => {
      const server = createHttpServer(productionApplication(storage));
      for (const query of ["   ", "\t\n", "\u00a0"]) {
        const response = await server.handle(request("/search", { query }));
        expect(response.status).toBe(400);
      }
    });
  });
  test("direct HTTP search matches agent-facing hybrid search without a model", async () => {
    await withStorage(async storage => {
      await storage.createNode({ kind: "entity", name: "Garden", type: "place", description: "Garden behind shed" });
      await storage.createIntakeChunks("raw", chunks);
      const app = productionApplication(storage);
      const expected = await searchMemory(storage, { query: "garden", limit: 20 });
      expect(expected.nodes.length).toBeGreaterThan(0);
      const response = await createHttpServer(app).handle(request("/search", { query: "garden", limit: 20 }));
      expect(response.status).toBe(200);
      expect(await response.json()).toEqual(expected);
    });
  });
  test("production refresh returns the existing graph projection and confirmed missing records", async () => {
    await withStorage(async storage => {
      const node = await storage.createNode({ kind: "entity", name: "Garden", type: "place" });
      const app = productionApplication(storage);
      const graph = await app.getGraph(node.id);
      if (!graph) throw new Error("Fixture node is missing");
      expect(await app.refreshGraph([node.id, "entity:absent"])).toEqual({ results: [{ id: node.id, status: "found", ...graph }, { id: "entity:absent", status: "missing" }] });
    });
  });
});

describe("Android workflow validation and failures", () => {
  for (const body of [{ query: "" }, { query: "x", limit: 0 }, { query: "x", limit: 101 }, { query: "x", limit: 1.5 }]) {
    test(`rejects invalid search ${JSON.stringify(body)}`, async () => {
      const response = await createHttpServer(application()).handle(request("/search", body));
      expect(response.status).toBe(400);
    });
  }
  test("accepts search limits at both bounds and omitted limit", async () => {
    for (const body of [{ query: "x", limit: 1 }, { query: "x", limit: 100 }, { query: "x" }]) {
      expect((await createHttpServer(application()).handle(request("/search", body))).status).toBe(200);
    }
  });
  test("bounds expanded node refresh to 200 IDs", async () => {
    const server = createHttpServer(application({ refreshGraph: async ids => ({ results: ids.map(id => ({ id, status: "missing" as const })) }) }));
    expect((await server.handle(request("/graph/refresh", { ids: Array.from({ length: 200 }, (_, i) => `entity:${i}`) }))).status).toBe(200);
    expect((await server.handle(request("/graph/refresh", { ids: Array.from({ length: 201 }, (_, i) => `entity:${i}`) }))).status).toBe(400);
  });
  for (const path of ["/search", "/graph/refresh"]) {
    test(`${path} transport failure never fabricates missing results`, async () => {
      const fail = async (): Promise<never> => { throw new Error("offline"); };
      const response = await createHttpServer(application({ search: fail, refreshGraph: fail })).handle(request(path, path === "/search" ? { query: "x" } : { ids: ["entity:x"] }));
      expect(response.status).toBe(503);
      expect((await response.json()).detail).toEqual(expect.any(String));
    });
  }
});

describe("Android workflow intake-key persistence", () => {
  test("keeps an accepted key after cleanup and rejects changed replays", async () => {
    await withStorage(async (initial, reopen) => {
      let storage = initial;
      expect(await storage.createIntakeChunks("capture-1", chunks, "mobile-key")).toBe(1);
      const batch = await storage.claimIntakeBatch("worker", 1000, 60);
      expect(batch).toBeDefined();
      expect(await storage.deleteIntakeBatch(batch!.lease_token)).toBe(1);
      storage = await reopen();

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
