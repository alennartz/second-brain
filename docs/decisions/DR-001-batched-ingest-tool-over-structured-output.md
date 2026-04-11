# DR-001: Batched Ingest Tool Over Structured Output

## Status
Accepted

## Context
The ingest agent was making ~8 LLM round trips per ingest — separate tool calls for `create_entities`, `create_notes`, and `create_edges`, each requiring a full round trip. At ~3-5s per round trip, a single ingest took ~30s. Two approaches to reduce this:

1. **Structured output (no agent loop):** The LLM returns a structured object with all entities, notes, and edges. No tool loop at all — one LLM call, one DB write.
2. **Batched tool (keep agent loop):** Collapse the three create tools into one `store_knowledge` tool. The agent still searches, sees results, then calls `store_knowledge` once with everything. Reduces round trips from ~8 to ~3.

## Decision
Chose the batched tool approach. The agent loop is preserved because the search→decide→store cycle is where dedup happens — the agent needs to see existing knowledge before deciding what to create. As the graph grows, dedup quality matters more, not less. Eliminating the loop would trade dedup accuracy for speed at exactly the point where accuracy becomes most valuable.

The bottleneck was tool granularity (three separate create calls that could be one), not the agent loop itself. Batching creates solves the round-trip problem without sacrificing the LLM's ability to reason about what already exists.

## Consequences
- Ingest round trips drop from ~8 to ~3, roughly halving wall-clock time per ingest.
- The agent loop remains, meaning ingest is still slower than a single structured-output call would be. If dedup proves unnecessary in practice (e.g., the graph stays small, or dedup is handled well enough by dream agents post-hoc), this trade-off could be revisited.
- The `store_knowledge` tool introduces an index-based reference scheme (`new_entity:N`, `new_note:N`) for intra-call cross-references, adding a contract between the LLM and the tool that the LLM must follow correctly.
- The old granular create tools (`create_notes`, `create_entities`, `create_edges`) remain as internal functions — they're still used by dream agents and composed inside `store_knowledge`.
