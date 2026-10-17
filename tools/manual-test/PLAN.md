# Manual Test Plan

## HTTP intake and recall

Exercise synchronous `POST /ingest`, search queued document chunks, and observe
background organization through `GET /ingest/pipeline` and `GET /recall`.
This is the primary intake journey. Driver: `curl` via `bash`.

## Pipeline operations

Inspect queue health and use pause, resume, and discard controls for an intake
document. This protects operator recovery and cleanup behavior. Driver: `curl`
via `bash`.

## MCP intake and recall

Stage text through the configured MCP tools and retrieve graph and unprocessed
evidence with separate citations. This keeps the agent-facing entry point
aligned with HTTP. Driver: direct Python MCP tool invocation when practical.

## Go CLI ingest

Run the one-shot `brain ingest` command against the service and verify the
synchronous chunk-count acknowledgement. This protects the shipped terminal
client. Driver: direct shell invocation via `bash`.

## Converse staging

Stage text through the converse ingest path and inspect the resulting queue or
unprocessed recall context. This is adjacent to the intake surface, but the Jev
routing path is owned by the separate `jev-converse-routing` topic. Driver:
`curl` when a configured non-Jev path is available; Jev assertions are recorded
as scope limitations.
