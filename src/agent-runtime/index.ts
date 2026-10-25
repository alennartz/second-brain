import type { TSchema } from "@sinclair/typebox";
import { createAgentSession, createCodemodeExtension, DefaultResourceLoader, SessionManager, SettingsManager, type ModelRuntime } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";

export type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
export type WorkflowModelRef = { provider: string; model: string; thinkingLevel: ThinkingLevel };
export type StructuredToolResult = { toolName: string; structuredContent: unknown; isError?: boolean; stop?: boolean };
export type AgentEvent = { type: string; [key: string]: unknown };
export type AgentTool = {
  name: string;
  description: string;
  parameters: TSchema;
  outputSchema?: TSchema;
  execute(input: unknown, signal: AbortSignal): Promise<StructuredToolResult>;
};
export type AgentRunRequest = {
  model: WorkflowModelRef;
  systemPrompt: string;
  prompt: string;
  tools: readonly AgentTool[];
  signal?: AbortSignal;
  onEvent?: (event: AgentEvent) => void;
};
export type AgentRunResult = {
  settled: boolean;
  aborted: boolean;
  lastAssistantText?: string;
  toolResults: readonly StructuredToolResult[];
};
export interface AgentRuntime { run(request: AgentRunRequest): Promise<AgentRunResult> }

export type SdkAgentRuntimeOptions = {
  modelRuntime: ModelRuntime;
  cwd: string;
  agentDir: string;
};

export type SessionOptions = {
  model: WorkflowModelRef;
  systemPrompt: string;
  tools: readonly AgentTool[];
  persistence: "memory";
  builtInTools: readonly never[];
  resources: readonly never[];
  codemode: { mode: "on"; models: false };
};
export interface RuntimeSession {
  prompt(text: string, options: { signal: AbortSignal; onEvent?: (event: AgentEvent) => void }): Promise<AgentRunResult>;
  abort(): Promise<void>;
  dispose(): Promise<void>;
}
export type SessionFactory = (options: SessionOptions) => Promise<RuntimeSession>;
export function createSdkAgentRuntime(options: SdkAgentRuntimeOptions): AgentRuntime {
  return createAgentRuntime(async request => {
    const model = options.modelRuntime.getModel(request.model.provider, request.model.model);
    if (!model) throw new Error(`Unknown model: ${request.model.provider}/${request.model.model}`);
    const results: StructuredToolResult[] = [];
    const termination = { requested: false };
    const resourceLoader = new DefaultResourceLoader({
      cwd: options.cwd, agentDir: options.agentDir,
      noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true,
      extensionFactories: [createCodemodeExtension({ mode: "on", models: false })],
      agentsFilesOverride: () => ({ agentsFiles: [] }),
      systemPromptOverride: () => request.systemPrompt,
    });
    await resourceLoader.reload();
    const { session } = await createAgentSession({
      cwd: options.cwd, agentDir: options.agentDir, model, thinkingLevel: request.model.thinkingLevel,
      modelRuntime: options.modelRuntime, resourceLoader,
      sessionManager: SessionManager.inMemory(options.cwd),
      settingsManager: SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false }, defaultTools: ["codemode", ...request.tools.map(tool => tool.name)] }),
      tools: ["codemode", ...request.tools.map(tool => tool.name)], customTools: request.tools.map(tool => ({
        name: tool.name, label: tool.name, description: tool.description, parameters: tool.parameters,
        ...(tool.outputSchema ? { outputSchema: tool.outputSchema } : {}),
        async execute(_id, input, signal) {
          try {
            if (signal?.aborted) throw new Error("Tool execution aborted");
            if (!Value.Check(tool.parameters, input)) throw new Error("Invalid tool parameters");
            const result = await tool.execute(input, signal ?? new AbortController().signal);
            if (!result.isError && tool.outputSchema && !Value.Check(tool.outputSchema, result.structuredContent)) throw new Error("Invalid tool output");
            results.push(result);
            if (result.stop) { termination.requested = true; queueMicrotask(() => { void session.abort(); }); }
            return { content: [{ type: "text" as const, text: JSON.stringify(result.structuredContent) }], details: result, structuredContent: result.structuredContent as never, isError: result.isError };
          } catch (error) {
            const result = { toolName: tool.name, structuredContent: { error: String(error) }, isError: true };
            results.push(result);
            throw error;
          }
        },
      })),
    });
    try {
      await session.bindExtensions({});
      session.setActiveToolsByName(["codemode", ...request.tools.map(tool => tool.name)]);
    } catch (error) { session.dispose(); throw error; }
    return {
      async prompt(text, execution) {
        const unsubscribe = session.subscribe(event => {
          execution.onEvent?.(event as unknown as AgentEvent);
          if (event.type === "tool_execution_end" && event.isError && !results.some(result => result.toolName === event.toolName && result.isError)) results.push({ toolName: event.toolName, structuredContent: event.result, isError: true });
        });
        try {
          await session.prompt(text);
          await session.waitForIdle();
          const lastAssistantText = session.getLastAssistantText();
          return { settled: true, aborted: execution.signal.aborted && !termination.requested, ...(lastAssistantText === undefined ? {} : { lastAssistantText }), toolResults: results };
        } finally { unsubscribe(); }
      },
      abort: () => session.abort(),
      async dispose() { session.dispose(); },
    };
  });
}
export function createAgentRuntime(factory?: SessionFactory): AgentRuntime {
  if (!factory) throw new Error("A session factory is required");
  return { async run(request) {
    const signal = request.signal ?? new AbortController().signal;
    if (signal.aborted) return { settled: true, aborted: true, toolResults: [] };
    const session = await factory({ model: request.model, systemPrompt: request.systemPrompt, tools: request.tools, persistence: "memory", builtInTools: [], resources: [], codemode: { mode: "on", models: false } });
    const cancellation = { pending: Promise.resolve() };
    const abort = () => { cancellation.pending = session.abort(); };
    signal.addEventListener("abort", abort, { once: true });
    try {
      if (signal.aborted) { abort(); return { settled: true, aborted: true, toolResults: [] }; }
      return await session.prompt(request.prompt, { signal, onEvent: request.onEvent });
    } finally {
      signal.removeEventListener("abort", abort);
      try { await cancellation.pending; } finally { await session.dispose(); }
    }
  } };
}
