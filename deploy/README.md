# Local production deployment

This deployment runs one local Second Brain service under a systemd user manager.
Docker runs the image built from this checkout. The service listens only on
`127.0.0.1:8100`. Loopback access is the trust boundary. The application has no
authentication layer.

## Files

| File | Purpose |
|---|---|
| `deploy.env.example` | Documented machine configuration |
| `deploy.env` | Gitignored machine configuration |
| `install.sh` | Validate configuration, render units, and install the service and timer |
| `update.sh` | Build the local image, create a pre-update archive, install, and restart |
| `backup.sh` | Create daily or pre-update archives, or restore one selected archive |
| `second-brain.service.in` | Main systemd user service template |
| `second-brain-backup.service.in` | Daily backup oneshot template |
| `second-brain-backup.timer.in` | Persistent 03:00 local-time timer template |

## Host prerequisites

Install and configure:

- Docker with permission to run containers.
- A systemd user manager with user lingering enabled.
- `curl`, `jq`, `tar`, and `flock` on the host.
- A checkout with the current Dockerfile.

The installer does not use `sudo`, pull an image, or contact a registry. Build the
configured image locally before the first install.

## Configuration

Copy the example and set machine paths:

```bash
cp deploy/deploy.env.example deploy/deploy.env
```

Set these values:

- `BRAIN_IMAGE`: the local Docker tag, such as `second-brain:local`.
- `BRAIN_DEPLOY_NAME`: the systemd service and container name.
- `BRAIN_DEPLOY_PORT`: `8100` for this deployment.
- `BRAIN_DEPLOY_ENV_FILE`: the application environment file.
- `BRAIN_DEPLOY_DATA_DIR`: the host directory mounted at `/data`.
- `BRAIN_DEPLOY_BACKUP_DIR`: the sibling archive directory.
- `BRAIN_DEPLOY_DB_NAME`: `brain.db`, the active database directory.

Set `BRAIN_DB_PATH=/data/brain.db` in the application environment file. The
file contains provider credentials. `install.sh` sets its mode to `0600` before
it enables any unit.

## First installation

Build the configured local image, then install the units:

```bash
docker build -t second-brain:local .
bash deploy/install.sh
```

Use `make deploy` for routine updates after the service has an active database.
It runs `deploy/update.sh`, which builds a candidate image without changing the
configured tag, acquires the deployment lock, creates a successful `pre-update`
archive, tags the candidate, renders the current units, and restarts the service.
A build or archive failure leaves the running service and configured image tag
untouched.

The main unit uses:

- `127.0.0.1:${BRAIN_DEPLOY_PORT}:8000` as its only published binding;
- `--pull never` and the configured local image;
- `${BRAIN_DEPLOY_DATA_DIR}:/data` as its persistent mount;
- Docker and systemd stop timeouts longer than the application intake shutdown
  grace; and
- `Restart=on-failure`.

## Backups

Create an archive through the deployment command family:

```bash
make deploy-backup                         # MODE=daily
make deploy-backup MODE=pre-update
```

Daily mode requests `/ingest/pipeline` through loopback. Positive `ready`,
`leased`, `retry_wait`, or `active_leases` values defer the archive without
stopping the service. The worker-loop count is not intake work. Paused-only
work does not defer it. A request or parsing error also defers it. The
persistent timer retries on its next run. If the service is already inactive,
the command skips the endpoint check and preserves that inactive state. A failed
unit is stopped before the archive and remains stopped afterward.

Pre-update mode treats non-idle work and pipeline errors as failures. The update
will not install or restart the service without a successful pre-update archive.
Both modes stop an active service before reading the database, publish one
owner-only (`0600`) `tar.gz` archive, and restart it after publication. A failed
operation removes temporary output and recovers only a service that was active
before the operation. Backup, restore, update, and reset operations share the
exclusive deployment lock.

Daily and pre-update archives rotate independently. Each set keeps its seven
newest files. Temporary files, the other mode, and unrelated operator archives
are not removed.

