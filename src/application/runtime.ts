import type { DreamJob, HttpApplication } from "../http/contracts";

export interface ManagedStorage {
  init(): Promise<void>;
  close(): Promise<void>;
}
export interface ManagedPipeline {
  start(): Promise<void>;
  stop(): Promise<void>;
}
export interface ManagedScheduler {
  start(): void;
  stop(): Promise<void>;
}
export interface CompositionFactories {
  createModelRuntime(): unknown;
  createEmbedder(): unknown;
  createStorage(embedder: unknown): ManagedStorage;
  createKnowledge(storage: ManagedStorage): unknown;
  createPipeline(dependencies: { storage: ManagedStorage; knowledge: unknown; modelRuntime: unknown }): ManagedPipeline;
  createScheduler(dependencies: { storage: ManagedStorage; knowledge: unknown; modelRuntime: unknown }): ManagedScheduler;
  createApplication(dependencies: {
    storage: ManagedStorage;
    knowledge: unknown;
    modelRuntime: unknown;
    pipeline: ManagedPipeline;
    scheduler: ManagedScheduler;
    dreamJobs: Map<string, DreamJob>;
  }): HttpApplication;
}
export interface ApplicationRuntime {
  application: HttpApplication;
  shutdown(): Promise<void>;
}
export async function startApplication(factories: CompositionFactories): Promise<ApplicationRuntime> {
  const modelRuntime = factories.createModelRuntime();
  const embedder = factories.createEmbedder();
  const storage = factories.createStorage(embedder);
  const state: { pipeline?: ManagedPipeline; scheduler?: ManagedScheduler; shutdown?: Promise<void> } = {};
  async function cleanup() {
    const errors: unknown[] = [];
    for (const resource of [state.pipeline, state.scheduler, storage]) {
      if (!resource) continue;
      try { if ("stop" in resource) await resource.stop(); else await resource.close(); }
      catch (error) { errors.push(error); }
    }
    if (errors.length) throw new AggregateError(errors, "Application shutdown failed");
  }
  try {
    await storage.init();
    const knowledge = factories.createKnowledge(storage);
    const dependencies = { storage, knowledge, modelRuntime };
    const pipeline = factories.createPipeline(dependencies);
    state.pipeline = pipeline;
    const scheduler = factories.createScheduler(dependencies);
    state.scheduler = scheduler;
    const application = factories.createApplication({ ...dependencies, pipeline, scheduler, dreamJobs: new Map() });
    await pipeline.start();
    scheduler.start();
    return { application, shutdown() { return state.shutdown ??= cleanup(); } };
  } catch (error) {
    await cleanup().catch(() => undefined);
    throw error;
  }
}
