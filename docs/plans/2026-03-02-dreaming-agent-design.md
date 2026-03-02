# Dreaming Agent Design

Background agent that runs when the server is idle, performing knowledge graph maintenance and enrichment in two phases: deduplication then connection discovery.

## Core Concept

The brain "dreams" when idle — consolidating knowledge, merging duplicates, and discovering latent connections. Dreams are interrupted when the brain "wakes up" (ingest or recall request arrives). Work is committed incrementally; partial cycles are fine.

## Dream Scheduler

Pure Python async task (not an LLM agent). Manages the dream lifecycle.

- **Idle detection** — Tracks last ingest/recall timestamp. Starts a dream cycle after `BRAIN_DREAM_IDLE_TIMEOUT` minutes of inactivity (default: 10).
- **Wake-up** — Any ingest/recall request sets a cancellation flag. The current atomic operation finishes, then the cycle stops. Partial work is committed.
- **Node selection** — Batch of `BRAIN_DREAM_BATCH_SIZE` (default: 10) nodes/edges sorted by `dream_age ASC, created_at DESC`. Freshly ingested nodes (dream_age=0) are always prioritized.
- **Phase orchestration:**
  1. Run **dedup agent** on the batch. Merges may pull in nodes from outside the batch. Fused nodes get `dream_age = max(inputs)`.
  2. Collect the **result set**: all nodes/edges looked at by dedup (minus deleted losers).
  3. Run **connect agent** on the result set.
  4. `dream_age += 1` on everything in the result set.
- **Lifecycle** — Starts with FastAPI lifespan as a background `asyncio.Task`. Disabled when `BRAIN_TEST_MODE=true` or `BRAIN_DREAM_ENABLED=false`.

### dream_age

Integer field on all nodes and edges (default 0). Tracks how many dream cycles have consulted a given record. Decoupled from creation time — a recently ingested node has dream_age 0 regardless of when "older" nodes were last dreamt on. This ensures new knowledge is always processed promptly while the full graph is eventually revisited.

When merging:
- Fused node/edge gets `dream_age = max(inputs)` (no increment yet).
- Auto-deduplicated edges during node merges also get `dream_age = max(inputs)`.
- The +1 increment happens once at the end of the full cycle for everything in the result set.

## Phase 1: Dedup Agent

PydanticAI agent focused on finding and fusing duplicate entities, notes, and edges.

### Dependencies

`DedupDeps(db, embed_fn, cancel_flag)`

### Strategy

For each node in the batch, find semantically similar nodes via embedding similarity. The LLM judges whether candidates are true duplicates and decides how to fuse them. All edge re-pointing and cleanup is deterministic tool logic.

### Tools

- **`find_similar(db, record_id, embed_fn, k)`** — Pure vector search. Grabs the node's embedding from DB, queries same-table nearest neighbors. Returns top-k with cosine similarity scores, embeddings stripped. LLM sees content + scores, decides which (if any) are duplicates.
- **`merge_nodes(db, ids, new_fields, embed_fn)`** — Fuses N nodes into one. Re-points all edges from losers to winner. Auto-merges duplicate edges (same table + direction + target + label): surviving edge gets `dream_age = max(inputs)`, duplicate deleted. Re-embeds with new text. Fused node gets `dream_age = max(inputs)`. Deletes losers. Returns surviving node + all touched node/edge IDs.
- **`merge_edges(db, ids, new_context)`** — Fuses N edges between the same node pair (same table + direction but different labels the LLM deems equivalent). Surviving edge gets `dream_age = max(inputs)`. Deletes losers.
- **`get_node(db, record_id)`** — Existing tool. Fetch full node content.

### LLM responsibilities

Semantic judgment only: "are these duplicates?" and "what should the fused text say?" The LLM provides combined names/content/descriptions. Deterministic code handles everything else.

## Phase 2: Connect Agent

PydanticAI agent focused on discovering missing relationships between existing nodes.

### Dependencies

`ConnectDeps(db, embed_fn, cancel_flag)`

### Input

The result set from the dedup phase.

### Strategy

Explore the graph structurally to find nodes that should be connected but aren't. Prefer structural patterns (shared references, multi-hop paths) over pure embedding similarity. Fall back to similarity for structurally isolated nodes.

### Tools

- **`explore(db, record_id, direction, node_types, depth)`** — Traverses up to N hops from a node. `direction` is `"out"`, `"in"`, or `"both"`. `node_types` filters which types are returned as targets (e.g., `["entity"]`). Returns target-type nodes with full content + the path taken to reach each (intermediate node IDs and edge labels). LLM can then `get_node` on interesting intermediaries. Depth bounded to 2-3 max.
- **`find_unlinked_cooccurrences(db, record_id)`** — Fast-path for the entity→note→entity pattern. For an entity, finds other entities that share notes via `references` edges but have no direct `relates_to` edge. Returns unlinked entity pairs + shared note IDs.
- **`get_node(db, record_id)`** — Existing tool. Drill into intermediate nodes when a path looks interesting.
- **`find_similar(db, record_id, embed_fn, k)`** — Shared with dedup agent. Fallback for structurally isolated nodes.
- **`create_edges(db, edges)`** — Existing tool. Bulk edge creation with semantic labels.

### LLM responsibilities

Reads structural candidates and node content, decides whether a real relationship exists, and picks meaningful edge labels. System prompt steers toward structural exploration first, similarity as fallback.

## Schema Changes

Add `dream_age` integer field (default 0) to:
- `note` table
- `entity` table
- All edge tables (`references`, `relates_to`, `derived_from`, and any future edge tables)

No new tables or indexes.

## Configuration

New settings in `config.py` (all with `BRAIN_` prefix):

| Variable | Type | Default | Description |
|---|---|---|---|
| `BRAIN_DREAM_ENABLED` | bool | `true` | Enable/disable dreaming |
| `BRAIN_DREAM_IDLE_TIMEOUT` | int | `10` | Minutes of inactivity before dreaming starts |
| `BRAIN_DREAM_BATCH_SIZE` | int | `10` | Number of nodes per dream cycle |

## API & Observability

- No new REST endpoints. Dreaming is a background process.
- Wake-up mechanism: `/ingest` and `/recall` endpoints update `last_activity` timestamp.
- Observability via logging only (no status endpoint for now).

## File Structure

### New files

- `src/second_brain/agents/dream_dedup.py` — Dedup agent
- `src/second_brain/agents/dream_connect.py` — Connect agent
- `src/second_brain/tools/dream_tools.py` — `find_similar`, `merge_nodes`, `merge_edges`, `explore`, `find_unlinked_cooccurrences`
- `src/second_brain/scheduler.py` — Dream scheduler

### Modified files

- `src/second_brain/db.py` — Add `dream_age` field to all tables
- `src/second_brain/app.py` — Start scheduler in lifespan, track last_activity on ingest/recall
- `src/second_brain/config.py` — Add dream config values
