export interface Embedder {
  embed(text: string, signal?: AbortSignal): Promise<readonly number[]>;
  embedBatch(
    texts: readonly string[],
    signal?: AbortSignal,
  ): Promise<readonly (readonly number[])[]>;
}

export type EmbeddingProvider = {
  embed(request: { model: string; dimensions: number; texts: readonly string[]; signal?: AbortSignal }): Promise<readonly (readonly number[])[]>;
};
export function createEmbedder(_options: { model: string; dimensions: number; provider: EmbeddingProvider }): Embedder {
  throw new Error("not implemented");
}

export type EmbedderResolver = (
  text: string,
  signal?: AbortSignal,
) => readonly number[] | Promise<readonly number[]>;

export interface EmbedderCall {
  text: string;
  signal?: AbortSignal;
}

/**
 * Injectable boundary double for embedding contract tests.
 *
 * The production adapter owns provider calls. This double records inputs and
 * delegates vectors to the caller, so storage tests never depend on a model.
 */
export class EmbedderStub implements Embedder {
  private readonly resolve: EmbedderResolver;
  private readonly recordedCalls: EmbedderCall[] = [];

  constructor(resolve?: EmbedderResolver) {
    this.resolve = resolve ?? (() => {
      throw new Error("embedding resolver not configured");
    });
  }

  get calls(): readonly EmbedderCall[] {
    return this.recordedCalls.slice();
  }

  async embed(text: string, signal?: AbortSignal): Promise<readonly number[]> {
    if (signal?.aborted) {
      throw signal.reason ?? new DOMException("The embedding request was aborted", "AbortError");
    }
    this.recordedCalls.push({ text, signal });
    const vector = await this.resolve(text, signal);
    return [...vector];
  }

  async embedBatch(
    texts: readonly string[],
    signal?: AbortSignal,
  ): Promise<readonly (readonly number[])[]> {
    const result: number[][] = [];
    for (const text of texts) {
      result.push([...(await this.embed(text, signal))]);
    }
    return result;
  }
}

export { EmbedderStub as StubEmbedder };
