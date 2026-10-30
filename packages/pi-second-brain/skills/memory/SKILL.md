---
name: memory
description: Use when capturing, recalling, or organizing knowledge in the Second Brain graph. Covers the memory tools, the capture and recall workflows, and on-demand graph maintenance.
---

# Second Brain Memory

The brain is a graph. Notes hold captured text. Entities hold people, projects,
and concepts. Typed edges relate them. A `references` edge from a note to an
entity records that the note is evidence for the entity.

## Recall

Answer questions from stored knowledge.

1. `memory_search` with the question text. It returns notes, entities, and
   unprocessed evidence.
2. `memory_get_node` or `memory_explore` on the returned IDs to verify and to
   follow relationships.
3. Answer using only IDs returned in this session. When nothing matches, say
   so. Never invent citations.
4. For related nodes without a known query, `memory_find_similar` takes a node
   ID.

## Capture

Store new knowledge.

1. One `memory_store_node` per independent fact. `kind: "note"` for source
   text, `kind: "entity"` for people, projects, and concepts.
2. `memory_store_edge` with type `references` from each note to the entities
   it evidences. Endpoints must already exist.
3. `memory_suggest_edges` lists entity pairs that share notes without an edge.
   Candidates, not proof. Verify the shared notes before storing.
4. `memory_update_node` applies one exact text edit. `oldText` must match the
   current value exactly once.

Long documents: store one note per paragraph or section, then link. Do not
merge captures into existing notes. Each call creates a new node.

## Maintenance

Merging and edge cleanup use deferred tools that are not declared until
activated. Read `dream.md` in this directory before doing maintenance work.
The maintenance procedure accepts target IDs from its host. It does not assume
that it must select a batch itself.

## Tool map

Reads: `memory_search`, `memory_get_node`, `memory_explore`,
`memory_find_similar`, `memory_suggest_edges`.

Writes: `memory_store_node`, `memory_store_edge`, `memory_update_node`.

Maintenance, deferred until activated: `memory_merge_nodes`,
`memory_merge_edges`, `memory_remove_edge`, `memory_rename_edge_type`.
