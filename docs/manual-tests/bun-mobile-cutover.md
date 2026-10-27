# Manual Testing — Bun mobile cutover

## Smoke Suite

This run exercised the deployed Bun server through the mobile HTTP endpoint.

## Topic-Specific Tests

- Verify the mobile container uses the Bun entrypoint and dedicated Pi files.
- Verify intake embedding dimensions match the fresh mobile database schema.
- Verify Android-facing health, intake, and recall requests.

## Tools

- Reused: `tools/mobile/mobile-server-up`, `curl`, and Docker Compose logs.
- Improved: mobile deployment now uses a dedicated Pi model catalog and settings.

## Harness Limitations

The Android UI itself was not driven in this run. The HTTP client path was
exercised directly from the host. This does not cover Android rendering,
connectivity changes, or the client timeout boundary.

## Results

- Mobile health: **pass**. `GET /health` returned `200` from
  `192.168.1.182:8200`.
- Mobile intake before schema reset: **fixed-inline**. The endpoint returned
  `503` because the mobile database HNSW schema expected 1536 dimensions while
  the configured Harrier embedding endpoint returned 1024 dimensions.
- Mobile intake after reset: **pass**. The incompatible `brain.surreal` schema
  was archived, removed, and recreated with 1024 dimensions. `POST /ingest`
  returned `200` and `{"chunks_stored":1}`.
- Mobile recall: **open**. One simple recall request returned `200` with raw
  evidence. Other short questions returned `400` because the Gemma workflow did
  not submit a validated `answerRecall` result. The deployed server stayed
  healthy.

## Plan Updates

The mobile smoke journey is now exercised through the deployed HTTP endpoint.
The connected Android UI journey remains deferred.

## Open Issues

Recall output validation is inconsistent for some short questions with the
current local Gemma model. The server returns `400` when the workflow does not
submit a validated answer.
