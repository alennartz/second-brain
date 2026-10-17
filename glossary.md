# Second Brain Glossary

Second Brain stores, retrieves, and refines knowledge for humans and agents.

## Language

**Intake document**:
A logical source submission represented by an ordered set of document chunks while the ingestion pipeline processes it.
_Avoid_: queue item, ingest job, unprocessed document

**Document chunk**:
An ordered segment of an intake document, stored and indexed for hybrid search until processed.
_Avoid_: staging chunk, unprocessed note

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
- The **ingestion pipeline** packs eligible **document chunks** into one **processing batch**.
- A **document chunk** is **unprocessed evidence** until the pipeline acknowledges a clean processing batch.
