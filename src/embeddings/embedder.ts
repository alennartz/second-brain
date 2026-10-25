export interface Embedder {
  embed(text: string, signal?: AbortSignal): Promise<readonly number[]>;
  embedBatch(
    texts: readonly string[],
    signal?: AbortSignal,
  ): Promise<readonly (readonly number[])[]>;
}

export class EmbedderStub implements Embedder {
  async embed(_text: string, _signal?: AbortSignal): Promise<readonly number[]> {
    throw new Error("not implemented");
  }

  async embedBatch(
    _texts: readonly string[],
    _signal?: AbortSignal,
  ): Promise<readonly (readonly number[])[]> {
    throw new Error("not implemented");
  }
}

export { EmbedderStub as StubEmbedder };
