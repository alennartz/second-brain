import { describe, expect, test } from "bun:test";
import { createEmbedder, type EmbeddingProvider } from "../src/embeddings/embedder.ts";

function fixture(provider: EmbeddingProvider) {
  return createEmbedder({ model: "compatible", dimensions: 3, provider });
}
describe("Embedder boundary", () => {
  test("returns the provider vector for one text", async () => {
    const embedder = fixture({ embed: async request => {
      expect(request.texts).toEqual(["source text"]);
      return [[0.25, 0.5, 0.75]];
    } });
    expect(await embedder.embed("source text")).toEqual([0.25, 0.5, 0.75]);
  });
  test("preserves batch order and forwards cancellation", async () => {
    const controller = new AbortController();
    const embedder = fixture({ embed: async request => {
      expect(request.texts).toEqual(["first", "second"]);
      expect(request.signal).toBe(controller.signal);
      return [[1, 0, 0], [0, 1, 0]];
    } });
    expect(await embedder.embedBatch(["first", "second"], controller.signal)).toEqual([[1, 0, 0], [0, 1, 0]]);
  });
  test("does not call the provider after cancellation", async () => {
    const controller = new AbortController();
    controller.abort();
    let calls = 0;
    const embedder = fixture({ embed: async () => { calls++; return [[1, 0, 0]]; } });
    await expect(embedder.embed("cancelled", controller.signal)).rejects.toThrow();
    await expect(embedder.embedBatch(["cancelled"], controller.signal)).rejects.toThrow();
    expect(calls).toBe(0);
  });
  test("returns an empty batch without provider work", async () => {
    const embedder = fixture({ embed: async () => { throw new Error("unexpected call"); } });
    expect(await embedder.embedBatch([])).toEqual([]);
  });
});
