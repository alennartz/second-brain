# DR-002: Storage Layer Owns Embedding and Search Fusion, Tools Own Business Logic

## Status
Accepted

## Context
The db-storage-layer refactor consolidated all raw SurrealQL into a `Storage` class in `db.py`. The central design question was where to draw the abstraction boundary — what belongs inside Storage vs. what stays in tool files that compose Storage primitives.

Before the refactor, embedding was handled through three different patterns: a `BatchEmbedder` protocol in `ingest_tools.py`, bare `Callable[[str], Awaitable[list[float]]]` signatures passed through agent Deps, and manual embed calls in several places. RRF search fusion was duplicated between `recall_tools.py` and `dream_tools.py`. Meanwhile, complex operations like `merge_nodes` (30+ sequential DB calls with edge dedup strategy, dream_age handling, and cancel-event checks) lived alongside primitive CRUD in the same tool files.

## Decision
Storage owns three concerns: graph primitives (node/edge CRUD), embedding (auto-embed on create, auto re-embed when text fields change on update), and search fusion (hybrid BM25 + vector with RRF). An `Embedder` protocol is injected at construction — callers never handle vectors.

Complex multi-step operations — `merge_nodes`, `find_similar`, `explore`, `find_unlinked_cooccurrences`, `merge_edges` — stay in tool files and compose Storage primitives.

The guiding principle: if a different application using this graph DB would want the behavior, it belongs in Storage. Embedding and search fusion are inherent to how the knowledge graph works. Merge strategies, dedup policies, and traversal heuristics are application-specific business logic.

Rejected alternatives:
- **Thin pass-through wrapper** (wrapping SurrealQL in named functions without owning embedding or search) — leaves embedding scattered across three patterns and RRF fusion duplicated in two tool files. Callers still manage vectors.
- **Full-service layer** (merge, explore, dedup in Storage) — leaks business logic into the data layer. `merge_nodes` alone contains edge dedup strategy, dream_age arithmetic, and cancellation checks that have no business in a storage abstraction.

## Consequences
- Storage needs text-field-to-embedding semantics: notes embed `content`, entities embed `description` falling back to `name`. This is an application-level coupling inside what is otherwise a generic graph storage layer.
- No way to create a record without embedding — intentional for this system where every node participates in vector search.
- Tool files shrink to pure business logic, testable against Storage's interface rather than raw SQL. All `AsyncSurreal` imports, `RecordID` types, and SurrealQL strings are confined to `db.py`.
- The three pre-existing embedding patterns collapse into one `Embedder` protocol, eliminating a class of inconsistency bugs.
