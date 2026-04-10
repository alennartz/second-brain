# Structured Ingest

## The Idea

Replace the granular ingest tool surface with a single `store_knowledge` tool that lets the agent plan all creates (entities, notes, edges) in one tool call, cutting LLM round trips from ~8 to ~3.

## Problem

Each ingest currently makes ~8.3 LLM round trips on average (measured over 12 snippets). The agent calls `search_knowledge`, then `create_entities`, then `create_notes`, then `create_edges` as separate tool calls, each requiring a full LLM round trip. At ~3-5s per round trip to gpt-5.2, a single ingest takes ~30s. This is the dominant cost — DB operations and embeddings are fast by comparison.

The granular tool surface also leads to the agent making poor search decisions (6 separate searches for one snippet instead of 1-2 broad ones) and underusing `get_node`/`update_node` for dedup against existing knowledge — something that will matter more as the graph grows.

## Key Decisions

### Single `store_knowledge` tool replaces three create tools

Instead of `create_notes` + `create_entities` + `create_edges` as separate tools, one `store_knowledge(entities, notes, edges)` tool creates everything in a single call. The agent still has a tool loop — it searches, sees results, then calls `store_knowledge` with a complete plan. This preserves agent flexibility (it can still search multiple times, store incrementally, etc.) while making the common path fast.

**Why not structured output (no agent loop)?** The agent loop is valuable for dedup — the agent needs to see search results before deciding what to create. As the graph grows, the search→decide→store cycle becomes more important, not less. Eliminating the loop would sacrifice dedup quality for speed. The bottleneck is tool granularity, not the loop itself.

### Reference scheme for edges

Edges can connect entities/notes created in the same call. Since IDs don't exist yet at plan time, the agent uses index references: `new_entity:0`, `new_note:1`, etc. The tool creates entities and notes first, builds an index→ID map, then resolves edge references.

Edge `from_ref` and `to_ref` accept either:
- Real record IDs for existing things (e.g., `entity:abc123`)
- Index references for things in the same call (e.g., `new_entity:0`, `new_note:2`)

### Return value is a summary, not full records

The tool returns a compact summary — entity names with assigned IDs, note IDs, edge/error counts. Enough for the agent to reference in its output and for follow-up `update_node` calls, but doesn't bloat context with full records.

```json
{
    "entities_created": [{"ref": "new_entity:0", "id": "entity:abc123", "name": "Von Braun"}],
    "notes_created": [{"ref": "new_note:0", "id": "note:xyz789"}],
    "edges_created": 5,
    "edges_skipped": 1,
    "errors": []
}
```

### `get_node` and `update_node` stay separate

Updates (enriching an existing entity's description after finding it via search) are a different judgment call from bulk creation. Keeping them separate avoids adding complexity to `store_knowledge` and keeps the common path simple.

## Direction

New tool surface for ingest:

| Tool | Purpose | Change |
|------|---------|--------|
| `search_knowledge` | Search existing DB | Unchanged |
| `store_knowledge` | Bulk create entities + notes + edges | **New** — replaces `create_notes`, `create_entities`, `create_edges` |
| `get_node` | Fetch a specific node | Unchanged |
| `update_node` | Modify existing node | Unchanged |

Expected flow: search → store → summary (3 LLM round trips vs ~8 today).

## Open Questions

- **Prompt tuning**: The system prompt needs to instruct the agent to use one broad search and one store call. Current prompt encourages per-entity searching. This is a separate change from the tool surface.
- **Embedding batching**: `store_knowledge` should batch-embed all entities and notes in as few API calls as possible (already partially implemented).
- **Error handling during execution**: If entity creation succeeds but edge creation fails mid-way, the tool should report partial results, not fail entirely. The agent can decide what to do.
- **Experiment infrastructure**: Need parallel multi-run experiments to measure the impact with variance bounds before/after this change.
