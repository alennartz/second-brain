export type ThinkingLevel =
  | "off"
  | "minimal"
  | "low"
  | "medium"
  | "high"
  | "xhigh"
  | "max";

export interface WorkflowModelRef {
  provider: string;
  model: string;
  thinkingLevel: ThinkingLevel;
}

export interface IntakeSettings {
  maxRequestChars: number;
  chunkChars: number;
  processingBatchChars: number;
  workerConcurrency: number;
  leaseSeconds: number;
  pollIntervalSeconds: number;
  retryBaseDelaySeconds: number;
  retryMaxDelaySeconds: number;
  shutdownGraceSeconds: number;
}

export interface DreamSettings {
  enabled: boolean;
  idleTimeoutMinutes: number;
  delayMultiplier: number;
  maxDelayMinutes: number;
  batchSize: number;
}

export interface Settings {
  ingestModel: WorkflowModelRef;
  recallModel: WorkflowModelRef;
  dreamModel: WorkflowModelRef;
  embeddingModel: string;
  embeddingDimensions: number;
  dbPath: string;
  intake: IntakeSettings;
  dream: DreamSettings;
}

export type SettingsEnvironment = Readonly<Record<string, string | undefined>>;

export function parseWorkflowModelRef(_value: string): WorkflowModelRef {
  throw new Error("not implemented");
}

export function parseSettings(_environment: SettingsEnvironment): Settings {
  throw new Error("not implemented");
}