The installer enables `${BRAIN_DEPLOY_NAME}-backup.timer`. It runs the daily
oneshot at `03:00` local time and uses `Persistent=true`, so a missed run starts
when the user manager resumes.

## Restore

Choose one explicit archive under the configured backup directory:

```bash
make deploy-restore ARCHIVE=/path/to/backups/daily-2026-01-01T030000Z.tar.gz
```

The command validates every archive member before stopping the service. It
accepts only entries under `BRAIN_DEPLOY_DB_NAME`, rejects absolute paths,
parent traversal, links, and foreign database entries, then:

1. stops the service;
2. moves the active `brain.db` to a timestamped `brain.db.safety-*` directory;
3. extracts the selected archive into a staging directory;
4. atomically publishes the staged database; and
5. starts the service.

Extraction and startup failures return a non-zero status and retain the safety
copy. A failed extraction restores the safety copy before service recovery. A
missing active database is valid for restore. Experiment databases remain in
place.

## One-time fresh database reset

A fresh start is an operator action. It is not part of `make deploy` and does
not run during routine updates. Run the standalone shell below. It fails closed:
it stops before moving data, removes incomplete output, and recovers a service
that was active before the reset.

```bash
bash -euo pipefail <<'RESET'
. deploy/deploy.env

service="${BRAIN_DEPLOY_NAME}.service"
active="$BRAIN_DEPLOY_DATA_DIR/$BRAIN_DEPLOY_DB_NAME"
mkdir -p "$BRAIN_DEPLOY_BACKUP_DIR"
exec {lock_fd}>"$BRAIN_DEPLOY_BACKUP_DIR/.backup.lock"
flock --exclusive "$lock_fd"
if [[ ! -d "$active" || -L "$active" ]]; then
  echo "active database is missing: $active" >&2
  exit 1
fi

was_active=0
if systemctl --user is-active --quiet "$service"; then
  was_active=1
fi
archive="$BRAIN_DEPLOY_BACKUP_DIR/reset-$(date -u +%Y-%m-%dT%H%M%SZ)-$$.tar.gz"
safety="$BRAIN_DEPLOY_DATA_DIR/${BRAIN_DEPLOY_DB_NAME}.safety-$(date -u +%Y-%m-%dT%H%M%SZ)-$$"
temporary=""

cleanup() {
  local status=$?
  set +e
  [[ -z "$temporary" ]] || rm -f -- "$temporary"
  if ((status != 0 && was_active == 1)); then
    systemctl --user start "$service" || true
  fi
  trap - EXIT
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ((was_active == 1)); then
  systemctl --user stop "$service"
fi
temporary="$(mktemp "$BRAIN_DEPLOY_BACKUP_DIR/.reset-XXXXXX.tar.gz.tmp")"
(
  cd "$BRAIN_DEPLOY_DATA_DIR"
  tar --create --gzip --file="$temporary" -- "$BRAIN_DEPLOY_DB_NAME"
)
chmod 0600 "$temporary"
mv -- "$temporary" "$archive"
temporary=""
mv -- "$active" "$safety"
systemctl --user start "$service"
trap - EXIT
RESET
```

This procedure archives and moves only `brain.db`. It never moves experiment
databases. Verify `GET http://127.0.0.1:8100/health` and retain the safety copy
until the fresh database is confirmed.

## Inspect and remove the deployment

```bash
make deploy-status
make deploy-logs
systemctl --user status second-brain-backup.timer --no-pager
systemctl --user list-timers --all
loginctl show-user "$USER" -p Linger
make deploy-undeploy
```

`make deploy-undeploy` disables and removes the main service, backup oneshot, and
backup timer, then reloads the user manager.

## Verification

Follow [the local production manual test journey](../docs/manual-tests/local-production-server.md).
It checks health, loopback listeners, image identity, the `/data` mount, restart
persistence, journal lifecycle, lingering, timer scheduling, and archive
recovery. The manual results remain unexecuted until an operator runs them.
