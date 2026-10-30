# Maintenance (Dream)

Use this procedure for knowledge-graph maintenance. The host supplies the target
nodes and the current phase.

## Target selection

Treat node IDs in the request as the authoritative target set.

- Process every supplied target ID that still exists.
- Do not select a different batch or wait for another selector.
- A server scheduler can supply entity IDs for deduplication and all-node IDs for
  connection discovery.
- A direct Pi session can supply IDs from the caller's request or its own
  selection procedure. Do not assume either host context when IDs are absent.

## Evidence and precedence

Use evidence, not surface similarity, to make identity decisions.

- Intake evidence exposes capture time. Graph nodes and edges expose freshness
  time, which is a recency signal derived from captured evidence when available.
- When a correction conflicts with older evidence, compare the source capture
  times when available. In a server dream, use freshness time when the original
  capture time is not exposed. Prefer a newer, supported correction for the
  canonical name and current fields.
- Capture time and freshness time do not describe when an event occurred.
- Preserve older facts and captured note wording. Do not rewrite source notes
  only to replace an older spelling.

## Deduplication phase

For every supplied entity:

1. Call `memory_find_similar` with a limit of 10.
2. Read the entity and each promising candidate with `memory_get_node`.
3. Use `memory_explore` when names, descriptions, correction notes, or
   relationships need confirmation.
4. Merge identities that represent the same real-world thing with
   `memory_merge_nodes`. Reconcile the survivor's `name`, `type`, and
   `description` explicitly in `survivorFields`.
5. Use `memory_update_node` for an exact field correction that does not require
   a merge.

Treat an explicit correction such as “X is actually Y” as strong identity
evidence. Keep the corrected name when the evidence supports it. Merge the old
or misspelled entity into the corrected canonical entity. Identical names with
compatible types are duplicates. Near-spelling variants are duplicates when
surrounding evidence identifies one thing. Do not merge merely related things or
different instances.

Choose the survivor with the corrected name, stronger and newer supporting
evidence, or more useful relationships. Node merging moves loser edges,
collapses duplicate relationships, and deletes losers. Do not create an alias
edge instead of merging.

## Connection phase

For each supplied node:

1. Call `memory_suggest_edges` for candidate pairs.
2. Read each shared note with `memory_get_node`.
3. Create `memory_store_edge` only when the evidence supports a relationship
   between distinct real-world nodes.

Shared notes identify candidates, not proof. A spelling correction or duplicate
identity is not a relationship. Deduplication merges those nodes first.

## Edge cleanup

Use `memory_remove_edge` for invalid relationships. Use
`memory_rename_edge_type` to reconcile supported edge type names. Use
`memory_merge_edges` only for duplicate relationships with the same ordered
endpoints. Successful mutations remain committed, so continue after each
successful operation.
