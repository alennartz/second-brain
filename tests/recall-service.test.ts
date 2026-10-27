import { describe, expect, test } from "bun:test";
import { createRecallService, type RecallEvidenceStore } from "../src/http/contracts";

const evidence: RecallEvidenceStore = {
  getNode: async id => id === "note:a" ? { id, content: "live content" } : undefined,
  getEdge: async id => id === "edge:a" ? { id, context: "live edge" } : undefined,
  getUnprocessed: async id => id === "intake_chunk:a" ? { id, content: "live raw" } : undefined,
};
describe("live recall evidence", () => {
  test("forwards hints and resolves each evidence layer against current storage", async () => {
    const service = createRecallService({ run: async (question, _signal, hints) => {
      expect(question).toBe("topic");
      expect(hints).toEqual(["work"]);
      return { answer: "Found", nodeIds: ["note:a"], edgeIds: ["edge:a"], unprocessedIds: ["intake_chunk:a"] };
    } }, evidence);
    expect(await service.recall({ question: "topic", hints: ["work"] })).toEqual({
      answer: "Found", context: { nodes: [{ id: "note:a", content: "live content" }], edges: [{ id: "edge:a", context: "live edge" }], unprocessed: [{ id: "intake_chunk:a", content: "live raw" }] },
    });
  });
  test("keeps evidence-free context null", async () => {
    const service = createRecallService({ run: async () => ({ answer: "None" }) }, evidence);
    expect(await service.recall({ question: "topic" })).toEqual({ answer: "None", context: null });
  });
  test("returns null context when a citation no longer resolves to live evidence", async () => {
    const service = createRecallService({ run: async () => ({ answer: "Found", nodeIds: ["note:deleted"] }) }, evidence);
    await expect(service.recall({ question: "topic" })).resolves.toEqual({ answer: "Found", context: null });
  });
  test("propagates failed live reads instead of returning stale evidence", async () => {
    const service = createRecallService({ run: async () => ({ answer: "Found", nodeIds: ["note:a"] }) }, { ...evidence, getNode: async () => { throw new Error("storage unavailable"); } });
    await expect(service.recall({ question: "topic" })).rejects.toThrow();
  });
});
