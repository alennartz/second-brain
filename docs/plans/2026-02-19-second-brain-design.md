# Second Brain — Design Document

An API-first personal knowledge engine with an embedded database and agentic LLM loops.

## Problem

Memory and recall: losing context, forgetting connections between ideas, inability to surface past thinking when it's relevant. The tool should remember everything, find connections, and proactively surface related knowledge.

## Stack

- **Language:** Python
- **API:** FastAPI
- **Database:** SurrealDB (embedded, in-process via SurrealKV on disk)
- **LLM:** Provider-agnostic via a library (e.g., LiteLLM, Pydantic AI). Embedding and reasoning models can differ and are configurable.

## Architecture

```
┌─────────────────────────────────────────────┐
│           Any Frontend (later)              │
│       CLI / Chat UI / Web App / MCP         │
└──────────────────┬──────────────────────────┘
                   │ REST API
┌──────────────────▼──────────────────────────┐
│             FastAPI Application              │
│                                              │
│  ┌───────────────┐   ┌───────────────────┐   │
│  │ Ingest Agent  │   │  Recall Agent     │   │
│  │               │   │                   │   │
│  │ Tools:        │   │ Tools:            │   │
│  │  search_*     │   │  vector_search    │   │
│  │  create_note  │   │  full_text_search │   │
│  │  create_entity│   │  hybrid_search    │   │
│  │  create_edge  │   │  graph_traverse   │   │
│  │  update_node  │   │  get_node         │   │
│  │  embed        │   │  get_connections  │   │
│  └───────┬───────┘   └────────┬──────────┘   │
│          │                    │               │
│  ┌───────▼────────────────────▼────────────┐ │
│  │    SurrealDB (embedded, in-process)     │ │
│  │                                          │ │
│  │  Vectors (HNSW) │ Graph (→/←) │ FTS     │ │
│  │  Hybrid search  │ SurrealKV on disk     │ │
│  └──────────────────────────────────────┘    │
└──────────────────────────────────────────────┘
```

Everything runs in a single process. No external services required beyond LLM API calls.

## Core Components

### Ingest Agent

An agentic LLM loop that handles smart intake of knowledge. When raw input arrives (text, future voice transcription, etc.), the agent:

1. Parses the input into discrete ideas
2. Extracts entities (people, projects, concepts, tools)
3. Searches the existing graph to resolve references ("that GTD thing I was exploring")
4. Creates notes, entities, and relationship edges
5. Generates and stores embeddings for new nodes
6. Surfaces non-obvious connections to existing knowledge

The agent has access to both read and write tools, allowing it to iteratively explore the existing knowledge space while ingesting new content. This means graph relationships are built inline during ingestion, not as a separate batch process.

### Recall Agent

An agentic LLM loop that iteratively explores the knowledge space to answer questions. Rather than a fixed retrieve-then-reason pipeline, the agent:

1. Receives a question
2. Uses search and graph tools to explore relevant knowledge
3. Follows threads — pulls on graph edges, refines queries based on findings
4. Continues exploring until it has sufficient context
5. Synthesizes a final answer from everything it found

This allows for multi-hop reasoning: a vector search surfaces a note, the agent follows a graph edge to a related entity, discovers an unexpected connection, searches again, and builds a rich answer.

### Embedding

A utility function called by the agents when writing vectors to SurrealDB. The embedding model is configured separately from the reasoning model (e.g., a cheap/fast embedding model paired with a strong reasoning model).

## Data Model

### Node Tables

**`note`** — A discrete unit of knowledge.
- `content`: string — the raw text
- `summary`: string — LLM-generated summary
- `embedding`: vector — for semantic search
- `source`: string — origin ("voice", "cli", "import")
- `created_at`: datetime
- `updated_at`: datetime

**`entity`** — A named concept extracted from notes.
- `name`: string
- `type`: string — person, project, concept, tool, etc.
- `description`: string
- `embedding`: vector

### Edge Tables

- **`references`** (`note` → `entity`) — "this note mentions this concept"
- **`relates_to`** (`entity` → `entity`) — "these concepts are connected", with a `context` field explaining why
- **`derived_from`** (`note` → `note`) — "this idea builds on that one"

### Indexes

- HNSW vector index on `note.embedding` and `entity.embedding`
- Full-text index on `note.content` and `entity.name`

The schema is intentionally minimal. SurrealDB is schemaless, so new node and edge types are cheap to add as use cases evolve.

## API Surface

Minimal to start:

- `POST /ingest` — Send raw text, the Ingest Agent processes it
- `POST /recall` — Ask a question, the Recall Agent explores and answers
- `GET /notes` — List/search notes
- `GET /entities` — List/search entities
- `GET /graph/{id}` — Get a node and its connections

## Deferred

These are explicitly out of scope for the initial build but the architecture supports them:

- **Frontend/UI** — API-first means any frontend can be added later
- **Voice input** — Just another ingestion source, feeds text to the Ingest Agent
- **Proactive suggestions** — Background jobs that periodically scan for new connections
- **Authentication** — Not needed for personal single-user use initially
- **Multi-user** — Single user for now
- **MCP server** — Expose the brain as an MCP server for use from Claude Code or other tools

## Key Design Decisions

1. **Embedded database** — SurrealDB runs in-process. No server to manage, smallest possible footprint. Data is a directory on disk.
2. **Agentic loops over fixed pipelines** — Both ingest and recall are LLM agent loops with tools, not rigid extract-then-store or retrieve-then-reason pipelines. The LLM decides how to explore.
3. **Provider-agnostic via library** — No custom LLM adapter. Use an existing library for provider switching. Configure, don't wrap.
4. **Graph relationships built at ingest time** — The Ingest Agent resolves references and builds edges inline, not as a post-processing step.
5. **API-first** — No frontend commitment. Build the engine, choose interfaces later.
