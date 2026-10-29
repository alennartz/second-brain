import { describe, expect, test } from "bun:test";
import {
  parseSettings,
  parseWorkflowModelRef,
  type Settings,
} from "../src/core/config.ts";

describe("configuration contracts", () => {
  test("parses a provider/model reference with a thinking level", () => {
    expect(parseWorkflowModelRef("openai/gpt-4o:high")).toEqual({
      provider: "openai",
      model: "gpt-4o",
      thinkingLevel: "high",
    });
  });

  test("splits at the first slash and final colon", () => {
    expect(parseWorkflowModelRef("provider/team/model:variant:high")).toEqual({ provider: "provider", model: "team/model:variant", thinkingLevel: "high" });
  });
  test.each(["/model:off", "provider/:off", "provider/model:", "provider/model", "provider/model:nope"])("rejects malformed reference %s", value => {
    expect(() => parseWorkflowModelRef(value)).toThrow();
  });
  test("requires a model reference for each workflow", () => {
    const models = { BRAIN_INGEST_MODEL: "provider/model:off", BRAIN_RECALL_MODEL: "provider/model:off", BRAIN_DREAM_MODEL: "provider/model:off" };
    for (const key of Object.keys(models)) {
      expect(() => parseSettings({ ...models, [key]: undefined })).toThrow();
    }
  });
  test("accepts the complete thinking-level range", () => {
    for (const level of ["off", "minimal", "low", "medium", "high", "xhigh", "max"] as const) {
      expect(parseWorkflowModelRef(`provider/model:${level}`).thinkingLevel).toBe(level);
    }
  });

  test("rejects a malformed model reference", () => {
    expect(() => parseWorkflowModelRef("gpt-4o")).toThrow();
  });

  test("rejects an unsupported thinking level", () => {
    expect(() => parseWorkflowModelRef("openai/gpt-4o:unsupported")).toThrow();
  });

  test("loads workflow, embedding, database, intake, and dream settings", () => {
    const environment = {
      BRAIN_INGEST_MODEL: "openai/gpt-4o:high",
      BRAIN_RECALL_MODEL: "openai/gpt-4o:medium",
      BRAIN_DREAM_MODEL: "openai/gpt-4o:low",
      BRAIN_EMBEDDING_MODEL: "openai:text-embedding-3-small",
      BRAIN_EMBEDDING_DIMENSIONS: "1536",
      BRAIN_DB_PATH: "data/brain.db",
      BRAIN_DREAM_CYCLE_TIMEOUT_MINUTES: "7",
    };
    const settings: Settings = parseSettings(environment);

    expect(settings).toMatchObject({
      ingestModel: { provider: "openai", model: "gpt-4o", thinkingLevel: "high" },
      recallModel: { provider: "openai", model: "gpt-4o", thinkingLevel: "medium" },
      dreamModel: { provider: "openai", model: "gpt-4o", thinkingLevel: "low" },
      embeddingModel: "openai:text-embedding-3-small",
      embeddingDimensions: 1536,
      dbPath: "data/brain.db",
      intake: expect.any(Object),
      dream: { cycleTimeoutMinutes: 7 },
    });
  });
});
