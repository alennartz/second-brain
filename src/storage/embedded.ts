import type { Embedder } from "../embeddings/embedder.ts";
import type { Storage } from "./storage.ts";

export interface EmbeddedStorageOptions {
  dbPath: string;
  embeddingDimensions: number;
  embedder: Embedder;
}

/**
 * Public seam for the Bun-native SurrealDB storage adapter.
 *
 * The implementation owns `surrealkv://` setup and SDK normalization. It must
 * not expose SurrealDB values through the `Storage` interface.
 */
export function createEmbeddedStorage(_options: EmbeddedStorageOptions): Storage {
  throw new Error("not implemented");
}
