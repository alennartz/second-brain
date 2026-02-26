# Tool Surface Redesign

## Problem

The current tool surface requires too many LLM round trips. Ingesting a paragraph with 3 entities needs 10+ tool calls: 3 dedup searches, 1 create_note, 3 create_entity, 3+ create_edge. Additionally, search results return raw nodes with no graph context, and the ingest agent cannot explore the graph at all.

## Design

### Enriched node results

Every node returned to the LLM (from `search_knowledge` or `get_node`) includes a `connections` list showing its edge neighborhood:

```json
{
  "id": "entity:abc",
  "name": "Python",
  "type": "language",
  "connections": [
    {"edge_label": "used_in", "direction": "out", "adjacent_id": "entity:xyz"},
    {"edge_label": "inspired_by", "direction": "in", "adjacent_id": "entity:def"}
  ]
}
```

Embeddings are stripped from all results returned to the LLM.

A shared helper `enrich_with_connections(db, record)` in `recall_tools.py` handles this. Both `search_knowledge` and `get_node` call it.

### Tool surface per agent

**Recall agent (2 tools):**

| Tool | Signature | Returns |
|---|---|---|
| `search_knowledge` | `(tables, query, k=5)` | List of enriched nodes |
| `get_node` | `(record_id)` | Single enriched node |

`get_connections` and `graph_traverse` are deleted.

**Ingest agent (6 tools):**

| Tool | Signature | Returns |
|---|---|---|
| `search_knowledge` | `(tables, query, k=5)` | Same as recall |
| `get_node` | `(record_id)` | Same as recall |
| `create_notes` | `(notes: list[{content, source?, summary?}])` | List of created records with IDs |
| `create_entities` | `(entities: list[{name, type, description?}])` | List of created records with IDs |
| `create_edges` | `(edges: list[{from_id, edge_table, to_id, context?}])` | List of created records with IDs |
| `update_node` | `(record_id, fields)` | Updated record |

### Typical ingest flow (3-4 round trips)

1. `search_knowledge` — find existing entities to deduplicate
2. `create_notes` — bulk create all notes
3. `create_entities` — bulk create only genuinely new entities
4. `create_edges` — bulk connect everything

### File changes

**`recall_tools.py`:**
- Add `enrich_with_connections(db, record)` helper
- Delete `get_connections()` and `graph_traverse()`

**`ingest_tools.py`:**
- `create_note` → `create_notes(db, notes, embed_fn)` — bulk, auto-embeds each
- `create_entity` → `create_entities(db, entities, embed_fn)` — bulk, auto-embeds each
- `create_edge` → `create_edges(db, edges)` — bulk RELATE
- `update_node` — unchanged

**`recall.py`:**
- Register `search_knowledge` and `get_node` with enrichment + embedding stripping
- Remove `get_connections` and `graph_traverse`

**`ingest.py`:**
- Register `search_knowledge` and `get_node` (same enrichment)
- Replace single-create tools with bulk versions
- System prompt already updated for semantic edge names and dedup

**`converse.py`:** No changes.

**Tests:** Update for new signatures, remove tests for deleted tools, add test for `enrich_with_connections`.

**CLAUDE.md:** Update architecture section.
