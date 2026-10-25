export type NodeId = string;
export type EdgeId = string;
export type Timestamp = string;

export class InvalidInputError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "InvalidInputError";
  }
}

export type NodeKind = "note" | "entity";

export interface NodeFields {
  content?: string;
  source?: string;
  summary?: string;
  name?: string;
  type?: string;
  description?: string;
  dreamAge?: number;
}

export type NewNode =
  | {
      kind: "entity";
      name: string;
      type: string;
      description?: string;
    }
  | {
      kind: "note";
      content: string;
      source?: string;
      summary?: string;
    };

export interface NodeRecord extends NodeFields {
  id: NodeId;
  /** The persisted SurrealDB table name, when returned by storage. */
  table?: NodeKind;
  /** The domain kind, when a caller prefers a discriminant over table. */
  kind?: NodeKind;
  createdAt?: Timestamp;
  updatedAt?: Timestamp;
}

export interface NewEdge {
  fromId: NodeId;
  edgeType: string;
  toId: NodeId;
  context?: string;
}

export interface EdgeRecord {
  id: EdgeId;
  from: NodeId;
  to: NodeId;
  /** Canonical edge type. Storage may also expose this as `table`. */
  edgeType: string;
  table?: string;
  context?: string;
  createdAt?: Timestamp;
  updatedAt?: Timestamp;
}

export interface RankedSearchCandidates {
  bm25: readonly NodeRecord[];
  vector: readonly NodeRecord[];
}

export interface MemorySearchCandidates {
  note: RankedSearchCandidates;
  entity: RankedSearchCandidates;
  intake_chunk: RankedSearchCandidates;
}

export interface UnprocessedEvidence {
  id: NodeId;
  intake_id: string;
  chunk_index: number;
  total_chunks: number;
  content: string;
  source: string;
  hints: readonly string[];
  created_at?: Timestamp;
}

export interface MemorySearchResult {
  nodes: readonly NodeRecord[];
  unprocessed: readonly UnprocessedEvidence[];
}

export interface IntakeChunkDraft {
  chunk_index: number;
  total_chunks: number;
  content: string;
  source?: string;
  hints?: readonly string[];
}

export type IntakeChunkState = "ready" | "leased" | "retry_wait" | "paused";

export interface IntakeChunkRecord {
  id: NodeId;
  intake_id: string;
  chunk_index: number;
  total_chunks: number;
  content: string;
  source: string;
  hints: readonly string[];
  state: IntakeChunkState;
  attempt_count: number;
  next_attempt_at: Timestamp | null;
  lease_token: string | null;
  lease_expires_at: Timestamp | null;
  last_error: string | null;
  idempotency_key: string | null;
  created_at: Timestamp | null;
  updated_at: Timestamp | null;
}

export interface ClaimedBatch {
  lease_token: string;
  intake_id: string;
  chunks: readonly IntakeChunkRecord[];
}

export interface IntakeQueueSnapshot {
  ready: number;
  leased: number;
  retry_wait: number;
  paused: number;
  oldest_ready_at: Timestamp | null;
  oldest_retry_at: Timestamp | null;
  worker_count: number;
  active_leases: number;
  stuck_intakes: readonly Record<string, unknown>[];
  recent_errors: readonly Record<string, unknown>[];
}
