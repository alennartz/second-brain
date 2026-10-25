import { describe, expect, test } from "bun:test";
import { StorageStub, type Storage } from "../src/storage/storage.ts";
import type {
  EdgeRecord,
  MemorySearchResult,
  NewEdge,
  NewNode,
  NodeRecord,
} from "../src/core/types.ts";

describe("Storage contract", () => {
  test("initializes and closes without exposing the database driver", async () => {
    const storage: Storage = new StorageStub();

    await expect(storage.init()).resolves.toBeUndefined();
    await expect(storage.close()).resolves.toBeUndefined();
  });

  test("creates and retrieves a note through domain records", async () => {
    const storage: Storage = new StorageStub();
    const input: NewNode = {
      kind: "note",
      content: "A note stored in the graph",
      source: "api",
      summary: "A summary",
    };
    const expected: NodeRecord = {
      id: "note:1",
      table: "note",
      kind: "note",
      content: input.content,
      source: input.source,
      summary: input.summary,
    };

    await expect(storage.createNode(input)).resolves.toEqual(expected);
    await expect(storage.getNode(expected.id)).resolves.toEqual(expected);
  });

  test("creates and lists canonical graph edges", async () => {
    const storage: Storage = new StorageStub();
    const input: NewEdge = {
      fromId: "note:1",
      edgeType: "references",
      toId: "entity:1",
      context: "The note names the entity",
    };
    const expected: EdgeRecord = {
      id: "references:1",
      from: input.fromId,
      to: input.toId,
      edgeType: input.edgeType,
      context: input.context,
    };

    await expect(storage.createEdge(input)).resolves.toEqual(expected);
    await expect(storage.getOutgoingEdges(input.fromId)).resolves.toEqual([expected]);
    await expect(storage.getIncomingEdges(input.toId)).resolves.toEqual([expected]);
  });

  test("returns separate graph and unprocessed evidence from search", async () => {
    const storage: Storage = new StorageStub();
    const expected: MemorySearchResult = {
      nodes: [{ id: "note:1", table: "note", content: "matching note" }],
      unprocessed: [
        {
          id: "intake_chunk:1",
          intake_id: "intake-1",
          chunk_index: 0,
          total_chunks: 1,
          content: "raw matching evidence",
          source: "api",
          hints: [],
        },
      ],
    };

    await expect(storage.searchCandidates("matching", 5)).resolves.toEqual(expected);
  });

  test("claims, renews, releases, and acknowledges an intake batch", async () => {
    const storage: Storage = new StorageStub();

    await expect(storage.claimIntakeBatch("worker-1", 4_000, 300)).resolves.toEqual({
      lease_token: "lease-1",
      intake_id: "intake-1",
      chunks: [],
    });
    await expect(storage.renewIntakeBatch("lease-1", 300)).resolves.toBe(1);
    await expect(storage.releaseIntakeBatch("lease-1", "retry later")).resolves.toBeUndefined();
    await expect(storage.deleteIntakeBatch("lease-1")).resolves.toBe(1);
  });

  test("reports queue state without raw SurrealDB values", async () => {
    const storage: Storage = new StorageStub();

    await expect(storage.intakeQueueSnapshot()).resolves.toEqual({
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
    });
  });
});
