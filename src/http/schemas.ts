import { Type, type TUnsafe } from "@sinclair/typebox";
import type { DreamJob, GraphResponse, IntakeBody, PipelineSnapshot, RecallBody, RecallResponse } from "./contracts";
import { timestampPattern } from "../core/timestamps";

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
  const count = Type.Integer({ minimum: 0 });
  const dictionary = Type.Record(Type.String(), Type.Unknown());
  const dictionaries = Type.Array(dictionary);
  const nullableTime = Type.Union([Type.String(), Type.Null()]);
  const identity = (name: string) => Type.Object({ [name]: Type.String({ minLength: 1 }) });
  return {
    ingestBody: Type.Object({ text: Type.String(), hints: Type.Optional(Type.Array(Type.String())), source: Type.Optional(Type.String()), captured_at: Type.String({ pattern: timestampPattern }) }),
    ingestHeaders: Type.Object({ "idempotency-key": Type.Optional(Type.String()) }),
    ingestResponse: Type.Object({ chunks_stored: count }),
    recallBody: Type.Object({ question: Type.String(), hints: Type.Optional(Type.Array(Type.String())) }),
    recallResponse: Type.Object({ answer: Type.String(), context: Type.Union([Type.Null(), Type.Object({ nodes: dictionaries, edges: dictionaries, unprocessed: dictionaries })]) }),
    graphParams: identity("record_id"),
    graphResponse: Type.Object({ node: dictionary, connections: Type.Array(Type.Object({ edge: dictionary, node: dictionary })) }),
    intakeParams: identity("intake_id"),
    intakeResponse: identity("intake_id"),
    discardResponse: Type.Object({ intake_id: Type.String(), chunks_discarded: count }),
    dreamParams: identity("job_id"),
    dreamResponse: Type.Object({ job_id: Type.String(), status: Type.Union([Type.Literal("pending"), Type.Literal("running"), Type.Literal("complete"), Type.Literal("failed")]), error: Type.Union([Type.String(), Type.Null()]) }),
    pipelineResponse: Type.Object({ ready: count, leased: count, retry_wait: count, paused: count, oldest_ready_at: nullableTime, oldest_retry_at: nullableTime, worker_count: count, active_leases: count, stuck_intakes: dictionaries, recent_errors: dictionaries }),
    healthResponse: Type.Object({ status: Type.Literal("ok") }),
  } as unknown as HttpSchemas;
}
