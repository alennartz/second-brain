# Pi Memory Extension: Directions

Exploration notes for turning `packages/pi-second-brain` into a complete memory
system for arbitrary Pi sessions, while the Bun server keeps running in
parallel. Record of decisions made, constraints established, and directions
still open.

## What exists today

- `packages/pi-second-brain` ships twelve `memory_*` tools as idiomatic Pi
  extension files, a typed graph library (`lib/graph.ts`), TypeBox schemas with
  parameter descriptions, and a storage bridge (`lib/bridge.ts`).
- The bridge resolves storage in order: injected instance, injected config,
  `secondBrain` key in Pi settings. Secrets accept literal, `$NAME`, `!command`.
- Tool decoration follows the tool-design skill: one-line `promptSnippet` per
  tool, `outputSchema` everywhere, parameter descriptions, defaults in
  descriptions, `readOnlyHint` on reads, guidelines only for cross-tool
  routing.
- The Bun server loads the package through `additionalExtensionPaths` against
  an in-memory settings manager, whitelists tools by name per workflow, and
  passes workflow prompts through `systemPromptOverride`.
- Direct Pi use registers the package through `.pi/settings.json`. Relative
  package sources resolve from the settings file directory, so the entry is
  `../packages/pi-second-brain`.
- Two databases by design. The server owns `BRAIN_DB_PATH`; Pi sessions use
  `data/pi-local.surreal`. Direct tool use is intentionally separate from the
  server: a local brain, not a view of the server's. Consolidation happens
  later by pointing Pi sessions at the server as clients instead of using
  local shared tools.

## Established constraints

**System prompt anatomy.** A set `customPrompt` (what `systemPromptOverride`
provides) replaces the preamble and suppresses the default `tools`, `rules`,
and `docs` sections. The `<cwd>` section always renders. Server sessions
therefore see: workflow prompt plus cwd, nothing else. `promptSnippet` and
`promptGuidelines` are inert in server sessions; they pay off only in direct
Pi use where the default preamble path renders them. Tool declarations
(description, parameter schemas) reach the model in both contexts.

**Module boundary.** Extensions load through jiti with a separate module
registry. They cannot import server module instances. The `globalThis` bridge
is the only in-process channel and works in both directions.

**Package resources.** Core Pi packages carry extensions, skills, prompts, and
themes. Agent definitions are a my-pi feature (my-pi treats them as package
resources). Consuming my-pi at runtime is a soft dependency: without it the
files are inert. A server parsing my-pi's file format would be a hard
dependency and stays forbidden.

**SurrealKV is single-process.** It is an embedded engine: in-process,
file-owning, exclusive across processes. It supports concurrent access within
one process. The multi-node claims on the website describe SurrealDB in
server mode clustering on distributed backends (TiKV, FoundationDB). No
backend allows two processes to open one embedded file.

**Idle scheduling needs one long-lived process.** Ephemeral CLI sessions never
accumulate quiet time and would race each other. Dream cadence belongs to a
daemon, a cron, or the Bun server. Ephemeral sessions stay pure clients.

**Dream scheduler logic.** The server implementation carries: entity-only
batch for deduplication, all-nodes batch for connection, both oldest-first by
`dream_age`; age increments cover the batch plus every touched node;
convergence budget `ceil(sqrt(nodeCount / batchSize))`; exponential backoff
`idleMs * multiplier^cycles` capped; activity reset aborts in-flight cycles
and recomputes the budget; single-flight with per-phase failure semantics.

## Directions

### Shared dream guidance

Direct Pi maintenance enters through `skills/memory/dream.md`, which scopes the
work and progressively loads `deduplicate.md` or `connect.md`. These two bundled
documents own the phase procedures. The server loads them separately and renders
each inside its corresponding system prompt. Server prompts retain target-ID
context and scheduler ownership. The server does not load the direct Pi
maintenance entry point.

### Shared ingest and recall guidance

The memory skill progressively loads `skills/memory/ingest.md` for capture and
`skills/memory/recall.md` for research. The server renders those same documents
inside separate workflow prompts. Batch, retry, and capture metadata belong to
the server ingest prompt. Question/hints input and the `answerRecall` contract
belong to the server recall prompt. Direct Pi entry points retain conversational
scoping, direct answers, and optional tools unavailable to the server.

Capture consolidates repeated or extended facts into existing notes while
preserving source attribution. It reconciles explicit naming corrections and
chooses evidence edge types and directions from the evidence. Shared guidance
must not depend on host invocation details or server-only tools.

### Package contract versus my-pi veneer

The package contract stays core Pi: `extensions/`, `skills/`, `roles/`. Tool
gating lives on the tools (`defaultActive: false` on the four dream
mutations), not in persona front-matter, because exposure is a core mechanism
and covers every context. Model pins stay per context: server env decides
deployment models, sessions decide their own. Personas become thin optional
files whose bodies point at role files. my-pi present: delegation works.
Absent: nothing breaks.

### Flow placements

- **Recall**: tools plus a skill, available in every session. Read tools stay
  direct with snippets. No delegation; recall wants the live conversation.
- **Ingest**: size-routed. Interactive snippets run in-session from the
  `remember` skill. Document-scale intake delegates to a librarian persona so
  the text burns a child context. One entry point, both placements, the
  routing rule written inside the skill.
- **Dream**: curator persona plus two new package tools, registered inactive:
  a batch selector exposing `kind: entity | all` with `dreamAge` in results,
  and an age marker wrapping `incrementDreamAge`. Trigger is external (cron or
  daemon); the persona carries procedure; the trigger carries policy.

### Storage and concurrency

Embedded SurrealKV stays the engine. Concurrency resolves by process shape,
not by a database daemon:

- A single process hosting many sessions (pimote) shares one embedded storage
  instance naturally: the bridge caches its self-created storage on
  `globalThis`, every session in the process reuses it, and SurrealKV supports
  concurrent access within one process.
- Known gap for that shape: `extensions/bridge-lifecycle.ts` closes
  self-created storage on `session_shutdown`, so the first session ending
  would close the shared instance under the others. Sharing needs a refcount
  or a leave-open-on-exit rule.
- The later consolidation step, when Pi sessions become clients of the
  server, replaces the local bridge entirely for those sessions.
- If a database server ever becomes necessary anyway, the adapter change is a
  connection URL in place of a file path; the SDK calls stay the same, and
  clients scale from one embedded file to a cluster without client changes.

### Dream trigger options

| Option | Trigger | Fairness | Assessment |
|---|---|---|---|
| Manual `/dream` | user | two new tools | works; nobody runs it |
| Cron plus `pi -p` | clock | two new tools | reliable; ignores activity |
| Daemon-side timer | long-lived process | two new tools | true parity; the daemon already exists in this direction |

The idle-timer extension inside Pi sessions is dropped: it assumes a long-lived
session, which ephemeral CLI use does not provide.

## Open decisions

- Bridge lifecycle under multi-session sharing: refcount sessions or close
  only at process exit.
- Ingest routing threshold and whether the librarian persona ships in the
  package as an inert extra or installs into the agent dir.
- Model authority rule if any pin ever moves into role files: persona default,
  server env override.
- Front-matter fields for the persona files, pending the my-pi agent
  definition format.

## Candidate next steps

1. Fix bridge lifecycle for multi-session sharing (refcount or exit-close).
2. Move the four workflow prompts into `roles/`; server reads them; behavior
   identical.
3. Add the two dream tools, registered inactive.
4. Ship the `recall` and `remember` skills in the package.
5. Author the curator and librarian personas as thin pointers.
6. Choose and wire the dream trigger.
