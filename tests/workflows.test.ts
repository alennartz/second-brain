import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import {
  createDreamWorkflow, createIngestWorkflow as createIngestWithGuidance, createRecallWorkflow as createRecallWithGuidance,
  type WorkflowDependencies, type WorkflowRuntime,
} from "../src/workflows/workflows";

const model = { provider: "test", model: "model", thinkingLevel: "off" as const };
const ingestGuidance = readFileSync(new URL("../packages/pi-second-brain/skills/memory/ingest.md", import.meta.url), "utf8");
const recallGuidance = readFileSync(new URL("../packages/pi-second-brain/skills/memory/recall.md", import.meta.url), "utf8");
const createIngestWorkflow = (dependencies: WorkflowDependencies) => createIngestWithGuidance(dependencies, ingestGuidance);
const createRecallWorkflow = (dependencies: WorkflowDependencies) => createRecallWithGuidance(dependencies, recallGuidance);
const dreamGuidance = {
  deduplicate: readFileSync(new URL("../packages/pi-second-brain/skills/memory/deduplicate.md", import.meta.url), "utf8"),
  connect: readFileSync(new URL("../packages/pi-second-brain/skills/memory/connect.md", import.meta.url), "utf8"),
};
function dependencies(run: WorkflowRuntime["run"]): WorkflowDependencies {
  return { model, runtime: { run } };
}
const settled = { settled: true, aborted: false, toolResults: [] };
const batch = {
  intakeId: "capture", leaseToken: "lease",
  chunks: [
    { id: "intake_chunk:a", chunkIndex: 0, content: "First paragraph.", hints: ["topic"], capturedAt: "2026-01-01T00:00:00Z" },
    { id: "intake_chunk:b", chunkIndex: 1, content: "Second paragraph.", hints: [], capturedAt: "2026-01-01T00:00:00Z" },
  ],
};
const sorted = (names: readonly string[]) => [...names].sort();

