# Maintenance (Dream)

Maintenance runs in two phases over a batch of nodes. The server schedules
these phases automatically. In a Pi session, run them on demand.

## Batch selection

Pick the nodes with the oldest dream age. Entities first: deduplication only
needs entities. Then all nodes: connection benefits from notes too. Bound the
batch, 25 nodes is the server default.

## Phase one: deduplicate

For each entity in the batch:

1. `memory_find_similar` on the entity to get candidates.
2. `memory_get_node` on the entity and each candidate. Read names, types,
   descriptions, correction notes, and relationships. Merge only identities
   supported by evidence, not surface similarity. An explicit correction such
   as “X is actually Y” is strong identity evidence.
3. `memory_merge_nodes` with the corrected or better-supported name as the
   survivor, reconciling fields explicitly. Loser edges move to the survivor
   automatically. Same kind only. Do not create an alias edge instead.
4. `memory_update_node` for exact field corrections. Preserve captured note
   wording; source notes remain evidence of what was recorded.
5. `memory_remove_edge` for invalid relationships. `memory_rename_edge_type`
   to reconcile edge type names, which merges collisions.

## Phase two: connect

For the batch nodes:

1. `memory_suggest_edges` for pairs that share notes without an edge.
2. `memory_get_node` on the shared notes. Shared notes identify candidates,
   not proof of a relationship.
3. `memory_store_edge` only where the evidence supports a specific
   relationship. Use existing canonical IDs.

## Activation

The four mutation tools are deferred. Activate them with tool search
(`tool_search` with `memory_merge`, `memory_remove`, or `memory_rename`)
before use. They stay inactive in ordinary sessions.
