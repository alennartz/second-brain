import { describe, expect, test } from "bun:test";
import {
  createDreamWorkflow, createIngestWorkflow, createRecallWorkflow,
  type WorkflowDependencies, type WorkflowRuntime,
} from "../src/workflows/workflows";

const model = { provider: "test", model: "model", thinkingLevel: "off" as const };
function dependencies(run: WorkflowRuntime["run"]): WorkflowDependencies {
  return { model, runtime: { run } };
}
const settled = { settled: true, aborted: false, toolResults: [] };
const batch = {
  intakeId: "capture", leaseToken: "lease",
  chunks: [
    { id: "intake_chunk:a", chunkIndex: 0, content: "First paragraph.", hints: ["topic"] },
    { id: "intake_chunk:b", chunkIndex: 1, content: "Second paragraph.", hints: [] },
  ],
};
const sorted = (names: readonly string[]) => [...names].sort();

describe("ingest workflow", () => {
  test("uses only ingest tool names and submits the leased text in source order", async () => {
    const requests: Parameters<WorkflowRuntime["run"]>[0][] = [];
    const workflow = createIngestWorkflow(dependencies(async request => { requests.push(request); return settled; }));
    expect(await workflow.run(batch)).toEqual({ clean: true, aborted: false, errors: [] });
    expect(requests).toHaveLength(1);
    expect(sorted(requests[0]!.toolNames)).toEqual(["exploreGraph", "getNode", "searchMemory", "storeEdge", "storeNode", "updateNode"]);
    expect(requests[0]!.customTools).toEqual([]);
    expect(requests[0]!.model).toEqual(model);
    expect(requests[0]!.prompt).toContain("topic");
    expect(requests[0]!.prompt.indexOf("First paragraph.")).toBeLessThan(requests[0]!.prompt.indexOf("Second paragraph."));
  });
  test("reports tool errors as an unclean batch", async () => {
    const workflow = createIngestWorkflow(dependencies(async () => ({ ...settled, toolResults: [{ toolName: "storeEdge", isError: true, structuredContent: { error: "missing node" } }] })));
    const outcome = await workflow.run(batch);
    expect(outcome.clean).toBe(false);
    expect(outcome.errors.length).toBeGreaterThan(0);
  });
  test("never marks an unsettled run clean", async () => {
    const workflow = createIngestWorkflow(dependencies(async () => ({ ...settled, settled: false })));
    expect((await workflow.run(batch)).clean).toBe(false);
  });
  test("passes cancellation to the runtime and does not acknowledge an aborted run", async () => {
    const controller = new AbortController();
    let signal: AbortSignal | undefined;
    const workflow = createIngestWorkflow(dependencies(async request => {
      signal = request.signal;
      controller.abort();
      return { ...settled, aborted: true };
    }));
    const result = await workflow.run(batch, controller.signal);
    expect(signal).toBe(controller.signal);
    expect(result.aborted).toBe(true);
    expect(result.clean).toBe(false);
  });
  test("reports a later runtime failure without acknowledging the batch", async () => {
    const workflow = createIngestWorkflow(dependencies(async () => { throw new Error("provider disconnected"); }));
    const outcome = await workflow.run(batch);
    expect(outcome.clean).toBe(false);
    expect(outcome.errors).toEqual(["provider disconnected"]);
  });
});

