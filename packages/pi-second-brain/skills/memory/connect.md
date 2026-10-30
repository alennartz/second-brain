# Connection discovery

For each node under review:

1. Use `memory_explore` to inspect its relationships and supporting notes.
2. Call `memory_suggest_edges` to discover entity pairs with shared notes.
3. Read the shared notes with `memory_get_node`. Check that candidates relate
   to the knowledge under review.
4. Use `memory_find_similar` to investigate nodes without useful structural
   connections.
5. Create `memory_store_edge` only when evidence supports a specific directed
   relationship between distinct real-world nodes. Use existing canonical IDs.

Shared notes and similarity identify candidates, not proof. Verify both endpoints
and the relationship before writing. A spelling correction or duplicate identity
is not a relationship. Leave identity reconciliation to deduplication.

When evidence conflicts, compare source capture times when available. Otherwise,
use `freshnessAt` as a recency signal, not absolute authority or event time.
Preserve useful older facts and captured note wording.

## Completion

Review each node for supported connections. Successful mutations remain
committed. Report unsupported candidates, unresolved ambiguities, and failures.
