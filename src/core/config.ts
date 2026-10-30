import { homedir } from "node:os";
import { join } from "node:path";

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
  cycleTimeoutMinutes: number;
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
  piToolsPackage: string;
  sessionDir: string;
  intake: IntakeSettings;
  dream: DreamSettings;
}

export type SettingsEnvironment = Readonly<Record<string, string | undefined>>;

export function parseWorkflowModelRef(value: string): WorkflowModelRef {
  const slash = value.indexOf("/");
  const colon = value.lastIndexOf(":");
  const levels: readonly string[] = ["off", "minimal", "low", "medium", "high", "xhigh", "max"];
  if (slash <= 0 || colon <= slash + 1 || !levels.includes(value.slice(colon + 1)) || /\s/.test(value)) {
    throw new Error(`Invalid workflow model reference: ${value}`);
  }
  return { provider: value.slice(0, slash), model: value.slice(slash + 1, colon), thinkingLevel: value.slice(colon + 1) as ThinkingLevel };
}

export function parseSettings(environment: SettingsEnvironment): Settings {
  const number = (key: string, fallback: number, integer = false): number => {
    const value = Number(environment[`BRAIN_${key}`] ?? fallback);
    if (!Number.isFinite(value) || value <= 0 || (integer && !Number.isInteger(value))) throw new Error(`Invalid BRAIN_${key}`);
    return value;
  };
  const path = (key: string, fallback: string): string => {
    const value = environment[`BRAIN_${key}`] ?? fallback;
    if (!value.trim() || /\s/.test(value)) throw new Error(`Invalid BRAIN_${key}`);
    return value;
  };
  const model = (key: string) => parseWorkflowModelRef(environment[`BRAIN_${key}_MODEL`] ?? "");
  const sessionDir = path("SESSION_DIR", join(homedir(), ".state", "second-brain"));
  const enabled = environment.BRAIN_DREAM_ENABLED ?? "true";
  if (!["true", "false", "1", "0"].includes(enabled.toLowerCase())) throw new Error("Invalid BRAIN_DREAM_ENABLED");
  return {
    ingestModel: model("INGEST"), recallModel: model("RECALL"), dreamModel: model("DREAM"),
    embeddingModel: environment.BRAIN_EMBEDDING_MODEL ?? "openai:text-embedding-3-small",
    embeddingDimensions: number("EMBEDDING_DIMENSIONS", 1536, true), dbPath: environment.BRAIN_DB_PATH ?? "data/brain.db",
    piToolsPackage: path("PI_TOOLS_PACKAGE", "packages/pi-second-brain"),
    sessionDir: sessionDir.startsWith("~/") ? join(homedir(), sessionDir.slice(2)) : sessionDir,
    intake: {
      maxRequestChars: number("INTAKE_MAX_REQUEST_CHARS", 100000, true), chunkChars: number("INTAKE_CHUNK_CHARS", 4000, true),
      processingBatchChars: number("INTAKE_PROCESSING_BATCH_CHARS", 12000, true), workerConcurrency: number("INTAKE_WORKER_CONCURRENCY", 1, true),
      leaseSeconds: number("INTAKE_LEASE_SECONDS", 300), pollIntervalSeconds: number("INTAKE_POLL_INTERVAL_SECONDS", 1),
      retryBaseDelaySeconds: number("INTAKE_RETRY_BASE_DELAY_SECONDS", 5), retryMaxDelaySeconds: number("INTAKE_RETRY_MAX_DELAY_SECONDS", 3600),
      shutdownGraceSeconds: number("INTAKE_SHUTDOWN_GRACE_SECONDS", 60),
    },
    dream: { enabled: ["true", "1"].includes(enabled.toLowerCase()), idleTimeoutMinutes: number("DREAM_IDLE_TIMEOUT_MINUTES", 10),
      cycleTimeoutMinutes: number("DREAM_CYCLE_TIMEOUT_MINUTES", 10), delayMultiplier: number("DREAM_DELAY_MULTIPLIER", 1.5), maxDelayMinutes: number("DREAM_MAX_DELAY_MINUTES", 720), batchSize: number("DREAM_BATCH_SIZE", 25, true) },
  };
}