describe("recall workflow", () => {
  test("passes caller hints into the recall operation", async () => {
    const workflow = createRecallWorkflow(dependencies(async request => {
      expect(request.prompt).toContain("project-alpha");
      expect(request.systemPrompt).toContain("calling answerRecall directly");
      expect(request.customTools?.find(tool => tool.name === "answerRecall")?.description).toContain("Set hasEvidence to false when all citation arrays are empty");
      await request.customTools!.find(tool => tool.name === "answerRecall")!.execute({ answer: "None", hasEvidence: false, nodeIds: [], edgeIds: [], unprocessedIds: [] }, new AbortController().signal);
      return settled;
    }));
    await workflow.run("topic", undefined, ["project-alpha"]);
  });
  test("validates answer arguments before accepting structured output", async () => {
    const workflow = createRecallWorkflow(dependencies(async request => {
      const answer = request.customTools!.find(tool => tool.name === "answerRecall")!;
      await expect(answer.execute({ answer: 1, hasEvidence: false, nodeIds: [], edgeIds: [], unprocessedIds: [] }, new AbortController().signal)).rejects.toThrow();
      return settled;
    }));
    await expect(workflow.run("topic")).rejects.toThrow();
  });
  test("exposes only read tool names plus the answerRecall custom tool and returns a valid evidence-free answer", async () => {
    const answer = { answer: "No evidence found.", hasEvidence: false, nodeIds: [], edgeIds: [], unprocessedIds: [] };
    const workflow = createRecallWorkflow(dependencies(async request => {
      expect(sorted(request.toolNames)).toEqual(["exploreGraph", "getNode", "searchMemory"]);
      expect(request.customTools!.map(tool => tool.name)).toEqual(["answerRecall"]);
      await request.customTools!.find(tool => tool.name === "answerRecall")!.execute(answer, new AbortController().signal);
      return settled;
    }));
    expect(await workflow.run("What do I know?")).toEqual(answer);
  });
  test("accepts graph and unprocessed citations collected from tool events", async () => {
    const answer = { answer: "Evidence.", hasEvidence: true, nodeIds: ["note:a"], edgeIds: ["edge:a"], unprocessedIds: ["intake_chunk:a"] };
    const workflow = createRecallWorkflow(dependencies(async request => {
      request.onEvent?.({
        type: "tool_execution_end",
        toolName: "searchMemory",
        isError: false,
        result: { structuredContent: { nodes: [{ id: "note:a", content: "Evidence." }], edges: [{ id: "edge:a" }], unprocessed: [{ id: "intake_chunk:a", content: "Raw." }] } },
      });
      await request.customTools!.find(tool => tool.name === "answerRecall")!.execute(answer, new AbortController().signal);
      return settled;
    }));
    expect(await workflow.run("topic")).toEqual(answer);
  });
  test("ignores citations from error results and non-read tools", async () => {
    const answer = { answer: "No evidence.", hasEvidence: false, nodeIds: [], edgeIds: [], unprocessedIds: [] };
    const workflow = createRecallWorkflow(dependencies(async request => {
      request.onEvent?.({ type: "tool_execution_end", toolName: "storeNode", isError: false, result: { structuredContent: { id: "note:unrelated" } } });
      request.onEvent?.({ type: "tool_execution_end", toolName: "searchMemory", isError: true, result: { structuredContent: { nodes: [{ id: "note:errored" }] } } });
      const tool = request.customTools!.find(tool => tool.name === "answerRecall")!;
      await expect(tool.execute({ ...answer, hasEvidence: true, nodeIds: ["note:unrelated"] }, new AbortController().signal)).rejects.toThrow();
      await tool.execute(answer, new AbortController().signal);
      return settled;
    }));
    expect(await workflow.run("topic")).toEqual(answer);
  });
  test("rejects invented citations and permits a later valid answer", async () => {
    const answer = { answer: "No evidence.", hasEvidence: false, nodeIds: [], edgeIds: [], unprocessedIds: [] };
    const workflow = createRecallWorkflow(dependencies(async request => {
      const tool = request.customTools!.find(tool => tool.name === "answerRecall")!;
      await expect(tool.execute({ ...answer, hasEvidence: true, nodeIds: ["note:invented"] }, new AbortController().signal)).rejects.toThrow();
      await tool.execute(answer, new AbortController().signal);
      return settled;
    }));
    expect(await workflow.run("question")).toEqual(answer);
  });
  test("does not return free-form assistant text without a validated answer tool call", async () => {
    const workflow = createRecallWorkflow(dependencies(async () => ({ ...settled, lastAssistantText: "Unvalidated answer" })));
    await expect(workflow.run("question")).rejects.toThrow();
  });
  test("does not return an answer from a cancelled session", async () => {
    const controller = new AbortController();
    const workflow = createRecallWorkflow(dependencies(async request => {
      expect(request.signal).toBe(controller.signal);
      return { ...settled, aborted: true };
    }));
    await expect(workflow.run("question", controller.signal)).rejects.toThrow();
  });
});

describe("dream workflow", () => {
  test("runs deduplication and connection in separate runtime calls with closed tool sets", async () => {
    const requests: Parameters<WorkflowRuntime["run"]>[0][] = [];
    const workflow = createDreamWorkflow(dependencies(async request => { requests.push(request); return settled; }));
    await workflow.deduplicate(["entity:a"]);
    await workflow.connect(["entity:a", "note:b"]);
    expect(requests).toHaveLength(2);
    expect(sorted(requests[0]!.toolNames)).toEqual(["exploreGraph", "findSimilar", "getNode", "mergeEdges", "mergeNodes", "removeEdge", "renameEdgeType", "updateNode"]);
    expect(sorted(requests[1]!.toolNames)).toEqual(["exploreGraph", "findSimilar", "findUnlinkedCooccurrences", "getNode", "storeEdge", "updateNode"]);
    expect(requests[0]!.prompt).toContain("entity:a");
    expect(requests[1]!.prompt).toContain("note:b");
  });
  test("reports phase mutation failures", async () => {
    const workflow = createDreamWorkflow(dependencies(async () => ({ ...settled, toolResults: [{ toolName: "mergeNodes", isError: true, structuredContent: { error: "merge failed" } }] })));
    expect((await workflow.deduplicate(["entity:a"])).errors.length).toBeGreaterThan(0);
  });
  test("passes cancellation to each phase", async () => {
    const controller = new AbortController();
    const workflow = createDreamWorkflow(dependencies(async request => {
      expect(request.signal).toBe(controller.signal);
      return { ...settled, aborted: true };
    }));
    expect((await workflow.connect(["note:a"], controller.signal)).aborted).toBe(true);
  });
});
