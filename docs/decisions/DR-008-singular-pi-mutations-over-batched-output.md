# DR-008: Singular Pi Mutations Over Batched Structured Output

## Status
Accepted

## Context

Supersedes DR-001 (Batched Ingest Tool Over Structured Output), deleted at commit `417480b8bc81d0ca7f401a272109d662e79d0008`.

The Bun rewrite keeps an agent search-and-write loop but changes the mutation
boundary. The prior batch contract bundled entities, notes, and edges into one
model response with positional references. That contract could lose partial
progress and required the model to resolve intra-call indexes. The new intake
pipeline leases evidence at least once, and each mutation must commit before a
later model turn can fail.

## Decision

Use singular `storeNode`, `storeEdge`, and exact `updateNode` Pi tools. Require
canonical IDs for existing endpoints. Keep direct tools active beside Codemode,
which lets capable models compose calls while less capable models can call each
operation directly. Keep node merges, edge merges, removals, and edge-type
renames as separate atomic domain calls.

The ingest workflow submits chunks in source order and reports errors. The
pipeline acknowledges a lease only after a clean workflow result. Earlier
committed mutations remain when a later turn fails, so retries are explicitly
at-least-once.

## Consequences

- Mutation results return real canonical IDs immediately.
- Partial graph progress survives provider failures and process restarts.
- The model can issue more turns than the old batch contract required.
- Duplicate and self-edge handling moves into one deep knowledge module.
- Retry replay can repeat model decisions, so canonical-ID validation and graph
  deduplication remain mandatory.
