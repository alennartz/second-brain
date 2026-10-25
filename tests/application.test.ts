import { describe, expect, test } from "bun:test";
import { startApplication, type CompositionFactories } from "../src/application/runtime";
import type { HttpApplication } from "../src/http/contracts";

function fixture(failure?: "init" | "pipeline-start" | "pipeline-stop") {
  const events: string[] = [];
  const modelRuntime = {};
  const embedder = {};
  const knowledge = {};
  const application = {} as HttpApplication;
  const storage = {
    init: async () => { events.push("storage:init"); if (failure === "init") throw new Error("init failed"); },
    close: async () => { events.push("storage:close"); },
  };
  const pipeline = {
    start: async () => { events.push("pipeline:start"); if (failure === "pipeline-start") throw new Error("pipeline failed"); },
    stop: async () => { events.push("pipeline:stop"); if (failure === "pipeline-stop") throw new Error("stop failed"); },
  };
  const scheduler = {
    start: () => { events.push("scheduler:start"); },
    stop: async () => { events.push("scheduler:stop"); },
  };
  const received: { pipeline?: unknown; scheduler?: unknown; application?: unknown } = {};
  const factories: CompositionFactories = {
    createModelRuntime: () => { events.push("model:create"); return modelRuntime; },
    createEmbedder: () => { events.push("embedder:create"); return embedder; },
    createStorage: value => { expect(value).toBe(embedder); return storage; },
    createKnowledge: value => { expect(value).toBe(storage); return knowledge; },
    createPipeline: dependencies => { received.pipeline = dependencies; return pipeline; },
    createScheduler: dependencies => { received.scheduler = dependencies; return scheduler; },
    createApplication: dependencies => { received.application = dependencies; return application; },
  };
  return { factories, events, received, application, storage, pipeline, scheduler, modelRuntime, knowledge };
}

describe("application composition", () => {
  test("startup shares one storage, knowledge module, and model runtime across workers and HTTP", async () => {
    const f = fixture();
    const runtime = await startApplication(f.factories);
    expect(runtime.application).toBe(f.application);
    const dependencies = { storage: f.storage, knowledge: f.knowledge, modelRuntime: f.modelRuntime };
    expect(f.received.pipeline).toEqual(dependencies);
    expect(f.received.scheduler).toEqual(dependencies);
    expect(f.received.application).toEqual({ ...dependencies, pipeline: f.pipeline, scheduler: f.scheduler, dreamJobs: expect.any(Map) });
    expect(f.events.filter(event => event === "model:create")).toHaveLength(1);
    expect(f.events.filter(event => event === "embedder:create")).toHaveLength(1);
    expect(f.events.indexOf("storage:init")).toBeLessThan(f.events.indexOf("pipeline:start"));
    expect(f.events.indexOf("storage:init")).toBeLessThan(f.events.indexOf("scheduler:start"));
  });
  test("shutdown stops workers before closing shared storage", async () => {
    const f = fixture();
    const runtime = await startApplication(f.factories);
    await runtime.shutdown();
    expect(f.events.indexOf("pipeline:stop")).toBeLessThan(f.events.indexOf("storage:close"));
    expect(f.events.indexOf("scheduler:stop")).toBeLessThan(f.events.indexOf("storage:close"));
    expect(f.events.filter(event => event === "storage:close")).toHaveLength(1);
  });
  test("initialization failure closes storage without starting workers", async () => {
    const f = fixture("init");
    await expect(startApplication(f.factories)).rejects.toThrow("init failed");
    expect(f.events).toContain("storage:close");
    expect(f.events).not.toContain("pipeline:start");
    expect(f.events).not.toContain("scheduler:start");
  });
  test("pipeline startup failure releases storage and all started workers", async () => {
    const f = fixture("pipeline-start");
    await expect(startApplication(f.factories)).rejects.toThrow("pipeline failed");
    expect(f.events).toContain("pipeline:stop");
    if (f.events.includes("scheduler:start")) expect(f.events).toContain("scheduler:stop");
    expect(f.events.at(-1)).toBe("storage:close");
  });
  test("shutdown still stops the scheduler and closes storage when the pipeline fails", async () => {
    const f = fixture("pipeline-stop");
    const runtime = await startApplication(f.factories);
    await runtime.shutdown().catch(() => undefined);
    expect(f.events).toContain("scheduler:stop");
    expect(f.events.at(-1)).toBe("storage:close");
  });
});