describe("ingest workflow", () => {
  test("uses only ingest tool names and submits the leased text in source order", async () => {
    const requests: Parameters<WorkflowRuntime["run"]>[0][] = [];
    const workflow = createIngestWorkflow(dependencies(async request => { requests.push(request); return settled; }));
    expect(await workflow.run(batch)).toEqual({ clean: true, aborted: false, errors: [] });
    expect(requests).toHaveLength(1);
    expect(sorted(requests[0]!.toolNames)).toEqual(["memory_explore", "memory_get_node", "memory_search", "memory_store_edge", "memory_store_node", "memory_update_node"]);
    expect(requests[0]!.customTools ?? []).toEqual([]);
    expect(requests[0]!.model).toEqual(model);
    expect(requests[0]!.systemPrompt).toContain(ingestGuidance);
    expect(requests[0]!.systemPrompt).not.toContain(recallGuidance);
    expect(requests[0]!.systemPrompt).not.toContain(dreamGuidance.deduplicate);
    expect(requests[0]!.systemPrompt).not.toContain(dreamGuidance.connect);
    expect(requests[0]!.prompt).toContain("topic");
    expect(requests[0]!.prompt).toContain("capturedAt");
    expect(requests[0]!.prompt).toContain("2026-01-01T00:00:00Z");
    expect(requests[0]!.prompt.indexOf("First paragraph.")).toBeLessThan(requests[0]!.prompt.indexOf("Second paragraph."));
  });
  test("reports tool errors as an unclean batch", async () => {
    const workflow = createIngestWorkflow(dependencies(async () => ({ ...settled, toolResults: [{ toolName: "memory_store_edge", isError: true, structuredContent: { error: "missing node" } }] })));
    const outcome = await workflow.run(batch);
    expect(outcome.clean).toBe(false);
    expect(outcome.errors.length).toBeGreaterThan(0);
  });
  test("marks deterministic node validation errors as non-retryable", async () => {
    const workflow = createIngestWorkflow(dependencies(async () => ({ ...settled, toolResults: [{ toolName: "memory_update_node", isError: true, structuredContent: { error: "Field does not belong to node kind" } }] })));
    const outcome = await workflow.run(batch);
    expect(outcome.clean).toBe(false);
    expect(outcome.retryable).toBe(false);
  });
  test("records safe diagnostics for failed mutation arguments", async () => {
    const diagnostics: unknown[] = [];
    const workflow = createIngestWorkflow({
      ...dependencies(async request => {
        request.onEvent?.({ type: "tool_execution_start", toolName: "memory_store_node", toolCallId: "call-1", args: { kind: "note", content: "private evidence", name: "wrong field" } });
        request.onEvent?.({ type: "tool_execution_end", toolName: "memory_store_node", toolCallId: "call-1", isError: true, result: { structuredContent: { error: "Invalid tool parameters" } } });
        return settled;
      }),
      onIngestDiagnostic: diagnostic => diagnostics.push(diagnostic),
    });
    const outcome = await workflow.run(batch);
    const serialized = JSON.stringify(diagnostics);
    expect(diagnostics).toHaveLength(1);
    expect(serialized).toContain('"tool_name":"memory_store_node"');
    expect(serialized).toContain('"argument_keys":["content","kind","name"]');
    expect(serialized).toContain('"payload_hash"');
    expect(serialized).not.toContain("private evidence");
    expect(outcome.errors.some(error => error.includes("Ingest mutation failed"))).toBe(true);
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
      expect(request.systemPrompt).toContain(recallGuidance);
      expect(request.systemPrompt).not.toContain(ingestGuidance);
      expect(request.systemPrompt).not.toContain(dreamGuidance.deduplicate);
      expect(request.systemPrompt).not.toContain(dreamGuidance.connect);
      const answerTool = request.customTools!.find(tool => tool.name === "answerRecall")!;
      expect(answerTool.description).toContain("validates each citation");
      expect(answerTool.promptGuidelines).toEqual(expect.arrayContaining([
        "After reading evidence, call answerRecall to submit the final answer.",
        "When no evidence exists, omit citation arrays from answerRecall.",
      ]));
      await answerTool.execute({ answer: "None" }, new AbortController().signal);
      return settled;
    }));
    await workflow.run("topic", undefined, ["project-alpha"]);
  });
  test("validates answer arguments before accepting structured output", async () => {
    const workflow = createRecallWorkflow(dependencies(async request => {
      const answer = request.customTools!.find(tool => tool.name === "answerRecall")!;
      await expect(answer.execute({ answer: 1 }, new AbortController().signal)).rejects.toThrow();
      return settled;
    }));
    await expect(workflow.run("topic")).rejects.toThrow();
  });
  test("exposes only read tool names plus the answerRecall custom tool and returns a valid evidence-free answer", async () => {
    const answer = { answer: "No evidence found." };
    const workflow = createRecallWorkflow(dependencies(async request => {
      expect(sorted(request.toolNames)).toEqual(["memory_explore", "memory_get_node", "memory_search"]);
      expect(request.customTools!.map(tool => tool.name)).toEqual(["answerRecall"]);
      await request.customTools!.find(tool => tool.name === "answerRecall")!.execute(answer, new AbortController().signal);
      return settled;
    }));
    expect(await workflow.run("What do I know?")).toEqual(answer);
  });
  test("accepts graph and unprocessed citations collected from tool events", async () => {
    const answer = { answer: "Evidence.", nodeIds: ["note:a"], edgeIds: ["edge:a"], unprocessedIds: ["intake_chunk:a"] };
    const workflow = createRecallWorkflow(dependencies(async request => {
      request.onEvent?.({
        type: "tool_execution_end",
        toolName: "memory_search",
        isError: false,
        result: { structuredContent: { nodes: [{ id: "note:a", content: "Evidence." }], edges: [{ id: "edge:a" }], unprocessed: [{ id: "intake_chunk:a", content: "Raw." }] } },
      });
      await request.customTools!.find(tool => tool.name === "answerRecall")!.execute(answer, new AbortController().signal);
      return settled;
    }));
    expect(await workflow.run("topic")).toEqual(answer);
  });
  test("ignores citations from error results and non-read tools", async () => {
    const answer = { answer: "No evidence." };
    const workflow = createRecallWorkflow(dependencies(async request => {
      request.onEvent?.({ type: "tool_execution_end", toolName: "memory_store_node", isError: false, result: { structuredContent: { id: "note:unrelated" } } });
      request.onEvent?.({ type: "tool_execution_end", toolName: "memory_search", isError: true, result: { structuredContent: { nodes: [{ id: "note:errored" }] } } });
      const tool = request.customTools!.find(tool => tool.name === "answerRecall")!;
      await expect(tool.execute({ ...answer, nodeIds: ["note:unrelated"] }, new AbortController().signal)).rejects.toThrow();
      await tool.execute(answer, new AbortController().signal);
      return settled;
    }));
    expect(await workflow.run("topic")).toEqual(answer);
  });
  test("rejects invented citations and permits a later valid answer", async () => {
    const answer = { answer: "No evidence." };
    const workflow = createRecallWorkflow(dependencies(async request => {
      const tool = request.customTools!.find(tool => tool.name === "answerRecall")!;
      await expect(tool.execute({ ...answer, nodeIds: ["note:invented"] }, new AbortController().signal)).rejects.toThrow();
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
    const workflow = createDreamWorkflow(dependencies(async request => { requests.push(request); return settled; }), dreamGuidance);
    await workflow.deduplicate(["entity:a"]);
    await workflow.connect(["entity:a", "note:b"]);
    expect(requests).toHaveLength(2);
    expect(sorted(requests[0]!.toolNames)).toEqual(["memory_explore", "memory_find_similar", "memory_get_node", "memory_merge_edges", "memory_merge_nodes", "memory_remove_edge", "memory_rename_edge_type", "memory_update_node"]);
    expect(sorted(requests[1]!.toolNames)).toEqual(["memory_explore", "memory_find_similar", "memory_get_node", "memory_store_edge", "memory_suggest_edges", "memory_update_node"]);
    expect(requests[0]!.prompt).toContain("entity:a");
    expect(requests[1]!.prompt).toContain("note:b");
    expect(requests[0]!.systemPrompt).toContain("server-side deduplication curator");
    expect(requests[0]!.systemPrompt).toContain("scheduler has already selected");
    expect(requests[1]!.systemPrompt).toContain("server-side connection curator");
    expect(requests[1]!.systemPrompt).toContain("scheduler has already selected");
  });

  test("injects only the corresponding bundled phase guidance", async () => {
    const requests: Parameters<WorkflowRuntime["run"]>[0][] = [];
    const workflow = createDreamWorkflow(
      dependencies(async request => { requests.push(request); return settled; }),
      dreamGuidance,
    );

    await workflow.deduplicate(["entity:a"]);
    await workflow.connect(["entity:a", "note:b"]);

    expect(requests[0]!.systemPrompt).toContain(dreamGuidance.deduplicate);
    expect(requests[0]!.systemPrompt).not.toContain(dreamGuidance.connect);
    expect(requests[1]!.systemPrompt).toContain(dreamGuidance.connect);
    expect(requests[1]!.systemPrompt).not.toContain(dreamGuidance.deduplicate);
    expect(JSON.parse(requests[0]!.prompt)).toEqual(["entity:a"]);
    expect(JSON.parse(requests[1]!.prompt)).toEqual(["entity:a", "note:b"]);
  });
  test("reports phase mutation failures", async () => {
    const workflow = createDreamWorkflow(dependencies(async () => ({ ...settled, toolResults: [{ toolName: "memory_merge_nodes", isError: true, structuredContent: { error: "merge failed" } }] })), dreamGuidance);
    expect((await workflow.deduplicate(["entity:a"])).errors.length).toBeGreaterThan(0);
  });
  test("passes cancellation to each phase", async () => {
    const controller = new AbortController();
    const workflow = createDreamWorkflow(dependencies(async request => {
      expect(request.signal).toBe(controller.signal);
      return { ...settled, aborted: true };
    }), dreamGuidance);
    expect((await workflow.connect(["note:a"], controller.signal)).aborted).toBe(true);
  });
});
