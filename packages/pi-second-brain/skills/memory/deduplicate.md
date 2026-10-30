# Deduplication

For each entity under review:

1. Call `memory_find_similar` with a limit of 10.
2. Read the entity and each promising candidate with `memory_get_node`.
3. Use `memory_explore` to inspect supporting notes and relationships.
4. Merge supported identities with `memory_merge_nodes`. Reconcile the
   survivor's `name`, `type`, and `description` in `survivorFields`.
5. Use `memory_update_node` for field corrections that do not require a merge.
6. Inspect the survivor's relationships and reconcile redundant or invalid edges.

## Identity and precedence

Use names, types, descriptions, and supporting evidence to judge identity.
Similarity identifies candidates, not proof. Matching names and compatible types
support a merge, but check for distinct instances or namesakes. Merge spelling
variants when the evidence identifies one thing. Keep related but distinct
entities separate.

An explicit correction such as “X is actually Y” is strong identity evidence.
Compare source capture times when deciding precedence between conflicting
corrections. When capture times are unavailable, use graph `freshnessAt` as a
recency signal. Prefer newer supported evidence, not recency alone. Neither
capture time nor freshness time describes when an event occurred.

Keep the supported canonical name. Choose one survivor and reconcile its fields
explicitly. Node merging moves loser edges, collapses duplicate relationships,
and deletes losers atomically. Merge duplicate identities rather than linking
them with alias edges. Preserve useful older facts and captured note wording.

## Edge cleanup

Use `memory_remove_edge` for invalid relationships. Use
`memory_rename_edge_type` to reconcile supported edge type names across the
whole graph. Use `memory_merge_edges` for redundant relationships with the same
ordered endpoints. Preserve distinct meanings and directions.

## Completion

Review each entity and its promising candidates. After a merge, inspect the
survivor and continue with entities that still exist. Successful mutations remain
committed. Report unresolved ambiguities and failures.
