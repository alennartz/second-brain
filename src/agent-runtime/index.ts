import type { TSchema } from "@sinclair/typebox";
import type { ModelRuntime } from "@earendil-works/pi-coding-agent";

export type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";
export type WorkflowModelRef = { provider: string; model: string; thinkingLevel: ThinkingLevel };
export type StructuredToolResult = { toolName: string; structuredContent: unknown; isError?: boolean };
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
export function createSdkAgentRuntime(_options: SdkAgentRuntimeOptions): AgentRuntime {
  throw new Error("not implemented");
}
export function createAgentRuntime(_factory?: SessionFactory): AgentRuntime {
  throw new Error("not implemented");
}
