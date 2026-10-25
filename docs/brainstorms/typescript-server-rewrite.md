# Brainstorm: TypeScript server rewrite

## The idea

Replace the Python server with a TypeScript server built and run with Bun. Use the Pi TypeScript SDK instead of PydanticAI, keep the existing SurrealDB data, and preserve the non-conversation HTTP service. Remove MCP and conversation mode.

## Key decisions

- **Big-bang server replacement.** Build the complete Bun server before the cutover. A single replacement keeps the migration boundary clear and avoids Python and TypeScript implementations drifting.
- **HTTP scope.** Preserve every existing non-conversation endpoint, payload, status, and workflow contract. Remove `/converse` and `/converse/stream`. Conversation mode is intentionally not part of the replacement API.
- **Client scope.** Do not change the Go or Flutter clients in this work. Their conversation paths become stale follow-up work because the server no longer exposes those routes.
- **Database compatibility.** Open the existing SurrealDB file directly. Keep tables, fields, record IDs, indexes, vectors, and existing records unchanged. The TypeScript server must not require a data migration.
- **Runtime compatibility.** Preserve active `BRAIN_` configuration names and operational controls. Remove Jev and other conversation-only settings because their feature is gone.
- **Workflow compatibility.** Preserve database effects, queue leasing and retry semantics, citations, strict output validation, dream scheduling, and lifecycle behavior. Prompt wording and model answer wording can change.
- **Pi session model.** Use Pi idiomatically with one in-memory session per ingest, recall, or dream operation. Do not persist transcripts or reuse sessions across requests.
- **Agent tool surface.** Give agents only knowledge-domain tools. Do not expose Pi filesystem, shell, network, default resource, or MCP tools.
- **Structured output.** Keep strict validation for ingest plans and recall outputs. Invalid output must cause bounded repair or a controlled failure, not silent best-effort acceptance.
- **Embeddings.** Use a direct provider adapter for embeddings. Keep the configured embedding model, dimensions, and existing vector compatibility while Pi owns agent and model orchestration.
- **Bun scope.** Use Bun for package installation, runtime, tests, and the production image. Remove Python from the server runtime image.
- **Architecture latitude.** The architecture may reshape module boundaries. It must read the Pi SDK documents and choose seams that use Pi well without weakening the database and HTTP contracts.
- **Acceptance bar.** Port the server test coverage to Bun and TypeScript, add database compatibility and HTTP contract checks, cover queue and scheduler behavior, and run manual smoke tests.

## Direction

Create a Bun-native TypeScript server whose architecture is shaped by Pi's session, tool, model, and resource seams. Keep SurrealDB and the public non-conversation service stable at the boundary. Treat storage, domain operations, agent workflows, scheduling, configuration, provider adapters, and HTTP lifecycle as replaceable internal components with explicit interfaces. Remove MCP and conversation concerns rather than carrying dead compatibility code.

## Open questions

### Sharp questions for architecting

- Which HTTP framework or Bun-native server seam preserves the current routes, status codes, streaming behavior that remains, and lifespan controls?
- Which Pi SDK session, resource-loader, custom-tool, model, and test seams fit stateless server operations without enabling unrelated Pi capabilities?
- Which SurrealDB TypeScript driver and serialization layer can read the current embedded database and preserve record IDs, graph relations, vectors, and query behavior?
- How will existing `BRAIN_` model strings, provider authentication modes, Azure Foundry settings, self-hosted OpenAI-compatible endpoints, and Pi model identifiers map without deployment changes?
- How will strict ingest-plan and recall-output validation, bounded retries, usage limits, cancellation, and lease ownership work with Pi events and session completion?
- Which background lifecycle structure preserves ingestion workers, lease heartbeats, dream backoff, shutdown grace, and manual dream jobs under Bun?
- Which conversation-only files, dependencies, tests, and documentation must be removed while leaving unrelated client changes untouched?

### Fog

- The final module names and exact ownership of shared workflow utilities are not yet defined.
- The best Bun HTTP framework and package choices depend on the architecture investigation.
- The exact Pi test doubles and provider adapter decomposition depend on the SDK capabilities confirmed during architecting.
