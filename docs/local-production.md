# Local production instance

**Snapshot:** 2026-10-24

This record describes the local Second Brain instance on this machine. It is a
single-user service. It is not a public deployment.

## Runtime

| Setting | Value |
|---|---|
| Service | `second-brain.service` |
| Container image | `second-brain:local` |
| Host endpoint | `http://127.0.0.1:8100` |
| Container endpoint | `http://0.0.0.0:8000` |
| Host data directory | `/home/alenna/repos/second-brain/data` |
| Active database | `/data/brain.db` in the container |
| Host backup directory | `/home/alenna/repos/second-brain/backups` |
| Container user | host user `1000:1000` |
| Service manager | systemd user manager with lingering enabled |
| Authentication | none; loopback is the trust boundary |

The service publishes only `127.0.0.1:8100`. It has no public listener, TLS
proxy, or application authentication layer.

## Application configuration

The service reads `/home/alenna/repos/second-brain/.env`. The file mode is
`0600`. Provider keys are stored there and are not recorded in this document.

```text
BRAIN_DB_PATH=/data/brain.db
BRAIN_REASONING_MODEL=openai:gemma4-26b-a4b
BRAIN_REASONING_BASE_URL=http://jetson.ordernet:8082/v1
BRAIN_EMBEDDING_MODEL=openai:harrier-oss-v1-0.6b
BRAIN_EMBEDDING_BASE_URL=http://jetson.ordernet:8084/v1
BRAIN_EMBEDDING_DIMENSIONS=1024
```

The upstream OpenAI-compatible routes are:

```text
POST http://jetson.ordernet:8082/v1/chat/completions
POST http://jetson.ordernet:8084/v1/embeddings
```

The reasoning endpoint returned `200 OK` for a direct `gemma4-26b-a4b`
request on this snapshot date. A completed graph-ingestion run remains
unverified under the configured provider.

## Database state

The active database was reset before this snapshot. The active
`data/brain.db` directory is about `148K`, and the intake pipeline reports no
ready, leased, retrying, or paused document chunks. It contains the fresh
SurrealKV database and schema metadata.

The previous database remains recoverable in timestamped reset archives and
safety directories. Experiment databases remain outside the reset scope.

## Backups and updates

Backups are owner-only `tar.gz` archives in the sibling `backups/` directory.
Daily and pre-update archives rotate independently, keeping seven archives per
mode. The persistent systemd user timer runs daily at `03:00` local time.

Routine updates use:

```bash
make deploy
```

The update builds the local image, creates a successful pre-update archive, and
restarts the service. It does not pull from a registry and does not reset the
database.

Useful operations:

```bash
make deploy-status
make deploy-logs
make deploy-backup
make deploy-backup MODE=pre-update
make deploy-restore ARCHIVE=/path/to/archive.tar.gz
make deploy-undeploy
```

The one-time fresh database reset is documented in
[`deploy/README.md`](../deploy/README.md). It is not part of routine updates.

## Shutdown behavior

When the service stops, the ingestion pipeline stops claiming new processing
batches. Database search and graph-write operations finish once started. An
active LLM call is canceled when shutdown begins. Its document chunks lose the
lease immediately and return to retry state. The existing Docker and systemd
stop timeouts remain hard fallbacks for a database operation that does not
finish.

## Verification status

Verified on this machine:

- health at `127.0.0.1:8100`;
- loopback-only binding;
- local image and `/data` mount;
- non-root database ownership;
- fresh database reset with experiment data preserved;
- daily and pre-update archives with mode `0600`;
- persistent `03:00` backup timer;
- service restart and database persistence; and
- successful `make deploy`.

Not verified against the active database:

- archive restore, because it would replace the active database; and
- completed graph ingestion through the upstream reasoning provider.
