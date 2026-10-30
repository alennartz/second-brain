# Brainstorm: Android workflows

**Status:** converged

## The idea

Develop the Android app around three journeys: reliable capture, repeatable
access to past answers, and read-only graph exploration. Capture is the most
important journey. The first pass must deliver all three.

## Key decisions

### Capture without waiting for the server

Save each capture locally before sending it. Return to a clean composer and show
pending captures and their sync status. Retry automatically when the app opens,
including captures for inactive brains. Keep the original capture time and
idempotency key across retries. Background sync is not required.

Keep idempotency records after the ingestion pipeline processes the intake.
A lost response or app crash must not turn a retry into a duplicate. Reusing a
key with different content must be rejected if the original was accepted.

Allow edits to pending captures. An edited retry keeps its original key. If the
server has already accepted the original, retain the rejected edit locally for
the user to resolve or submit as a new capture deliberately. Deleting pending
captures is deferred. This avoids implying that deleting a local entry removes
an intake the server might already have accepted.

### Keep answers as snapshots

Keep Ask one-shot. Automatically save each successful question, answer, time,
and displayed evidence on the phone. Reopening a consultation must show the
same answer and evidence without calling the model or requiring the server.
The snapshot retains graph IDs as links to the current graph, but does not rely
on those IDs to reproduce the evidence. Graph records can change or disappear.

### Explore the graph independently of Ask

Keep Ask and Explore as separate entry points. Ask generates an answer. Explore
searches and browses without generating one. Direct search uses the same hybrid
lexical and semantic database search as the agent-facing memory tool. It needs
embeddings but not an LLM-generated answer. Show unprocessed evidence separately
from graph nodes; only graph nodes lead into graph exploration.

Explore is graph-first. Search matches appear on the canvas immediately, not in
a list that requires manual selection before they join the graph. Connections
load in the background. Selecting nodes and following edges keeps the map open;
Details is an explicit action. Evidence links enter the map too. All memory and
connection labels use human names or fallbacks, never database record IDs.

A graph node from search or an answer can start exploration. Following an edge
loads the next node and its existing connections. One persistent workspace per
brain grows as the user explores. A clear action starts it over.

Provide separate views of the same workspace: a pannable, zoomable canvas with
compact nodes, and a detailed node and connection view. Selection and loaded
graph data stay in sync across views. Keep visited data visible offline. On the
first Explore visit after each app launch, show the saved workspace immediately
and refresh expanded nodes in the background. The user can also trigger this
refresh manually. Dim nodes and edges confirmed missing. A failed check leaves
the cached data in place, without marking it deleted.

Show new edges from expanded nodes without expanding their destinations. An
edge can connect to a node already on the workspace. A separate clear-deleted
action removes confirmed-missing items locally without another server request.
This keeps the workspace useful offline while distinguishing cached data from
the current graph.

### Keep brains distinct

Store named brain profiles. The user can add a brain or update the address of an
existing named brain; updating an address is an explicit claim that it is the
same brain. Captures, answer snapshots, and graph workspaces belong to their
brain. Switching the active brain must not redirect queued captures or graph
links to another brain.

A profile can be saved before its first successful connection and is marked as
never connected until then. This preserves offline capture and prevents queued
work from being stranded. Profiles for brains that were connected successfully
remain available after switching. Retry queued captures for inactive profiles as
well as the active profile.

### Defer hands-free voice

The desired future experience is a hands-free car journey: start from Gemini or
Google Assistant, dictate, hear the transcription, and confirm before saving.
A rejection allows another attempt. The app must not submit without confirmation.

Defer the full voice flow, including the assistant trigger. Google documents
Play Store publication as a requirement for normal App Actions deployment, and
the requested Gemini conversation and locked-phone behavior are not established.
The existing keyboard microphone remains available. Native Android Auto
integration is not assumed.

## Direction

Deliver the journeys in slices: brain profiles and reliable Capture, Ask
snapshots, then graph search and exploration. Preserve the existing mobile
configuration and pending draft when upgrading. The exploration workspace is
read-only; manual graph editing is out of scope.

## Open questions

### Sharp questions

- How will durable idempotency receipts survive processing and retries while
  preserving conflict detection and a useful original receipt?
- How will the app migrate existing settings and pending drafts without losing
  their brain association, key, or capture time?
- How will graph search expose the same results as the agent-facing hybrid
  search through the HTTP boundary?
- How will the app persist and update a growing workspace while distinguishing
  cached, current, and unavailable graph records?
- How will a rejected pending edit remain recoverable without automatically
  creating a second intake?

### Fog

- Canvas layout, readability, and performance as the explored graph grows.
- The right long-term retention policy for idempotency receipts and local data.
- Hands-free voice integration and its distribution requirements remain future
  investigation, not a commitment for this pass.
