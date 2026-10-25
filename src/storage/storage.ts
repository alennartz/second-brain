import type {
  ClaimedBatch,
  EdgeId,
  EdgeRecord,
  IntakeChunkDraft,
  IntakeChunkRecord,
  IntakeQueueSnapshot,
  MemorySearchResult,
  NewEdge,
  NewNode,
  NodeFields,
  NodeId,
  NodeRecord,
  Timestamp,
} from "../core/types.ts";

/**
 * Domain-only transaction scope for composite graph mutations.
 *
 * The scope never exposes SurrealDB values. The storage implementation commits
 * all calls or rolls them back when the callback rejects.
 */
export type UnlinkedCooccurrenceCandidate = { fromId: NodeId; toId: NodeId; sharedNoteIds: readonly NodeId[] };

export interface StorageTransaction {
  createNode(input: NewNode): Promise<NodeRecord>;
  getNode(id: NodeId): Promise<NodeRecord | undefined>;
  updateNodeFields(id: NodeId, fields: NodeFields): Promise<NodeRecord | undefined>;
  deleteNode(id: NodeId): Promise<void>;

  createEdge(input: NewEdge): Promise<EdgeRecord>;
  getEdge(id: EdgeId): Promise<EdgeRecord | undefined>;
  deleteEdge(id: EdgeId): Promise<void>;
  getIncomingEdges(id: NodeId): Promise<readonly EdgeRecord[]>;
  getOutgoingEdges(id: NodeId): Promise<readonly EdgeRecord[]>;
  getEdgesByType(edgeType: string): Promise<readonly EdgeRecord[]>;
  findEdges(from: NodeId, edgeType: string, to: NodeId): Promise<readonly EdgeRecord[]>;
  createIntakeChunks(
    intakeId: string,
    chunks: readonly IntakeChunkDraft[],
    idempotencyKey?: string,
  ): Promise<number>;
}

export interface Storage {
  withTransaction<T>(operation: (transaction: StorageTransaction) => Promise<T>): Promise<T>;
  init(): Promise<void>;
  close(): Promise<void>;

  createNode(input: NewNode): Promise<NodeRecord>;
  getNode(id: NodeId): Promise<NodeRecord | undefined>;
  updateNodeFields(id: NodeId, fields: NodeFields): Promise<NodeRecord | undefined>;
  deleteNode(id: NodeId): Promise<void>;

  createEdge(input: NewEdge): Promise<EdgeRecord>;
  getEdge(id: EdgeId): Promise<EdgeRecord | undefined>;
  deleteEdge(id: EdgeId): Promise<void>;
  getIncomingEdges(id: NodeId): Promise<readonly EdgeRecord[]>;
  getOutgoingEdges(id: NodeId): Promise<readonly EdgeRecord[]>;
  findEdges(from: NodeId, edgeType: string, to: NodeId): Promise<readonly EdgeRecord[]>;

  searchCandidates(query: string, limit: number): Promise<MemorySearchResult>;
  findSimilarCandidates(id: NodeId, limit: number): Promise<readonly NodeRecord[]>;
  getEdgesByType(edgeType: string): Promise<readonly EdgeRecord[]>;
  findUnlinkedCooccurrenceCandidates(limit: number): Promise<readonly UnlinkedCooccurrenceCandidate[]>;

  createIntakeChunks(
    intakeId: string,
    chunks: readonly IntakeChunkDraft[],
    idempotencyKey?: string,
  ): Promise<number>;
  claimIntakeBatch(
    workerId: string,
    maxChars: number,
    leaseSeconds: number,
  ): Promise<ClaimedBatch | undefined>;
  renewIntakeBatch(leaseToken: string, leaseSeconds: number): Promise<number>;
  deleteIntakeBatch(leaseToken: string): Promise<number>;
  releaseIntakeBatch(
    leaseToken: string,
    error: string,
    nextAttemptAt?: Timestamp,
  ): Promise<void>;
  getIntakeChunks(ids: readonly NodeId[]): Promise<readonly IntakeChunkRecord[]>;
  searchIntakeChunks(query: string, limit: number): Promise<readonly IntakeChunkRecord[]>;
  setIntakePaused(intakeId: string, paused: boolean): Promise<number>;
  deleteIntake(intakeId: string): Promise<number>;
  intakeQueueSnapshot(): Promise<IntakeQueueSnapshot>;
}

