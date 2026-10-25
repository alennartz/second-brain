import { describe, expect, test } from "bun:test";
import { EmbedderStub } from "../src/embeddings/embedder.ts";
import { createEmbeddedStorage, type EmbeddedStorageOptions } from "../src/storage/embedded.ts";
import type { Storage } from "../src/storage/storage.ts";

describe("embedded SurrealDB storage seam", () => {
  test("opens the configured surrealkv database through the domain storage contract", async () => {
    const options: EmbeddedStorageOptions = {
      dbPath: "data/test-brain.surreal",
      embeddingDimensions: 3,
      embedder: new EmbedderStub(),
    };
    const storage: Storage = createEmbeddedStorage(options);

    await expect(storage.init()).resolves.toBeUndefined();
    await expect(storage.close()).resolves.toBeUndefined();
  });

  test("normalizes embedded record values before returning domain records", async () => {
    const storage = createEmbeddedStorage({
      dbPath: "data/test-brain.surreal",
      embeddingDimensions: 3,
      embedder: new EmbedderStub(),
    });
    const node = await storage.createNode({ kind: "note", content: "plain value" });

    expect(node.id).toBe("note:1");
    expect(typeof node.id).toBe("string");
    expect(JSON.stringify(node)).not.toMatch(/RecordID|datetime|embedding/);
  });
});
