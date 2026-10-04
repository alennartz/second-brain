# Plan: Jev converse routing

## Context

Speed up `/converse` by letting TypeSafe's Jev decision model route messages on a fast
path: confidently-pure recall or ingest messages dispatch straight to their sub-agent,
skipping the converse LLM router round-trip. Everything else — chat, mixed intent, low
confidence, or any Jev failure — runs today's full converse agent unchanged.

Brainstorm: `docs/brainstorms/jev-converse-routing.md` (scope = converse routing only;
**live from day one**, user decision over shadow mode; LLM router is the floor).

## Architecture

### Impacted Modules

**Agents** — the routing decision is a new concern with its own module (below).
`agents/converse.py` gains a fast-path orchestration entry point that both API paths
share. The existing `recall`/`ingest` tool bodies are extracted into reusable functions
so the fast path and the tool path share one implementation (context accumulation,
status events, sub-agent wiring) — the tools become thin wrappers over them. The
converse agent itself is unchanged; it remains the fallback router.

**API (`app.py`)** — both `POST /converse` and `POST /converse/stream` stop calling
`_converse_agent.run` directly and call the single orchestration entry point.
Lifespan constructs the routing model (a `TypeSafeModel`) alongside `_model`, unless
`settings.test_mode` or `settings.jev_enabled` is false, in which case no routing model
exists and every turn takes the fallback path.

**Core (`config.py`, `providers.py`)** — new `BRAIN_JEV_*` settings (below).
`providers.py` handles the `typesafe:` model prefix: passthrough when no explicit key,
or a `TypeSafeProvider`-style explicit-key construction when `settings.jev_key` is set —
mirroring the existing `reasoning_key` override pattern. The implementer pins the
current stable Jev version id at build time and records it in `settings.jev_model`
(never `jev-latest` — thresholds are tuned against a specific build).

**Client** — untouched. No request/response shape changes.

### New Modules

**`src/second_brain/agents/routing.py`** (Agents layer) — owns the routing decision:
the `RoutingDecision` output type whose fields *are* the Jev questions (docstrings and
`BoolCriteria` carry the question wording), the `create_routing_agent()` factory, the
extraction of per-field confidence from a run result, and the pure
`decide_route()` interpretation function. Dependencies: Core (models/config types) and
PydanticAI only — no Storage, no Tools. This keeps the routing *policy* (question
wording, thresholds, dispatch rules) in one testable place.

### Interfaces

```python
# agents/routing.py

class Route(str, Enum):
    RECALL = "recall"
    INGEST = "ingest"
    CONVERSE = "converse"   # fall through to today's full converse agent

class RoutingDecision(BaseModel):
    """Fast-path routing for one conversational turn."""
    is_pure_recall: Annotated[bool, BoolCriteria(
        true="The message ONLY asks a question to answer from stored knowledge. "
             "It contains nothing new to store.",
        false="It stores new information, does both, or is small talk/meta.",
    )]
    """Is this message exclusively a question about stored knowledge?"""
    is_pure_ingest: Annotated[bool, BoolCriteria(
        true="The message ONLY states new information to remember. "
             "It contains no question to answer.",
        false="It asks a question, does both, or is small talk/meta.",
    )]
    """Is this message exclusively new knowledge to store?"""

class RoutingRunResult(NamedTuple):
    decision: RoutingDecision
    confidence: dict[str, float]   # field name -> confidence from provider_details

def create_routing_agent() -> Agent[RoutingDeps, RoutingDecision]: ...
    # output_type=RoutingDecision; the docstrings/criteria above are the Jev questions.

async def route_message(
    routing_agent, routing_model, message: str,
    message_history: list[ModelRequest | ModelResponse],
) -> Route | None:
    """Run the routing agent and interpret the result.
    Returns None when no fast-path route is warranted (low confidence, mixed
    intent) — callers then take the CONVERSE fallback. Raises nothing: any
    exception (missing key, 429/529, network) is logged and returns None."""

def decide_route(
    decision: RoutingDecision, confidence: dict[str, float], threshold: float,
) -> Route:
    """Pure interpretation. RECALL iff is_pure_recall and
    confidence['is_pure_recall'] >= threshold and not (is_pure_ingest and
    confidence['is_pure_ingest'] >= threshold); symmetric for INGEST;
    otherwise CONVERSE."""
```

```python
# agents/converse.py

async def run_converse_turn(
    message: str,
    message_history: list[ModelRequest | ModelResponse],
    *,
    deps: ConverseDeps,
    model: Model | str,
    routing_model: Model | str | None = None,
) -> str:
    """Single entry point for one conversational turn.

    routing_model is not None -> try the fast path first:
        Route.RECALL  -> run the recall pipeline directly (today's recall tool body)
        Route.INGEST  -> run the ingest pipeline directly (today's ingest tool body)
        None/CONVERSE -> run the converse agent exactly as today
    routing_model is None -> always the converse agent.

    Side effects identical on every path: status events on deps.progress_queue,
    cited nodes/edges accumulated (deduplicated) onto deps.context."""
```

