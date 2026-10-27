# Second Brain Glossary

Second Brain stores, retrieves, and refines knowledge for humans and agents.

## Language

**Intake document**:
A logical source submission represented by an ordered set of document chunks while the ingestion pipeline processes it.
_Avoid_: queue item, ingest job, unprocessed document

**Document chunk**:
An ordered segment of an intake document, stored and indexed for hybrid search until processed.
_Avoid_: staging chunk, unprocessed note

**Capture time**:
The client-supplied RFC 3339 time, including its numeric UTC offset, when a user records an intake document. It describes recording time, not the event described by the document.
_Avoid_: event time, created time, updated time

**Freshness time**:
The timestamp used as a recency signal for information represented by a graph node or edge. It normally comes from the latest capture time, with lifecycle creation time as a fallback for legacy and direct records.
_Avoid_: updated time, last modified time, event time

**Intake staging**:
The synchronous operation that chunks, embeds, and stores source text before returning the stored chunk count.
_Avoid_: ingest job, completed ingestion

**Ingestion pipeline**:
The background worker system that claims document chunks, assembles processing batches, and runs the ingest agent.
_Avoid_: ingest job

**Unprocessed evidence**:
Document chunks that remain searchable before graph organization and appear separately from graph nodes and edges.
_Avoid_: unprocessed note, unprocessed document

**Pipeline snapshot**:
An aggregate view of queue counts, worker activity, and recent intake errors.
_Avoid_: job status

**Processing batch**:
The contiguous document chunks packed into one ingest-agent call.
_Avoid_: ingestion increment, chunk batch

## Relationships

- **Intake staging** creates one or more **document chunks** for an **intake document** and returns after they are searchable.
- A **document chunk** belongs to exactly one **intake document**.
- An **intake document** has one **capture time**, copied to each of its **document chunks**.
- The **ingestion pipeline** packs eligible **document chunks** into one **processing batch**.
- A **document chunk** is **unprocessed evidence** until the pipeline acknowledges a clean processing batch.
