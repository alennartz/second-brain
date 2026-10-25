import { describe, expect, test } from "bun:test";
import { EmbedderStub, type Embedder } from "../src/embeddings/embedder.ts";

describe("Embedder contract", () => {
  test("returns one vector for one text", async () => {
    const embedder: Embedder = new EmbedderStub();

    await expect(embedder.embed("remember this source text")).resolves.toEqual([
      0.1,
      0.2,
      0.3,
    ]);
  });

  test("returns one vector per input in batch order", async () => {
    const embedder: Embedder = new EmbedderStub();

    await expect(embedder.embedBatch(["first", "second"])).resolves.toEqual([
      [0.1, 0.2],
      [0.3, 0.4],
    ]);
  });

  test("accepts an abort signal on single and batch requests", async () => {
    const embedder: Embedder = new EmbedderStub();
    const controller = new AbortController();

    await expect(embedder.embed("cancel-aware", controller.signal)).resolves.toEqual([
      0.1,
    ]);
    await expect(embedder.embedBatch([], controller.signal)).resolves.toEqual([]);
  });
});