Behavioral contracts a test writer can pin:

- **Fast path equivalence:** a turn routed to RECALL must produce the same response and
  the same `deps.context` accumulation as a turn where the converse LLM router chose
  the `recall` tool — the fast path is a shortcut to the same pipeline, not a second one.
- **Fallback is today's behavior:** any route of `CONVERSE` (or `None`) invokes the
  converse agent with the same message history the caller passed in.
- **Mixed intent is never fast-pathed:** a message touching both recall and ingest must
  land on CONVERSE regardless of confidences.
- **Failure containment:** if the routing run raises for any reason (no API key,
  network error, rate limit), the turn still completes through the converse agent; the
  failure is logged, never surfaced to the caller.
- **Threshold boundary:** `confidence == threshold` routes (>= is sufficient).
- **Test mode:** `settings.test_mode` or `settings.jev_enabled == False` means
  `routing_model is None` at every call site — no TYPESAFE_API_KEY is ever required
  outside live routing.

### Configuration (Core: `config.py`)

```python
jev_enabled: bool = True                 # kill switch; live from day one (user decision)
jev_model: str = "typesafe:jev-<pinned>" # versioned id, pinned at implementation time
jev_key: str | None = None               # explicit override; else TYPESAFE_API_KEY
jev_confidence_threshold: float = 0.9    # high bar: only confident fast paths skip the router
jev_history_turns: int = 3               # history turns included in the routing state
```

State for routing: the user message plus the last `jev_history_turns` user/assistant
turns. The state counts against Jev's 32k-token limit once per request; 3 turns keeps
us far under it. Routing observability is a structured log line per turn (route,
per-field confidences, threshold, chosen path) — sufficient for later threshold tuning.
No response-shape changes (YAGNI).

### Technology Choices

**Chosen: PydanticAI `TypeSafeModel`** (user decision). `pydantic-ai[typesafe]` /
`pydantic-ai-slim[typesafe]` optional group; the routing agent is an ordinary
PydanticAI agent whose structured output type maps onto Jev's typed questions; per-field
confidence arrives via `provider_details`. Rationale: every model in this codebase is
already a PydanticAI model injected per-run with `model=`, so tests reuse `TestModel`
and no new protocol seam is needed. Retries/backoff come from the SDK.

Alternatives considered:

- **Direct HTTP client behind a `Decider` protocol** (DR-002 `Embedder`-style seam):
  full control over question batching and a trivial dummy, no new dependency groups —
  but hand-rolled retry/backoff and ~100 lines of request/response types duplicating
  what the SDK provides. Revisit if routing needs batched multi-state calls (e.g. a
  future recall-filtering slice).
- **OpenRouter** (`typesafe/jev-1.13`): one vendor key, but an extra indirection layer
  and less certain decision-model semantics through the router.

New dependency to add via package manager at implementation time (resolve latest
compatible versions, never hand-pinned): the `typesafe` optional group of the existing
PydanticAI dependency.

### DR Supersessions

None. DR-001's reasoning is untouched (sub-agent loops preserved on every path) and
DR-002's injection discipline is followed (routing model constructed at startup,
injected per-run like `model_setting`).

## Tests

**Pre-test-write commit:** `e5ed3eb25693ac949334648f9f40e192268d89e6`

### Interface Files

- `src/second_brain/agents/routing.py` — `Route` (`StrEnum`: recall/ingest/converse),
  `RoutingDecision` (the two Jev questions as `BoolCriteria`-annotated bools),
  `RoutingRunResult` (decision + per-field confidence), `RoutingDeps`, and stubs for
  `create_routing_agent()`, `route_message()`, `decide_route()` (all raise
  `NotImplementedError`).
- `src/second_brain/agents/converse.py` — added the `run_converse_turn()` orchestration
  entry point (stub). Existing agent/tool code untouched.
- `src/second_brain/config.py` — the `BRAIN_JEV_*` settings: `jev_enabled`,
  `jev_model` (`typesafe:jev-1.13.0`, the current stable versioned id — never
  `jev-latest`), `jev_key`, `jev_confidence_threshold`, `jev_history_turns`.