export class StorageStub implements Storage {
  async getEdgesByType(_edgeType: string): Promise<readonly EdgeRecord[]> {
    throw new Error("not implemented");
  }

  async findUnlinkedCooccurrenceCandidates(_limit: number): Promise<readonly UnlinkedCooccurrenceCandidate[]> {
    throw new Error("not implemented");
  }

  async withTransaction<T>(
    _operation: (transaction: StorageTransaction) => Promise<T>,
  ): Promise<T> {
    throw new Error("not implemented");
  }

  async init(): Promise<void> {
    throw new Error("not implemented");
  }

  async close(): Promise<void> {
    throw new Error("not implemented");
  }

  async createNode(_input: NewNode): Promise<NodeRecord> {
    throw new Error("not implemented");
  }

  async getNode(_id: NodeId): Promise<NodeRecord | undefined> {
    throw new Error("not implemented");
  }

  async updateNodeFields(
    _id: NodeId,
    _fields: NodeFields,
  ): Promise<NodeRecord | undefined> {
    throw new Error("not implemented");
  }

  async deleteNode(_id: NodeId): Promise<void> {
    throw new Error("not implemented");
  }

  async createEdge(_input: NewEdge): Promise<EdgeRecord> {
    throw new Error("not implemented");
  }

  async getEdge(_id: EdgeId): Promise<EdgeRecord | undefined> {
    throw new Error("not implemented");
  }

  async deleteEdge(_id: EdgeId): Promise<void> {
    throw new Error("not implemented");
  }

  async getIncomingEdges(_id: NodeId): Promise<readonly EdgeRecord[]> {
    throw new Error("not implemented");
  }

  async getOutgoingEdges(_id: NodeId): Promise<readonly EdgeRecord[]> {
    throw new Error("not implemented");
  }

  async findEdges(
    _from: NodeId,
    _edgeType: string,
    _to: NodeId,
  ): Promise<readonly EdgeRecord[]> {
    throw new Error("not implemented");
  }

  async searchCandidates(_query: string, _limit: number): Promise<MemorySearchResult> {
    throw new Error("not implemented");
  }

  async findSimilarCandidates(
    _id: NodeId,
    _limit: number,
  ): Promise<readonly NodeRecord[]> {
    throw new Error("not implemented");
  }

  async createIntakeChunks(
    _intakeId: string,
    _chunks: readonly IntakeChunkDraft[],
    _idempotencyKey?: string,
  ): Promise<number> {
    throw new Error("not implemented");
  }

  async claimIntakeBatch(
    _workerId: string,
    _maxChars: number,
    _leaseSeconds: number,
  ): Promise<ClaimedBatch | undefined> {
    throw new Error("not implemented");
  }

  async renewIntakeBatch(_leaseToken: string, _leaseSeconds: number): Promise<number> {
    throw new Error("not implemented");
  }

  async deleteIntakeBatch(_leaseToken: string): Promise<number> {
    throw new Error("not implemented");
  }

  async releaseIntakeBatch(
    _leaseToken: string,
    _error: string,
    _nextAttemptAt?: Timestamp,
  ): Promise<void> {
    throw new Error("not implemented");
  }

  async getIntakeChunks(_ids: readonly NodeId[]): Promise<readonly IntakeChunkRecord[]> {
    throw new Error("not implemented");
  }

  async searchIntakeChunks(
    _query: string,
    _limit: number,
  ): Promise<readonly IntakeChunkRecord[]> {
    throw new Error("not implemented");
  }

  async setIntakePaused(_intakeId: string, _paused: boolean): Promise<number> {
    throw new Error("not implemented");
  }

  async deleteIntake(_intakeId: string): Promise<number> {
    throw new Error("not implemented");
  }

  async intakeQueueSnapshot(): Promise<IntakeQueueSnapshot> {
    throw new Error("not implemented");
  }
}

export { StorageStub as StubStorage };
