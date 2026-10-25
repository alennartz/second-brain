import { expect, test } from "bun:test";
import { createEmbedder } from "../src/embeddings/embedder";

test("embedding adapter selects the configured model and dimensions independently of workflow models", async () => {
  const signal = new AbortController().signal;
  const embedder = createEmbedder({ model: "text-embedding-compatible", dimensions: 3, provider: { embed: async request => {
    expect(request).toEqual({ model: "text-embedding-compatible", dimensions: 3, texts: ["one", "two"], signal });
    return [[1, 0, 0], [0, 1, 0]];
  } } });
  expect(await embedder.embedBatch(["one", "two"], signal)).toEqual([[1, 0, 0], [0, 1, 0]]);
});

test.each([{ vectors: [] }, { vectors: [[1, 0]] }, { vectors: [[1, 0, Number.NaN]] }, { vectors: [[1, 0, 0], [0, 1, 0]] }])("rejects invalid provider vectors %j", async ({ vectors }) => {
  const embedder = createEmbedder({ model: "compatible", dimensions: 3, provider: { embed: async () => vectors } });
  await expect(embedder.embed("one")).rejects.toThrow();
});

test("propagates provider failures instead of substituting incompatible vectors", async () => {
  const embedder = createEmbedder({ model: "compatible", dimensions: 3, provider: { embed: async () => { throw new Error("provider unavailable"); } } });
  await expect(embedder.embed("one")).rejects.toThrow();
});
