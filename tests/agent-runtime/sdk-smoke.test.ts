import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, test } from "bun:test";
import {
  fauxAssistantMessage,
  fauxProvider,
  fauxToolCall,
  type FauxProviderHandle,
  type FauxResponseStep,
} from "@earendil-works/pi-ai";
import { ModelRuntime } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import {
  createSdkAgentRuntime,
  type AgentEvent,
  type AgentRunRequest,
  type AgentRuntime,
  type AgentTool,
  type StructuredToolResult,
  type WorkflowModelRef,
} from "../../src/agent-runtime/index.ts";

const model: WorkflowModelRef = {
  provider: "agent-runtime-smoke",
  model: "deterministic",
  thinkingLevel: "high",
};

type DomainFixture = {
  tools: AgentTool[];
  searchCalls: string[];
  selectedNodeIds: string[];
  signals: AbortSignal[];
};

function readString(input: unknown, key: string): string {
  if (typeof input !== "object" || input === null || typeof (input as Record<string, unknown>)[key] !== "string") {
    throw new Error(`${key} must be a string`);
  }
  return (input as Record<string, string>)[key];
}

function createDomainFixture(): DomainFixture {
  const searchCalls: string[] = [];
  const selectedNodeIds: string[] = [];
  const signals: AbortSignal[] = [];
  const searchParameters = Type.Object({ query: Type.String() });
  const searchOutput = Type.Object({ nodes: Type.Array(Type.String()) });
  const selectParameters = Type.Object({ nodeId: Type.String() });
  const selectOutput = Type.Object({ accepted: Type.Boolean() });
  const brokenParameters = Type.Object({});
  const brokenOutput = Type.Object({ ok: Type.Boolean() });

  const searchMemory: AgentTool = {
    name: "searchMemory",
    description: "Search domain memory.",
    parameters: searchParameters,
    outputSchema: searchOutput,
    execute: async (input, signal): Promise<StructuredToolResult> => {
      signals.push(signal);
      const query =
        typeof input === "object" && input !== null
          ? String((input as Record<string, unknown>).query)
          : "undefined";
      searchCalls.push(query);
      if (signal.aborted) {
        return {
          toolName: "searchMemory",
          structuredContent: { nodes: [] },
          isError: true,
        };
      }
      return {
        toolName: "searchMemory",
        structuredContent: { nodes: [`node-for:${query}`] },
      };
    },
  };

  const selectNode: AgentTool = {
    name: "selectNode",
    description: "Record one selected domain node.",
    parameters: selectParameters,
    outputSchema: selectOutput,
    execute: async (input, signal): Promise<StructuredToolResult> => {
      signals.push(signal);
      const nodeId = readString(input, "nodeId");
      selectedNodeIds.push(nodeId);
      return {
        toolName: "selectNode",
        structuredContent: { accepted: !signal.aborted },
        isError: signal.aborted,
      };
    },
  };

  const brokenStructured: AgentTool = {
    name: "brokenStructured",
    description: "Return invalid structured content for contract tests.",
    parameters: brokenParameters,
    outputSchema: brokenOutput,
    execute: async (_input, signal): Promise<StructuredToolResult> => ({
      toolName: "brokenStructured",
      structuredContent: { ok: "not-a-boolean" },
      isError: signal.aborted,
    }),
  };

  return { tools: [searchMemory, selectNode, brokenStructured], searchCalls, selectedNodeIds, signals };
}

