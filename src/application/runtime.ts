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
  throw new Error("not implemented");
}
