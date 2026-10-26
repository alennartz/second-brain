import { describe, expect, test } from "bun:test";
import { Type } from "@sinclair/typebox";
import { createAgentRuntime, type AgentRunRequest, type AgentRunResult, type RuntimeSession, type SessionOptions } from "../src/agent-runtime/index.ts";

const result: AgentRunResult = { settled: true, aborted: false, lastAssistantText: "done", toolResults: [{ toolName: "searchMemory", structuredContent: { nodes: [] } }] };
const request: AgentRunRequest = { model: { provider: "test", model: "model", thinkingLevel: "high" }, systemPrompt: "domain only", prompt: "find evidence", toolNames: [] };
function fixture(prompt: RuntimeSession["prompt"] = async () => result) {
  const options: SessionOptions[] = [];
  const sessions: { aborted: number; disposed: number }[] = [];
  const runtime = createAgentRuntime(async (input) => {
    options.push(input);
    const state = { aborted: 0, disposed: 0 };
    sessions.push(state);
    return { prompt, abort: async () => { state.aborted++; }, dispose: async () => { state.disposed++; } };
  });
  return { runtime, options, sessions };
}
describe("AgentRuntime", () => {
  test("returns settled assistant text and structured tool results", async () => {
    const { runtime } = fixture();
    expect(await runtime.run(request)).toEqual(result);
  });
  test("creates isolated in-memory sessions for each request", async () => {
    const f = fixture();
    await f.runtime.run(request);
    await f.runtime.run(request);
    expect(f.sessions).toHaveLength(2);
    expect(f.options.every(o => o.persistence === "memory")).toBe(true);
  });
  test("sends follow-up prompts through the same session", async () => {
    const prompts: string[] = [];
    let promptCount = 0;
    const f = fixture(async (text) => {
      prompts.push(text);
      promptCount++;
      return promptCount === 1 ? { ...result, lastAssistantText: "first" } : { ...result, lastAssistantText: "second" };
    });
    const output = await f.runtime.run({
      ...request,
      followUp: current => current.lastAssistantText === "first" ? "retry" : undefined,
    });
    expect(output.lastAssistantText).toBe("second");
    expect(prompts).toEqual(["find evidence", "retry"]);
    expect(f.sessions).toHaveLength(1);
    expect(f.sessions[0]!.disposed).toBe(1);
  });
  test("uses selected model and only the explicit custom tools with Codemode", async () => {
    const f = fixture();
    const tool = { name: "searchMemory", description: "search", parameters: Type.Object({}), outputSchema: Type.Object({}), execute: async () => result.toolResults[0]! };
    await f.runtime.run({ ...request, customTools: [tool] });
    expect(f.options[0]).toMatchObject({ model: request.model, systemPrompt: request.systemPrompt, toolNames: [], customTools: [tool], builtInTools: [], resources: [], codemode: { mode: "on", models: false } });
  });
  test("disposes the session after normal settlement", async () => {
    const f = fixture();
    await f.runtime.run(request);
    expect(f.sessions[0]!.disposed).toBe(1);
  });
  test("disposes the session after a prompt error", async () => {
    const f = fixture(async () => { throw new Error("model unavailable"); });
    await expect(f.runtime.run(request)).rejects.toThrow("model unavailable");
    expect(f.sessions[0]!.disposed).toBe(1);
  });
  test("observes prompt events without altering structured results", async () => {
    const event = { type: "tool_execution_end", toolName: "searchMemory" };
    const events: unknown[] = [];
    const f = fixture(async (_, options) => { options.onEvent?.(event); return result; });
    expect(await f.runtime.run({ ...request, onEvent: e => events.push(e) })).toEqual(result);
    expect(events).toEqual([event]);
  });
  test("passes cancellation to session execution, aborts and disposes", async () => {
    const controller = new AbortController();
    let received: AbortSignal | undefined;
    const f = fixture(async (_, options) => {
      received = options.signal;
      controller.abort();
      return { settled: true, aborted: true, toolResults: [] };
    });
    const outcome = await f.runtime.run({ ...request, signal: controller.signal });
    expect(received!.aborted).toBe(true);
    expect(outcome.aborted).toBe(true);
    expect(outcome.settled).toBe(true);
    expect(f.sessions[0]!.aborted).toBeGreaterThan(0);
    expect(f.sessions[0]!.disposed).toBe(1);
  });
  test("does not execute a prompt when cancellation precedes the run", async () => {
    const controller = new AbortController();
    controller.abort();
    let prompts = 0;
    const f = fixture(async () => { prompts++; return result; });
    expect((await f.runtime.run({ ...request, signal: controller.signal })).aborted).toBe(true);
    expect(prompts).toBe(0);
  });
  test("does not expose assistant text when the settled session has none", async () => {
    const f = fixture(async () => ({ settled: true, aborted: false, toolResults: [] }));
    expect(await f.runtime.run(request)).toEqual({ settled: true, aborted: false, toolResults: [] });
  });
});
