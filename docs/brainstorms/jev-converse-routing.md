# Brainstorm: Jev converse routing

**Date:** 2026-09-27
**Status:** converged

## The idea

Use TypeSafe's Jev decision model as the fast reflex layer for `/converse` message
routing. Today `agents/converse.py` lets a full LLM decide, per message, whether to
delegate to the recall agent, the ingest agent, or answer conversationally. That is a
closed-set classification problem paid for at generative-model latency and cost.

Research context: `docs/` research brief (2026-09-27, hosted) surveyed Jev integration
options across the whole pipeline — routing, entity dedup, recall filtering, guardrails,
dream triage, model selection. This brainstorm scoped **which slice to build now**.

## Key decisions

### 1. Scope: converse routing only (first slice)

**Chosen.** Reranked candidates from the research brief:

- Converse routing ← chosen
- Ingest entity dedup + edge labels
- Recall candidate filtering
- Guardrails, dream triage, model selection

**Why:** highest user-visible impact (every conversational turn), smallest blast radius
(one decision point), and measurable in isolation. The brief's own rollout advice put
routing first; everything else waits for evidence from this slice (especially recall
filtering, which risks answer quality without measurement).

### 2. Rollout posture: live from day one (not shadow mode)

**Chosen by explicit user decision, overriding my shadow-mode recommendation.**

**Why (user's call):** simpler config and the latency win lands immediately. The risk is
covered by the confidence gate — Jev only routes when confident; everything else falls
through to the existing LLM router, which remains the safety net. A shadow mode was
rejected as ceremony: the fallback path already bounds the downside.

**Consequence to keep:** routing behavior *does* change the moment this ships. Threshold
sensitivity matters from day one; the LLM fallback must be genuinely equivalent to
today's behavior for the non-routed remainder.

### 3. Fallback semantics: LLM router is the floor

On low Jev confidence, missing/invalid key, network error, rate limit, or test mode
without credentials — route exactly as today. Jev is an optimization, never a new
single point of failure.

## Direction

A Jev decision pass sits in front of the converse router:

1. Message (+ trimmed history) → Jev: `Choice{recall, ingest, chat}` + `Noul` confidence check (or use the Choice's own confidence).
2. Confidence above threshold → dispatch directly to recall/ingest, or answer as chat.
3. Below threshold or Jev unavailable → existing LLM routing, unchanged.

Config via `BRAIN_`-prefixed env vars per repo convention. Model id pinned to a versioned
release (thresholds are tuned against a specific build; `jev-latest` drifts).

## Open questions

**Sharp (technical — inputs to architecting):**

- Integration mechanism: PydanticAI's native `TypeSafeModel` (`typesafe:jev-1.13.0`,
  `pydantic-ai-slim[typesafe]`) vs. a small direct HTTP client against `POST /v1/systemone`
  behind an injectable protocol (the `Embedder` pattern). Test doubles and
  `BRAIN_TEST_MODE` behavior must not require a `TYPESAFE_API_KEY`.
- Where the gate lives: inside `agents/converse.py` vs. in the `/converse` endpoint path —
  keeping `ConverseDeps` and `Context` accumulation intact.
- What the Jev state should contain: message only vs. message + trimmed history
  (32k-token state limit; full history counts against it).
- Default confidence threshold and how it is configured/tuned; what "chat" dispatch
  concretely does (lightweight LLM call vs. current converse agent behavior).
- How the decision is logged/observable for later threshold tuning.

**Fog:**

- Whether route accuracy degrades on the TUI's terse interactive messages vs. longer ones.
- Whether dedup (slice #2) should follow quickly or wait for routing telemetry.
- How to collect a routing eval set from real `/converse` traffic (if at all).
