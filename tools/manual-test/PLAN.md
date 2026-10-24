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

## Android Flutter client smoke journey

**Status:** deferred. The containerized toolchain supports checks and builds, but
no connected phone or Android emulator is available here. Real-phone installation,
live debugging, and VM-service connection remain unrun.

Run this journey later in an Android emulator environment. It targets the
emulator, not the real phone used for wireless live debugging:

1. First-launch server setup.
2. Capture success and the stored chunk acknowledgement.
3. Failed Capture retention and explicit retry.
4. Ask recall and expanded evidence.
5. Back from the result route with the question retained.
6. Capture and Ask submission while the keyboard is open.
