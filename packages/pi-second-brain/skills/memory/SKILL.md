---
name: memory
description: Use when capturing, recalling, or organizing knowledge in the Second Brain graph. Covers the memory tools, the capture and recall workflows, and on-demand graph maintenance.
---

# Second Brain Memory

The brain is a graph. Notes hold captured facts and source attribution. Entities
hold people, projects, and concepts. Typed edges relate them.

## Recall

Use the user's question and conversation context to scope the research. Read
[recall.md](recall.md) before researching. Answer directly in the conversation
with supporting citations. For related nodes without a known text query,
`memory_find_similar` accepts a node ID.

## Capture

Identify what the user wants remembered. Use only evidence they provided or
identified. Read [ingest.md](ingest.md) before organizing it. Summarize what was
stored or reconciled and report unresolved issues.

For additional relationship discovery, `memory_suggest_edges` lists pairs
that share notes. Read those notes before judging a candidate relationship.

## Maintenance

Read [dream.md](dream.md) before doing graph maintenance.

## Tool map

Reads: `memory_search`, `memory_get_node`, `memory_explore`,
`memory_find_similar`, `memory_suggest_edges`.

Writes: `memory_store_node`, `memory_store_edge`, `memory_update_node`.

Maintenance, deferred until activated: `memory_merge_nodes`,
`memory_merge_edges`, `memory_remove_edge`, `memory_rename_edge_type`.
