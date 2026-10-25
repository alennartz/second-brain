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
export interface CompositionFactories<
  TEmbedder = unknown,
  TStorage extends ManagedStorage = ManagedStorage,
  TKnowledge = unknown,
  TPipeline extends ManagedPipeline = ManagedPipeline,
  TScheduler extends ManagedScheduler = ManagedScheduler,
> {
  createModelRuntime(): unknown;
  createEmbedder(): TEmbedder;
  createStorage(embedder: TEmbedder): TStorage;
  createKnowledge(storage: TStorage): TKnowledge;
  createPipeline(dependencies: { storage: TStorage; knowledge: TKnowledge; modelRuntime: unknown }): TPipeline;
  createScheduler(dependencies: { storage: TStorage; knowledge: TKnowledge; modelRuntime: unknown }): TScheduler;
  createApplication(dependencies: {
    storage: TStorage;
    knowledge: TKnowledge;
    modelRuntime: unknown;
    pipeline: TPipeline;
    scheduler: TScheduler;
    dreamJobs: Map<string, DreamJob>;
  }): HttpApplication;
}
export interface ApplicationRuntime {
  application: HttpApplication;
  shutdown(): Promise<void>;
}
export async function startApplication<
  TEmbedder,
  TStorage extends ManagedStorage,
  TKnowledge,
  TPipeline extends ManagedPipeline,
  TScheduler extends ManagedScheduler,
>(factories: CompositionFactories<TEmbedder, TStorage, TKnowledge, TPipeline, TScheduler>): Promise<ApplicationRuntime> {
  const modelRuntime = factories.createModelRuntime();
  const embedder = factories.createEmbedder();
  const storage = factories.createStorage(embedder);
  const state: { pipeline?: ManagedPipeline; scheduler?: ManagedScheduler; application?: HttpApplication; shutdown?: Promise<void> } = {};
  async function cleanup() {
    const errors: unknown[] = [];
    for (const resource of [state.pipeline, state.scheduler]) {
      if (!resource) continue;
      try { await resource.stop(); }
      catch (error) { errors.push(error); }
    }
    try { await state.application?.waitForDreamJobs?.(); }
    catch (error) { errors.push(error); }
    try { await storage.close(); }
    catch (error) { errors.push(error); }
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
    state.application = application;
    await pipeline.start();
    scheduler.start();
    return { application, shutdown() { return state.shutdown ??= cleanup(); } };
  } catch (error) {
    await cleanup().catch(() => undefined);
    throw error;
  }
}
