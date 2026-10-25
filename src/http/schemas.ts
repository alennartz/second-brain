import type { TUnsafe } from "@sinclair/typebox";
import type { DreamJob, GraphResponse, IntakeBody, PipelineSnapshot, RecallBody, RecallResponse } from "./contracts";

export interface HttpSchemas {
  ingestBody: TUnsafe<IntakeBody>;
  ingestHeaders: TUnsafe<{ "idempotency-key"?: string }>;
  ingestResponse: TUnsafe<{ chunks_stored: number }>;
  recallBody: TUnsafe<RecallBody>;
  recallResponse: TUnsafe<RecallResponse>;
  graphParams: TUnsafe<{ record_id: string }>;
  graphResponse: TUnsafe<GraphResponse>;
  intakeParams: TUnsafe<{ intake_id: string }>;
  intakeResponse: TUnsafe<{ intake_id: string }>;
  discardResponse: TUnsafe<{ intake_id: string; chunks_discarded: number }>;
  dreamParams: TUnsafe<{ job_id: string }>;
  dreamResponse: TUnsafe<DreamJob>;
  pipelineResponse: TUnsafe<PipelineSnapshot>;
  healthResponse: TUnsafe<{ status: "ok" }>;
}

export function createHttpSchemas(): HttpSchemas {
  throw new Error("not implemented");
}