- `pyproject.toml` / `uv.lock` — dependency changes required to materialize the
  interfaces at all: `pydantic-ai[typesafe]` (resolves to 2.54.0 — `TypeSafeModel` and
  `BoolCriteria` only exist on PydanticAI 2.x; the plan's "typesafe optional group of the
  existing PydanticAI dependency" forces the 1.x → 2.x major bump, zero code fallout,
  all 236 pre-existing tests green on the new stack) and `fastmcp` 3.x → 4.0.10 (2.x of
  pydantic-ai-slim pulls `fastmcp-slim`, which collided with fastmcp 3.x's module;
  fastmcp 4.x is the `fastmcp-slim[client,server]` metapackage and resolves the clash).
- `test_scenario.py` — pre-existing basedpyright error (`resp` possibly unbound) fixed so
  the pre-commit hook can pass; unrelated to this topic.

Materialization notes:

- The Jev question wording rides in `Field(description=...)` on each `RoutingDecision`
  field (plus the `BoolCriteria` true/false criteria). Plain attribute docstrings — what
  the plan's interface sketch shows — are not collected by Pydantic 2.12 and would never
  reach the Jev schema; the field description is what the decision model sends as the
  question.
- `RoutingDeps` is an empty dataclass: the plan references the type but specifies no
  fields, and the routing decision needs no Storage or tools. Threshold/history config is
  read from `settings` where the policy needs it.
- `Route` inherits `StrEnum` (ruff UP042 over the sketch's `str, Enum`).

### Test Files

- `tests/test_routing.py` — `decide_route` interpretation rules and `route_message`
  behavior (route selection from a run result's `provider_details`, failure containment,
  threshold source, routing-state composition). Model doubles are `FunctionModel`s that
  answer the decision questions deterministically and carry per-field confidence through
  `provider_details['confidence']` exactly as the TypeSafe decision model does.
- `tests/test_converse_agent.py` (extended) — `run_converse_turn` orchestration: fast-path
  equivalence against the converse tool path, fallback semantics, failure containment,
  and routing-state bounds. Sub-agent runs use `TestModel`; the converse-tool path is
  driven by a relay double (calls the sub-agent tool, relays its return verbatim — what
  the system prompt instructs).

### Behaviors Covered

#### decide_route (pure interpretation)

- Confident pure-recall decision routes `RECALL`; confident pure-ingest routes `INGEST`.
- Mixed intent (both flags set) is `CONVERSE` regardless of confidences.
- Neither flag (small talk/meta) is `CONVERSE`.
- Confidence below the threshold is `CONVERSE`.
- Confidence exactly equal to the threshold routes (`>=` is sufficient).
- A confident flag is not blocked by the other flag set at low confidence (both
  directions).

#### route_message

- A confident pure-recall run result yields `Route.RECALL`; confident pure-ingest yields
  `Route.INGEST`.
- Mixed intent takes no fast path (result is `None` or `Route.CONVERSE` — callers treat
  both as the fallback).
- Below-threshold confidence takes no fast path.
- Confidence at `settings.jev_confidence_threshold` routes; raising the configured
  threshold changes the outcome — the threshold comes from settings.
- A routing run that raises (missing key, rate limit, network) returns `None`, logs the
  failure at WARNING or above, and never raises to the caller.
- The routing state includes the current message and the provided recent history.

#### run_converse_turn

- **Fast-path equivalence (recall):** a RECALL-routed turn returns the same response and
  accumulates the same cited nodes/edges (deduplicated) onto `deps.context` as a turn
  where the converse router invoked the `recall` tool; status events on
  `deps.progress_queue` are emitted on both paths and are identical.
- **Fast-path equivalence (ingest):** an INGEST-routed turn matches the converse `ingest`
  tool path (response and context).
- **Mixed intent** falls through to the converse agent even at maximum confidence.
- **Routing failure** (routing model raises) still completes the turn through the converse
  agent, never surfacing the error.
- **`routing_model=None`** (test mode / `jev_enabled=False` call-site shape) always runs
  the converse agent, even for a message that reads like pure recall.
- **Fallback fidelity:** the converse agent is invoked with the full message history the
  caller passed in.
- **Bounded routing state:** the state given to the routing model is the current message
  plus at most the configured `jev_history_turns` of history, taken as the most recent
  contiguous stretch (never the oldest turns).

Intentionally unpinned in this phase: pure data-shape contracts (the exact
`RoutingDecision` field/criteria text, `Route` values, `jev_*` defaults) — they are
materialized in code but any test of them would pass against interface-only code, which
the Red Gate forbids; assert them once implementation exists. The app-level wiring
(both endpoints calling `run_converse_turn`; lifespan passing `routing_model=None` in
test mode / when disabled) is implementation scope.

### Red Gate

All 23 new tests fail with `NotImplementedError: not implemented` from the stubs (8 at
`decide_route`, 8 at `route_message`, 7 at `run_converse_turn`); all 236 pre-existing
tests pass. Suite runs clean; ruff and basedpyright pass.
