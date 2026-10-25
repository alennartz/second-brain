import OpenAI from "openai";
import type { EmbeddingProvider } from "./embedder.ts";

export function createOpenAIEmbeddingProvider(client: OpenAI): EmbeddingProvider {
  return {
    async embed({ model, dimensions, texts, signal }) {
      const response = await client.embeddings.create({ model: model.replace(/^openai:/, ""), dimensions, input: [...texts] }, { signal });
      return [...response.data].sort((a, b) => a.index - b.index).map(item => item.embedding);
    },
  };
}
