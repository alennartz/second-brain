# Design Document

Living design document for Second Brain. For historical feature-specific designs and implementation plans see `docs/plans/`. This document aims to remain up to date with respect to the overall architecture and design decisions of the project. New design decisions are added here and obsolete ones are updated or removed as the project evolves. This document is intended for contributors to understand the rationale behind design choices and the overall structure of the codebase.

---

## Vision

People lose context and forget connections between ideas. Second Brain is a personal knowledge engine that remembers everything, finds connections, and surfaces related knowledge when asked. It is not a note-taking app — it is an active participant in recalling and structuring what you know.

## Architectural Principles

### Single-process, embedded database

SurrealDB runs in-process via `surrealkv://` with no external server. The entire system is one process and a directory on disk. This was chosen for the smallest possible operational footprint — nothing to install, configure, or keep alive beyond the server itself.

### Agent loops over fixed pipelines

Both ingest and recall are LLM agent loops with tools, not rigid extract-then-store or search-then-respond pipelines. The LLM decides how to explore the knowledge space iteratively — it can search multiple times, follow graph connections, refine its approach. This matters because knowledge work is inherently exploratory; a fixed pipeline would force premature decisions about what to search for or how to structure results.

### Provider-agnostic via library

Model wiring delegates to PydanticAI — no custom LLM adapter code. A model string like `openai:gpt-4o-mini` or `anthropic:claude-sonnet-4-5` passes through to the library, which handles provider differences. This means any provider PydanticAI supports works with zero application code changes.

### API-first, client-agnostic

The server exposes a REST API with no frontend assumptions. Clients (CLI, TUI, web, MCP) are separate concerns that consume the same endpoints. This was deliberate — the engine should be built and validated before committing to any particular interface.

### Deterministic operations stay out of the LLM

Embedding text is a deterministic computation. It should not round-trip through the LLM's context window. The same principle applies to graph traversal and search execution. Agent tools embed automatically on create and run search queries internally — the LLM reasons about *what* to search for and *what* to create, not *how* to embed or *how* to fuse search results.

## Data Model

The knowledge graph has two node types and three edge types:

- **`note`** — a discrete piece of knowledge (content, summary, embedding, source, timestamps)
- **`entity`** — a named concept or thing (name, type, description, embedding)
- **`references`** — note → entity (this note mentions this concept)
- **`relates_to`** — entity → entity (with optional context describing the relationship)
- **`derived_from`** — note → note (this note builds on that note)

The schema is intentionally minimal and schemaless (SurrealDB SCHEMALESS mode). Fields are defined but flexible. Both node types carry vector embeddings and are indexed with HNSW (cosine) for semantic search and BM25 analyzers for full-text search.

Relationships are built at ingest time by the Ingest Agent, not as a post-processing step. The agent has the full context of the new knowledge while ingesting and is best positioned to resolve references and create edges at that moment.

## Agents

### Ingest Agent

Parses input into notes and entities, searches existing knowledge for overlap and connections, creates graph relationships, and auto-embeds all new nodes. Has read+write access to the graph. The agent decides the structure — it may create one note or several, link to existing entities or create new ones.

### Recall Agent

Iteratively explores the graph via hybrid search and traversal. Can follow threads across multiple hops, refine searches based on intermediate results, and synthesize an answer with citations back to specific nodes. Read-only access to the graph.

### Converse Agent

A conversational router that wraps ingest and recall as internal tools. Supports multi-turn history. The user talks to one agent; it decides whether the intent is to store knowledge, retrieve knowledge, or both. Accumulates context across tool calls so a single conversational turn can involve multiple searches and ingestions.

## Search

Search uses hybrid retrieval: BM25 full-text search and HNSW vector similarity, fused with Reciprocal Rank Fusion (RRF). This was chosen because keyword search catches exact terms the embedding might miss, while semantic search catches meaning the keywords miss. RRF is simple and parameter-free — no tuning weights between the two signals.

The hybrid search is a single tool (`search_knowledge`) exposed to both agents. There are no separate full-text or vector search tools. The agent provides a query; the tool handles embedding, both search paths, and fusion internally.

## Provider Architecture

### Model resolution

The reasoning model and embedding model are configured independently via model strings (`BRAIN_REASONING_MODEL`, `BRAIN_EMBEDDING_MODEL`). Without a Foundry URL or custom base URL, model strings pass through to PydanticAI unless `BRAIN_REASONING_EFFORT` is set. The optional effort setting binds OpenAI reasoning effort to each model request and requires an `openai:` model. OpenAI-compatible base URLs are available independently for reasoning and embeddings.

### Azure Foundry support

Each concern (reasoning, embedding) can independently target an Azure AI Foundry endpoint. This was split into per-concern configuration because in practice, embeddings and reasoning often live on different Foundry resources, or one concern may use Foundry while the other uses a direct API.

Each concern has three knobs:
- **Foundry URL** — enables Foundry routing for that concern (unset = passthrough)
- **Auth mode** — `aad` (DefaultAzureCredential) or `key` (API key), defaulting to `key`
- **Explicit key** — optional override; when omitted, the SDK reads its own default env var

This gives full flexibility: direct OpenAI for embeddings + Foundry AAD for reasoning, or Foundry key-auth for both, or no Foundry at all.

## Client

A Go terminal application with two modes:

### CLI mode

One-shot commands (`brain ingest`, `brain recall`, `brain graph`) for scripting and quick interactions. Each maps directly to a server endpoint.

### TUI mode

An interactive split-pane interface: conversation panel (left) and graph panel (right). The user converses via the `/converse` endpoint while simultaneously exploring the knowledge graph visually.

The graph panel displays a curated subset — only nodes and edges the agent deemed relevant to its response, not the full subgraph it explored. This prevents cognitive overload. The user can independently expand nodes in the graph panel (via direct `GET /graph/{id}` calls) without triggering the LLM or disrupting conversation context.

Built with Cobra (CLI), Bubble Tea (TUI), and Lip Gloss (styling). Compiles to a single static binary.

## Developer Experience

### Pre-commit hooks

Quality gates run on `git commit` via the `pre-commit` framework, not on file save or in editor. This was chosen because the workflow involves parallel Claude Code sessions in the same directory — file-watching hooks would cause cross-session interference. Git hooks fire only on commit, keeping development unblocked while preventing bad code from entering the repository.

Hook order: ruff format → ruff check (with auto-fix) → basedpyright (type check) for Python; golangci-lint (format + lint) for Go. Tests are excluded to keep commits fast.

### Makefile as single entry point

All development commands (test, lint, build, docker, e2e) are Makefile targets. This makes workflows discoverable and provides a single reference point rather than requiring knowledge of multiple tool-specific invocations.

### Test mode

`BRAIN_TEST_MODE=true` swaps real LLM calls for PydanticAI's `TestModel()` and connects to an in-memory SurrealDB. This enables the full application to run without API keys — used in unit tests, Docker test profile, and e2e tests.

### Docker

Multi-stage Dockerfile (builder + slim runtime) for the server only — the Go client stays as a locally-built binary. Docker Compose provides two profiles: a production-like server on `:8000` (with `.env` and persistent volume) and a test server on `:8001` (with `BRAIN_TEST_MODE=true` and in-memory DB).

### E2E tests

Go tests in `client/e2e/` exercise the full HTTP API against the Docker test server. They validate HTTP contracts and response shapes, not LLM output quality (since `TestModel` returns deterministic placeholders). Gated behind a build tag (`//go:build e2e`) so they don't run during normal `go test`.
