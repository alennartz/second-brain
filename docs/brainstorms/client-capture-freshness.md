# Brainstorm: client capture and graph freshness

**Date:** 2026-10-27
**Status:** converged

## The idea

Add the time when a user records an intake document to Second Brain data. This is
not the time of the event described by a memory and not a server lifecycle time.
Agents must see the raw capture time on document chunks and a derived freshness
time on graph nodes and edges. They will use freshness as a recency signal when
resolving contradictions.

## Key decisions

### 1. Use two distinct concepts

**Chosen:**

- **Capture time** is one client-supplied RFC 3339 timestamp with its numeric UTC
offset. It records when the user chose to record one intake submission.
- **Freshness time** is the latest capture time associated with the information in
a graph node or edge.
- Existing `createdAt` and `updatedAt` remain server lifecycle timestamps.

**Why:** event time is a separate, more complex feature. Mixing it with recording
time or lifecycle time would make temporal reasoning unreliable.

### 2. Require a client timestamp for HTTP intake

**Chosen:** Require capture time on every intake request. Reject missing or
malformed values. Accept any valid RFC 3339 value with an offset. Preserve the
client representation and compare absolute instants in code. Do not normalize,
clamp, or compare against server time.

Capture time belongs to the idempotent request identity. A retry with the same
key, content, and time is the same intake. A different time with the same key is
a conflict.

**Why:** the client owns the recording decision. Server correction would hide
clock problems and make retries nondeterministic.

### 3. Use one capture time per intake submission

**Chosen:** Copy the request capture time to every document chunk created from
that intake document. Keep the batch-maximum propagation rule.

**Why:** one submission represents one user decision. The current queue also
claims a processing batch from one intake document. Per-chunk times would imply
separate decisions that the client does not make.

### 4. Propagate the batch maximum during ingestion

**Chosen:** Compute the maximum capture time in the claimed processing batch.
Expose each chunk's capture time in the ingest-agent input. Every node or edge
mutation from that ingest run receives:

`max(existing freshness time, batch maximum)`

Older chunks can still change graph content. Freshness never moves backward. A
mixed batch can give an older-only mutation the batch's newer time. This coarse
attribution is accepted for the first implementation; per-mutation evidence IDs
can come later.

**Why:** batch maximum is deterministic and avoids asking the agent to provide
metadata that storage must validate. The current one-intake batch shape makes the
usual case exact.

### 5. Expose freshness through graph reads

**Chosen:** Return chunk capture time and graph freshness time from the read
paths used by agents, including search, node reads, and graph exploration. Keep
dream workflows unchanged: they receive node IDs and fetch current records with
read tools rather than receiving injected node records.

The ingest prompt receives chunk metadata directly. The ingest mutation scope
supplies batch freshness to storage without trusting the agent to copy a value
into each tool call.

### 6. Keep maintenance separate from capture

**Chosen:**

- New ingest nodes and edges get the ingest batch freshness.
- Node and edge merges retain the maximum freshness among all inputs.
- Dream and deduplication exact edits preserve existing node freshness.
- Edges created during connection inherit the maximum freshness of their endpoint
  nodes.
- Legacy records and direct Pi writes use `createdAt` as a lifecycle fallback.
- Freshness remains one heuristic field; agents do not receive a basis such as
  `capture` or `lifecycle`.

**Why:** maintenance reorganizes existing information. It does not represent a
new user recording. Endpoint freshness gives inferred edges a deterministic
ordering without claiming that the relationship was directly captured.

## Direction

```text
client capture time
  -> intake request
  -> document chunks
  -> ingest-agent context
  -> batch freshness in mutation scope
  -> node and edge freshness
  -> agent read tools and recency-aware prompts
```

The recency instruction must treat freshness as evidence, not authority: prefer
newer supporting information when sources conflict, inspect older evidence, and
do not confuse freshness with the time an event occurred.

## Open questions

### Sharp questions

- Which storage representation preserves the original RFC 3339 offset while
  allowing deterministic absolute-instant comparison, including equal-instants
  with different offsets?
- How will concurrent ingest-agent sessions receive batch freshness without a
  shared mutable global context in the Pi bridge?
- Which schema, wire projections, tool output schemas, Go types, and Flutter
  models require the new metadata, and how will the `createdAt` backfill migrate
  existing graph records and edges?
- How will the client-generated timestamp be created and retained across the Go
  and Flutter capture flows while preserving the same idempotency key on retry?

### Fog

- Exact per-mutation evidence attribution may become necessary if mixed batches
  make recency bias too coarse.
- Named IANA time zones are deliberately deferred. An RFC 3339 offset preserves
  local time and offset but not zone identity.
- The lifecycle fallback makes legacy and direct Pi freshness less authoritative
  than client-derived freshness, but the first version will not expose that basis.
