import { AsyncLocalStorage } from "node:async_hooks";
import type { Storage } from "../../../src/storage/storage.ts";
import { parseSecondBrainConfig, resolveSecret, type SecondBrainConfig } from "./config.ts";
import { bindKnowledge, cancellableStorage, type KnowledgeContext, type KnowledgeFunctions } from "./graph.ts";

type BridgeState = {
  storage?: Storage;
  config?: SecondBrainConfig;
  settings?: () => unknown;
  selfCreated?: Storage;
  init?: Promise<Storage>;
  context?: AsyncLocalStorage<KnowledgeContext>;
};

function state(): BridgeState {
  const holder = globalThis as { __secondBrain?: BridgeState };
  const bridge = holder.__secondBrain ??= {};
  return bridge;
}
function contextStore(): AsyncLocalStorage<KnowledgeContext> {
  const bridge = state();
  return bridge.context ??= new AsyncLocalStorage<KnowledgeContext>();
}

export function injectSecondBrainStorage(storage: Storage): void {
  state().storage = storage;
}

export function injectSecondBrainConfig(config: SecondBrainConfig): void {
  state().config = config;
}

export function registerBridgeSettings(source: { getSettings(): unknown }): void {
  state().settings = () => source.getSettings();
}

export function withKnowledgeContext<T>(context: KnowledgeContext, operation: () => Promise<T>): Promise<T> {
  return contextStore().run(context, operation);
}

async function initStorage(config: SecondBrainConfig): Promise<Storage> {
  const [{ createEmbeddedStorage }, { createEmbedder }, { createOpenAIEmbeddingProvider }, { default: OpenAI }] = await Promise.all([
    import("../../../src/storage/embedded.ts"),
    import("../../../src/embeddings/embedder.ts"),
    import("../../../src/embeddings/openai.ts"),
    import("openai"),
  ]);
  const apiKey = resolveSecret(config.embedding.apiKey);
  const client = new OpenAI({ apiKey, ...(config.embedding.baseUrl ? { baseURL: config.embedding.baseUrl } : {}) });
  const embedder = createEmbedder({ model: config.embedding.model, dimensions: config.embedding.dimensions, provider: createOpenAIEmbeddingProvider(client) });
  const storage = createEmbeddedStorage({ dbPath: config.dbPath, embeddingDimensions: config.embedding.dimensions, embedder });
  await storage.init();
  return storage;
}

async function resolveStorage(): Promise<Storage> {
  const bridge = state();
  if (bridge.storage) return bridge.storage;
  if (bridge.config) return bridge.init ??= initStorage(bridge.config).then(storage => bridge.selfCreated = storage);
  const settings = bridge.settings?.();
  const raw = (settings as { secondBrain?: unknown } | undefined)?.secondBrain;
  if (raw) return bridge.init ??= initStorage(parseSecondBrainConfig(raw)).then(storage => bridge.selfCreated = storage);
  throw new Error("Second Brain tools are not configured: inject a storage instance, inject configuration, or set the secondBrain key in Pi settings");
}

export async function scopedKnowledge(signal: AbortSignal | undefined): Promise<KnowledgeFunctions> {
  const scope = signal ?? new AbortController().signal;
  scope.throwIfAborted();
  const storage = await resolveStorage();
  scope.throwIfAborted();
  return bindKnowledge(cancellableStorage(storage, scope), contextStore().getStore());
}

export async function closeBridgedStorage(): Promise<void> {
  const bridge = state();
  const storage = bridge.selfCreated;
  if (!storage) return;
  bridge.selfCreated = undefined;
  bridge.init = undefined;
  await storage.close();
}
