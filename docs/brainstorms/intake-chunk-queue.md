# Brainstorm: Intake chunk queue

**Date:** 2026-10-15
**Status:** converged

## The idea

Move ingestion behind a searchable staging queue. `POST /ingest` prepares source text synchronously by chunking and embedding it. An always-on background worker then consumes the chunks in context-sized batches and writes organized knowledge at its own pace.

The staging layer is not worker-only storage. It is a less organized memory layer that participates in recall until its chunks are processed.

## Key decisions

### 1. Chunks are the canonical queued source

**Chosen.** Use one `intake_chunk` table. Do not keep a separate full-source record.

Each row belongs to an internal intake document, has an ordinal, and contains the text used for search and ingestion. The worker's maximum batch size can be smaller than the original source, so a separate full-source record adds storage without helping processing. Ordered chunks are sufficient to form each processing batch.

### 2. Staging is synchronous and all-or-nothing

`POST /ingest` chunks and embeds the complete request, stores every chunk, then returns only the stored chunk count. A successful response means the chunks are searchable and queued. It does not mean organized ingestion finished.

If chunking or embedding fails, partial rows are removed and the request fails. The caller can retry. An optional client idempotency key protects only queued or in-flight duplicates; after chunks are deleted, a later request is new.

### 3. Chunking uses natural boundaries without overlap

The chunker prefers paragraph and sentence boundaries, enforces a configured size limit, and creates disjoint chunks. Each chunk keeps its intake identity and source order.

### 4. Processing is ordered per intake and independent across batches

A worker packs contiguous chunks from one intake until the model context budget is full. Different intakes can process concurrently. An oversized intake takes several processing batches.

Each batch is an independent ingest-agent input. There is no document-level consolidation pass and no rolling state between batches. Existing search and deduplication handle overlap with already organized knowledge.

### 5. Workers run continuously with durable retries

Use an in-app worker pool with configurable concurrency and a default of one. Workers process ready chunks continuously rather than waiting for the dream scheduler's idle periods.

Claimed chunks use leases so a crashed process becomes recoverable. Failures retry forever with exponential backoff and fair scheduling; delayed failures do not block ready work. Operators can pause or discard a permanently failing intake. Aggregate operations data exposes identifiers for stuck work.

### 6. Graph writes and chunk deletion commit atomically

After an agent batch succeeds, generated notes, entities, and edges and deletion of the batch chunks must commit as one operation. No provenance fields are added to graph records. Atomic commit prevents a crash between output writes and queue acknowledgement from creating duplicate effects.

This decision requires an architecture for transaction-scoped agent writes or staged agent output. The current tool-driven ingest flow writes during the agent loop, so the transaction boundary must be designed explicitly.

### 7. Staging participates in recall

Recall searches processed notes and remaining intake chunks together. It fuses both layers with equal weight and candidate caps, then returns intake evidence in a separate, explicitly unprocessed context collection. Chunks disappear from recall immediately after successful processing.

Unprocessed evidence remains distinguishable from organized notes. It has no graph edges and must not appear as a graph node by accident.

### 8. Operations use aggregate visibility, not job polling

The ingest route no longer needs an asynchronous job lifecycle. Add aggregate pipeline introspection for queue counts, retry-wait counts, oldest work, worker health, recent errors, and stuck intake identifiers. Retain no completion receipt after the final chunk is deleted.

## Direction

1. Receive raw text and metadata through the existing `/ingest` route.
2. Chunk at natural boundaries without overlap.
3. Embed and atomically store all rows in `intake_chunk`.
4. Return the stored chunk count.
5. Let always-on workers claim the next contiguous chunks per intake.
6. Pack each processing batch to the model context budget.
7. Run the existing ingest reasoning flow against that batch.
8. Atomically commit organized graph writes and delete successful chunk rows.
9. Retry failures forever with leases and backoff, while allowing other intakes to proceed.
10. Include remaining chunks in recall as labeled unprocessed context.

## Open questions

### Sharp questions for architecting

- How can the current tool-driven PydanticAI ingest flow use a transaction that covers all graph writes and chunk deletion?
- What SurrealDB transaction and claim pattern provides safe leases, ordered per-intake processing, and recovery after process termination?
- Which fields identify an intake and chunk, and how does the worker find the next contiguous range after earlier rows are deleted?
- What tokenizer or conservative sizing rule controls chunk limits and processing-batch packing?
- What maximum request size keeps synchronous chunk preparation within HTTP and embedding-provider limits?
- How should global hybrid ranking fuse `note` and `intake_chunk` candidates, cap each layer, and preserve source labels and citations?
- How should recall response models represent unprocessed context without graph edges?
- What pause and discard operations belong in the aggregate operations API?
- How should worker startup, graceful shutdown, provider timeouts, and multiple app instances interact with leases?

### Fog

- The exact metadata carried on every chunk, including source, hints, and timestamps.
- Whether the existing agent can retain its search-and-decide behavior inside a transaction without a staged output model.
- The right initial concurrency, backoff limits, and model token budget after observing real workloads.
