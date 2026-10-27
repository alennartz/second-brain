import type { TSchema } from "@sinclair/typebox";
import { createAgentSession, createCodemodeExtension, DefaultResourceLoader, SessionManager, SettingsManager, type ExtensionFactory, type ModelRuntime, type ToolAnnotations } from "@earendil-works/pi-coding-agent";
import { Value } from "@sinclair/typebox/value";
import type { ThinkingLevel, WorkflowModelRef } from "../core/config";

export type { ThinkingLevel, WorkflowModelRef } from "../core/config";
export type StructuredToolResult = { toolName: string; structuredContent: unknown; isError?: boolean; stop?: boolean };
export type AgentEvent = { type: string; [key: string]: unknown };
export type AgentTool = {
  name: string;
  label?: string;
  description: string;
  promptSnippet?: string;
  promptGuidelines?: readonly string[];
  annotations?: ToolAnnotations;
  parameters: TSchema;
  outputSchema?: TSchema;
  execute(input: unknown, signal: AbortSignal): Promise<StructuredToolResult>;
};
export type AgentRunRequest = {
  model: WorkflowModelRef;
  systemPrompt: string;
  prompt: string;
  toolNames: readonly string[];
  customTools?: readonly AgentTool[];
  signal?: AbortSignal;
  onEvent?: (event: AgentEvent) => void;
  followUp?: (result: AgentRunResult) => string | undefined;
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
  extensionPaths?: readonly string[];
};

export type SessionOptions = {
  model: WorkflowModelRef;
  systemPrompt: string;
  toolNames: readonly string[];
  customTools: readonly AgentTool[];
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
function removePiDocsSection(prompt: string): string {
  const start = prompt.indexOf("\n<docs>");
  if (start < 0) return prompt;
  const endTag = "</docs>";
  const end = prompt.indexOf(endTag, start);
  return end < 0 ? prompt : `${prompt.slice(0, start)}${prompt.slice(end + endTag.length)}`;
}
function createWorkflowPromptExtension(systemPrompt: string): ExtensionFactory {
  return pi => {
    pi.on("before_agent_start", event => {
      const toolsStart = event.systemPrompt.indexOf("<tools>");
      if (toolsStart < 0) return { systemPrompt };
      const generatedSections = removePiDocsSection(event.systemPrompt.slice(toolsStart));
      return { systemPrompt: `${systemPrompt}\n\n${generatedSections}` };
    });
  };
}
export function createSdkAgentRuntime(options: SdkAgentRuntimeOptions): AgentRuntime {
  return createAgentRuntime(async request => {
    const model = options.modelRuntime.getModel(request.model.provider, request.model.model);
    if (!model) throw new Error(`Unknown model: ${request.model.provider}/${request.model.model}`);
    const results: StructuredToolResult[] = [];
    const termination = { requested: false };
    const customNames = new Set(request.customTools?.map(tool => tool.name) ?? []);
    const customToolCallIds = new Set<string>();
    const activeTools = ["codemode", ...request.toolNames, ...(request.customTools?.map(tool => tool.name) ?? [])];
    const settingsManager = SettingsManager.inMemory({
      compaction: { enabled: false },
      retry: { enabled: false },
      defaultTools: activeTools,
    });
    const resourceLoader = new DefaultResourceLoader({
      cwd: options.cwd, agentDir: options.agentDir, settingsManager,
      additionalExtensionPaths: [...(options.extensionPaths ?? [])],
      noSkills: true, noPromptTemplates: true, noThemes: true,
      extensionFactories: [createCodemodeExtension({ mode: "on", models: false }), createWorkflowPromptExtension(request.systemPrompt)],
      agentsFilesOverride: () => ({ agentsFiles: [] }),
      systemPromptOverride: () => undefined,
    });
    await resourceLoader.reload();
    const { session } = await createAgentSession({
      cwd: options.cwd, agentDir: options.agentDir, model, thinkingLevel: request.model.thinkingLevel,
      modelRuntime: options.modelRuntime, resourceLoader, settingsManager,
      sessionManager: SessionManager.inMemory(options.cwd),
      tools: activeTools,
      customTools: (request.customTools ?? []).map(tool => ({
        name: tool.name, label: tool.label ?? tool.name, description: tool.description, parameters: tool.parameters,
        ...(tool.promptSnippet ? { promptSnippet: tool.promptSnippet } : {}),
        ...(tool.promptGuidelines ? { promptGuidelines: [...tool.promptGuidelines] } : {}),
        ...(tool.annotations ? { annotations: tool.annotations } : {}),
        ...(tool.outputSchema ? { outputSchema: tool.outputSchema } : {}),
        async execute(toolCallId, input, signal) {
          try {
            if (signal?.aborted) throw new Error("Tool execution aborted");
            if (!Value.Check(tool.parameters, input)) throw new Error("Invalid tool parameters");
            const result = await tool.execute(input, signal ?? new AbortController().signal);
            if (!result.isError && tool.outputSchema && !Value.Check(tool.outputSchema, result.structuredContent)) throw new Error("Invalid tool output");
            customToolCallIds.add(toolCallId);
            results.push(result);
            if (result.stop) { termination.requested = true; queueMicrotask(() => { void session.abort(); }); }
            return { content: [{ type: "text" as const, text: JSON.stringify(result.structuredContent) }], details: result, structuredContent: result.structuredContent as never, isError: result.isError };
          } catch (error) {
            customToolCallIds.add(toolCallId);
            const result = { toolName: tool.name, structuredContent: { error: String(error) }, isError: true };
            results.push(result);
            throw error;
          }
        },
      })),
    });
    try {
      await session.bindExtensions({});
      session.setActiveToolsByName(activeTools);
    } catch (error) { session.dispose(); throw error; }
    return {
      async prompt(text, execution) {
        const unsubscribe = session.subscribe(event => {
          execution.onEvent?.(event as unknown as AgentEvent);
          if (event.type === "tool_execution_end" && event.toolName !== "codemode" && (!customNames.has(event.toolName) || !customToolCallIds.has(event.toolCallId))) {
            const result = event.result as { structuredContent?: unknown } | undefined;
            results.push({ toolName: event.toolName, structuredContent: result?.structuredContent ?? result, isError: event.isError });
          }
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
    const session = await factory({ model: request.model, systemPrompt: request.systemPrompt, toolNames: request.toolNames, customTools: [...(request.customTools ?? [])], persistence: "memory", builtInTools: [], resources: [], codemode: { mode: "on", models: false } });
    const cancellation = { pending: Promise.resolve() };
    const abort = () => { cancellation.pending = session.abort(); };
    signal.addEventListener("abort", abort, { once: true });
    try {
      if (signal.aborted) { abort(); return { settled: true, aborted: true, toolResults: [] }; }
      let result = await session.prompt(request.prompt, { signal, onEvent: request.onEvent });
      while (request.followUp && !signal.aborted && !result.aborted) {
        const followUp = request.followUp(result);
        if (followUp === undefined) break;
        result = await session.prompt(followUp, { signal, onEvent: request.onEvent });
      }
      return result;
    } finally {
      signal.removeEventListener("abort", abort);
      try { await cancellation.pending; } finally { await session.dispose(); }
    }
  } };
}
