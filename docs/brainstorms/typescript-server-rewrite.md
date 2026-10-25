# Brainstorm: TypeScript server rewrite

## The idea

Replace the Python server with a TypeScript server built and run with Bun. Use the Pi TypeScript SDK instead of PydanticAI, keep the existing SurrealDB data, and preserve the non-conversation HTTP service. Remove MCP and conversation mode.

## Key decisions

- **Big-bang server replacement.** Build the complete Bun server before the cutover. A single replacement keeps the migration boundary clear and avoids Python and TypeScript implementations drifting.
- **HTTP scope.** Preserve every existing non-conversation endpoint, payload, status, and workflow contract. Remove `/converse` and `/converse/stream`. Conversation mode is intentionally not part of the replacement API.
- **Client scope.** Do not change the Go or Flutter clients in this work. Their conversation paths become stale follow-up work because the server no longer exposes those routes.
- **Database compatibility.** Open the existing SurrealDB file directly. Keep tables, fields, record IDs, indexes, vectors, and existing records unchanged. The TypeScript server must not require a data migration.
- **Runtime configuration.** Intentionally introduce a Pi-native model surface. Expose one required `provider/model:effort` string per workflow, such as `BRAIN_INGEST_MODEL`, `BRAIN_RECALL_MODEL`, and `BRAIN_DREAM_MODEL`. Keep embeddings separate because existing vectors must remain compatible. Remove Jev, old reasoning-provider settings, and other conversation-only settings.
- **Workflow compatibility.** Preserve database effects, queue leasing and retry semantics, citations, strict output validation, dream scheduling, and lifecycle behavior. Prompt wording and model answer wording can change.
- **Pi session model.** Use Pi idiomatically with request-scoped in-memory sessions. Ingest and recall use one session per operation. Dream remains one workflow but runs separate sessions for its deduplication and connection phases. Do not persist transcripts or reuse sessions across requests.
- **Agent tool surface.** Enable Pi Codemode alongside direct knowledge-domain tools. Do not expose Pi filesystem, shell, network, or MCP tools, and disable Codemode model-catalog access. Every domain tool must expose structured results so direct calls and Codemode scripts share one contract.
- **Tool ergonomics.** Keep ordinary operations singular so a model can call a tool repeatedly in one turn. Store nodes and edges are create-only. Edges use canonical IDs. Node updates use one exact old-text/new-text replacement. Node and edge merges remain explicit graph operations.
- **Structured validation.** Validate tool arguments and structured results at the server seam. Do not require models to count positional references or generate internal IDs. Return actionable failures instead of silently accepting ambiguous writes. Mutation tools share one short SurrealDB transaction per assistant message; earlier committed messages remain after later failures.
- **Embeddings.** Use a direct provider adapter for embeddings. Keep the configured embedding model, dimensions, and existing vector compatibility while Pi owns agent and model orchestration.
- **Bun scope.** Use Bun for package installation, runtime, tests, and the production image. Remove Python from the server runtime image.
- **Architecture latitude.** The architecture may reshape module boundaries. It must read the Pi SDK documents and choose seams that use Pi well without weakening the database and HTTP contracts.
- **Acceptance bar.** Port the server test coverage to Bun and TypeScript, add database compatibility and HTTP contract checks, cover queue and scheduler behavior, test direct and Codemode tool calls, and run manual smoke tests.

## Direction

Create a Bun-native TypeScript server whose architecture is shaped by Pi's session, tool, model, and resource seams. Keep SurrealDB and the public non-conversation service stable at the boundary. Use required Pi model strings with explicit thinking levels for each workflow, while retaining a separate embedding adapter for the existing vector space. Treat storage, domain operations, agent workflows, scheduling, configuration, provider adapters, and HTTP lifecycle as replaceable internal modules with explicit interfaces. Remove MCP and conversation concerns rather than carrying dead compatibility code.

## Open questions

### Sharp questions for architecting

- Which Elysia application and lifecycle seam preserves the current routes, status codes, error shapes, and startup/shutdown controls?
- Which Pi SDK session, resource-loader, Codemode, custom-tool, model, and test seams fit stateless server operations without enabling unrelated Pi capabilities?
- Which SurrealDB TypeScript driver and serialization layer can read the current embedded database and preserve record IDs, graph relations, vectors, and query behavior?
- How will required per-workflow `provider/model:effort` strings and standard Pi provider configuration map to model objects, including custom endpoints?
- How will forgiving tool inputs, canonical-ID references, exact node edits, graph rewrites, cancellation, and lease ownership work with Pi events and session completion?
- Which background lifecycle structure preserves ingestion workers, lease heartbeats, dream backoff, shutdown grace, and manual dream jobs under Bun?
- Which conversation-only files, dependencies, tests, and documentation must be removed while leaving unrelated client changes untouched?

### Fog

- The final module names and exact ownership of shared workflow utilities are not yet defined.
- The best Bun HTTP framework and package choices depend on the architecture investigation.
- The exact Pi test doubles and provider adapter decomposition depend on the SDK capabilities confirmed during architecting.
