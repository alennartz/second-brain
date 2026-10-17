# DR-003: Synchronous Intake Chunks with At-Least-Once Background Ingestion

## Status
Accepted

## Context

Direct ingestion made the HTTP request wait for the reasoning agent and required the agent to hold the entire input in context. Large inputs also needed a searchable representation before the agent could process them in manageable batches. The system already has hybrid search and graph deduplication, so the new intake path needed to preserve fast search visibility without creating a second permanent document model.

The main trade-off was crash consistency. A transaction-scoped write set or structured-output agent could make graph writes and queue deletion atomic, but both would change the existing tool-driven ingest loop. The existing loop searches, decides, and stores together because deduplication depends on that interaction.

## Decision

Represent each intake submission as ordered rows in one `intake_chunk` table. The HTTP and MCP intake operations synchronously chunk and embed the input, store all chunks, and return when the rows are searchable. The rows form both the durable work queue and a temporary, explicitly unprocessed layer of memory.

An always-on in-app worker claims context-sized batches, runs the existing tool-driven ingest agent, and deletes successful chunks. Failures return to the queue with leases and capped exponential backoff. A crash after graph writes but before chunk deletion replays the batch. The agent searches existing knowledge during replay, and later dream cycles consolidate duplicates. This is intentionally at-least-once rather than transactionally exactly-once.

Recall searches organized notes and remaining intake chunks together, but returns unprocessed evidence separately from graph nodes and edges. Completed chunks disappear from that layer when the worker deletes them.

## Consequences

- Intake acknowledgement is fast and means "searchable," not "organized."
- The queue needs leases, retry state, pause/discard controls, and operational introspection.
- The system accepts duplicate graph writes after crashes. Search-based deduplication and dreaming carry that cost.
- No separate full-source table or external queue broker is required. Ordered chunks are the source representation.
- Unprocessed recall evidence must be projected so queue credentials and lease metadata never reach agents or clients.
- Worker shutdown and model failures can replay work. Operators must treat chunk deletion as the completion boundary.

Structured-output ingestion was rejected because it removes the iterative search-and-decide loop captured by DR-001. A transaction-scoped write set was rejected because the installed embedded SurrealDB client does not expose a transaction object across the separate storage calls used by that loop. A separate full-source table was rejected because the worker already limits each processing batch and does not need the original input in one record.