async function withRuntime<T>(
  responses: FauxResponseStep[],
  run: (fixture: { runtime: AgentRuntime; faux: FauxProviderHandle; directory: string }) => Promise<T>,
): Promise<T> {
  const directory = await mkdtemp(join(tmpdir(), "second-brain-agent-runtime-"));
  const faux = fauxProvider({
    api: "agent-runtime-faux",
    provider: model.provider,
    models: [{ id: model.model, name: "Agent Runtime Deterministic", reasoning: true }],
  });
  faux.setResponses(responses);
  try {
    const modelRuntime = await ModelRuntime.create({
      authPath: join(directory, "auth.json"),
      modelsPath: join(directory, "models.json"),
      allowModelNetwork: false,
      refreshOnCreate: false,
    });
    const fauxApiKey = faux.provider.auth.apiKey;
    if (!fauxApiKey) {
      throw new Error("The faux provider must expose API-key authentication.");
    }
    fauxApiKey.resolve = async ({ credential }) => ({
      auth: { apiKey: credential?.key ?? "agent-runtime-test-key" },
    });
    modelRuntime.registerNativeProvider(faux.provider);
    const runtime = createSdkAgentRuntime({ modelRuntime, cwd: directory, agentDir: directory });
    return await run({ runtime, faux, directory });
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}

function request(tools: readonly AgentTool[], prompt = "Use the domain tools."): AgentRunRequest {
  return {
    model,
    systemPrompt: "Use only the supplied domain tools.",
    prompt,
    tools,
  };
}

describe("SDK-backed agent runtime seam", () => {
  test("creates an in-memory session per run and selects provider, model, and effort", async () => {
    const domain = createDomainFixture();
    const userCounts: number[] = [];
    const modelsSeen: string[] = [];
    const effortsSeen: unknown[] = [];
    const response = (
      context: { messages: readonly unknown[] },
      options: { reasoning?: unknown } | undefined,
      _state: unknown,
      requestModel: { provider: string; id: string },
    ) => {
      userCounts.push(context.messages.filter((message) => (message as { role?: unknown }).role === "user").length);
      modelsSeen.push(`${requestModel.provider}/${requestModel.id}`);
      effortsSeen.push(options?.reasoning);
      return fauxAssistantMessage(fauxToolCall("searchMemory", { query: "ideas" }));
    };
    await withRuntime(
      [response, fauxAssistantMessage("first complete"), response, fauxAssistantMessage("second complete")],
      async ({ runtime }) => {
        const first = await runtime.run(request(domain.tools, "first request"));
        const second = await runtime.run(request(domain.tools, "second request"));

        expect(first.settled).toBe(true);
        expect(second.settled).toBe(true);
        expect(domain.searchCalls).toEqual(["ideas", "ideas"]);
        expect(userCounts).toEqual([1, 1]);
        expect(modelsSeen).toEqual([`${model.provider}/${model.model}`, `${model.provider}/${model.model}`]);
        expect(effortsSeen).toEqual([model.thinkingLevel, model.thinkingLevel]);
      },
    );
  });

  test("executes a model-issued direct tool call and preserves structured output", async () => {
    const domain = createDomainFixture();
    await withRuntime(
      [fauxAssistantMessage(fauxToolCall("searchMemory", { query: "ideas" })), fauxAssistantMessage("complete")],
      async ({ runtime }) => {
        const result = await runtime.run(request(domain.tools));

        expect(result.settled).toBe(true);
        expect(result.aborted).toBe(false);
        expect(result.lastAssistantText).toBe("complete");
        expect(domain.searchCalls).toEqual(["ideas"]);
        expect(result.toolResults).toContainEqual(expect.objectContaining({
          toolName: "searchMemory",
          structuredContent: { nodes: ["node-for:ideas"] },
        }));
      },
    );
  });

  test("lets a Codemode script consume structured domain-tool results", async () => {
    const domain = createDomainFixture();
    const script = `const found = await tools.searchMemory({ query: "ideas" });\nreturn await tools.selectNode({ nodeId: found.nodes[0] });`;
    await withRuntime(
      [fauxAssistantMessage(fauxToolCall("codemode", { code: script })), fauxAssistantMessage("complete")],
      async ({ runtime }) => {
        const result = await runtime.run(request(domain.tools));

        expect(result.settled).toBe(true);
        expect(domain.searchCalls).toEqual(["ideas"]);
        expect(domain.selectedNodeIds).toEqual(["node-for:ideas"]);
      },
    );
  });

  test("keeps Codemode enabled while closing filesystem, shell, network, MCP, and model tools", async () => {
    const domain = createDomainFixture();
    const events: AgentEvent[] = [];
    const script = [
      "const absent = ['read', 'bash', 'web_fetch', 'mcp__external__search', 'models'].map(name => {",
      "try { return typeof tools[name]; } catch (error) { return error.message; }",
      "});",
      "return [typeof tools.searchMemory, ...absent].join('|')",
    ].join(" ");
    await withRuntime(
      [fauxAssistantMessage(fauxToolCall("codemode", { code: script })), fauxAssistantMessage("complete")],
      async ({ runtime }) => {
        const result = await runtime.run({
          ...request(domain.tools),
          onEvent: (event) => events.push(event),
        });

        expect(result.settled).toBe(true);
        const serialized = JSON.stringify(events);
        expect(serialized).toContain("tools.read does not exist");
        expect(serialized).toContain("tools.bash does not exist");
        expect(serialized).toContain("tools.web_fetch does not exist");
        expect(serialized).toContain("tools.mcp__external__search does not exist");
        expect(serialized).not.toContain('"name":"read"');
        expect(serialized).not.toContain('"name":"bash"');
        expect(serialized).not.toContain('"name":"web_fetch"');
      },
    );
  });

  test("reports input schema failures from model-issued tool calls", async () => {
    const domain = createDomainFixture();
    await withRuntime(
      [fauxAssistantMessage(fauxToolCall("searchMemory", { query: 42 })), fauxAssistantMessage("recovered")],
      async ({ runtime }) => {
        const result = await runtime.run(request(domain.tools));

        expect(result.settled).toBe(true);
        expect(result.lastAssistantText).toBe("recovered");
        expect(domain.searchCalls).toEqual([]);
        expect(result.toolResults.some((toolResult) => toolResult.toolName === "searchMemory" && toolResult.isError)).toBe(true);
      },
    );
  });

  test("reports output schema failures from domain tools", async () => {
    const domain = createDomainFixture();
    await withRuntime(
      [fauxAssistantMessage(fauxToolCall("brokenStructured", {})), fauxAssistantMessage("recovered")],
      async ({ runtime }) => {
        const result = await runtime.run(request(domain.tools));

        expect(result.settled).toBe(true);
        expect(result.lastAssistantText).toBe("recovered");
        expect(result.toolResults.some((toolResult) => toolResult.toolName === "brokenStructured" && toolResult.isError)).toBe(true);
      },
    );
  });

  test("cancels a request and leaves disposal to the runtime seam", async () => {
    const domain = createDomainFixture();
    let providerReadyResolve: (() => void) | undefined;
    const providerReady = new Promise<void>((resolve) => {
      providerReadyResolve = resolve;
    });
    const response = (_context: unknown, options: { signal?: AbortSignal } | undefined) =>
      new Promise<ReturnType<typeof fauxAssistantMessage>>((resolve) => {
        const signal = options?.signal;
        if (!signal) {
          resolve(fauxAssistantMessage("unexpected missing signal"));
          return;
        }
        providerReadyResolve?.();
        signal.addEventListener("abort", () => resolve(fauxAssistantMessage("aborted")), { once: true });
      });
    await withRuntime([response], async ({ runtime }) => {
      const controller = new AbortController();
      const pending = runtime.run({ ...request(domain.tools, "cancel this"), signal: controller.signal });
      await providerReady;
      controller.abort();
      const result = await pending;

      expect(result.aborted).toBe(true);
      expect(result.settled).toBe(true);
    });
  });
});
