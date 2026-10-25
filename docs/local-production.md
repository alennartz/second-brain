# Local production instance

**Snapshot:** 2026-10-24

This is a historical snapshot of the pre-rewrite service. It does not confirm a
production cutover to the Bun server. The Bun server requires a fresh latest-
schema database and does not migrate the previous database. Before cutover,
back up and reset the active database with the procedure in
[`deploy/README.md`](../deploy/README.md).

The service is single-user. It is not a public deployment.

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

The pre-rewrite service read `/home/alenna/repos/second-brain/.env`, whose mode
was `0600`. Its model and endpoint settings are not valid Bun server
configuration and are not reproduced here. The Bun server requires
`BRAIN_INGEST_MODEL`, `BRAIN_RECALL_MODEL`, and `BRAIN_DREAM_MODEL`, each in
`provider/model:effort` format. See the root README for current settings. The
rewrite's manual run did not verify this production deployment with the Bun
image or updated environment.

## Database state

The pre-rewrite active database was reset before this snapshot. The active
`data/brain.db` directory was about `148K`, and the intake pipeline reported no
ready, leased, retrying, or paused document chunks. That database state predates
the Bun server's latest schema. Do not reuse it for the Bun server.

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

The Bun application stops intake polling, waits through its configured shutdown
grace period, cancels remaining work, releases unacknowledged leases, and closes
storage after its workers stop. Docker and systemd stop timeouts provide the hard
fallback.

## Verification status as of the snapshot

The checks below verified the pre-rewrite deployment only. They do not verify
the Bun image, updated environment, or fresh latest-schema database.

Verified on this machine before the rewrite:

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
- completed graph ingestion with the provider configured at the time.
