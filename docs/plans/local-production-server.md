# Plan: Local Production Server

## Context

Turn the existing Second Brain container into a reliable single-user local
service. The agreed direction is recorded in
[`docs/brainstorms/local-production-server.md`](../brainstorms/local-production-server.md).
The service remains local-only, keeps port 8100, starts from a fresh active
database, and protects recovery with local rotating archives.

## Architecture

### Impacted Modules

- **Deployment and Operations** — extend the existing `deploy/` systemd and
  Docker integration into a local-production module. It will build the configured
  local image, install the service, bind the host port to loopback, enforce
  environment-file permissions, coordinate backups, and install the daily backup
  timer. Runtime operations stay outside the application process.
- **Make targets** — expose the deployment, backup, restore, status, and log
  operations through the existing Makefile without changing application APIs.
- **Documentation** — describe the local trust boundary, one-time database reset,
  update transaction, backup retention, restore contract, and timer behavior.
- **API and Agents** — no new application endpoint or authentication layer. The
  existing application lifespan remains the shutdown seam: it stops the ingestion
  pipeline, cancels the dream scheduler, and closes Storage before the database is
  archived.

### New Modules

- **Local database archive module (`deploy/`)** — a small command-line module that
  owns quiescing the systemd service, creating and rotating `tar.gz` archives,
  restoring one selected archive, and recovering the service after failures.
  It operates only on the explicitly configured active database directory, not on
  experiment databases.
- **Daily backup timer** — a systemd user oneshot service and timer installed with
  the main deployment. The timer runs at 03:00 local time with persistent timer
  behavior so missed runs are handled after resume.

### Interfaces

#### Deployment configuration

The machine configuration supplies these values:

```text
BRAIN_IMAGE                 # local Docker tag built from this checkout
BRAIN_DEPLOY_NAME           # systemd service and container name
BRAIN_DEPLOY_PORT           # host port, fixed at 8100 for this instance
BRAIN_DEPLOY_ENV_FILE       # application environment file
BRAIN_DEPLOY_DATA_DIR       # host directory mounted at /data
BRAIN_DEPLOY_BACKUP_DIR     # sibling backups directory
BRAIN_DEPLOY_DB_NAME        # active database directory, fixed at brain.db
```

The installer creates the data and backup directories, sets the application
environment file to mode `0600`, and refuses to continue without the required
values or a locally available image.

#### Application service

The rendered systemd unit runs the local image with:

- `127.0.0.1:${BRAIN_DEPLOY_PORT}:8000` as the only host binding;
- `--pull never`, because image construction is local;
- `${BRAIN_DEPLOY_DATA_DIR}:/data` as the persistent volume;
- a Docker stop timeout and systemd `TimeoutStopSec` longer than the configured
  ingestion shutdown grace.

The unit remains restart-on-failure and enabled for the lingering user manager.
Stopping the unit is the final write barrier. Uvicorn shuts down the application
lifespan, which stops ingestion workers, cancels dreaming, and closes Storage
before the archive command reads the database directory.

#### Local image update

The deployment command builds the current checkout into `BRAIN_IMAGE`. A failed
build leaves the running service untouched. After a successful build, the command
requests a `pre-update` archive, then renders the unit and restarts the service.
The installer never performs a registry pull. The configured local tag remains the
operator-facing image identity for this single machine.

#### Archive command

The archive command has three explicit modes:

```text
backup daily
backup pre-update
restore <archive>
```

For `daily`, the command checks `/ingest/pipeline`. If ready, leased, retrying, or
actively processed intake work exists, it logs a deferred result and exits without
stopping the service. The next timer run retries it. It does not use that check as
the correctness guarantee for dreaming or other requests.

For `pre-update`, the same non-idle result is an error. The update must not restart
the service without a successful pre-update archive.

When the mode proceeds, the command stops the service, waits for a clean exit, and
writes one temporary `tar.gz` archive of
`${BRAIN_DEPLOY_DATA_DIR}/${BRAIN_DEPLOY_DB_NAME}`. It atomically renames the
completed archive into `${BRAIN_DEPLOY_BACKUP_DIR}` with owner-only permissions,
then starts the service again. A failure path attempts to restore the service's
prior active state and returns a non-zero status.

Daily archives retain the seven newest `daily-*` files. Pre-update archives retain
the seven newest `pre-update-*` files. The two retention sets are independent.

#### Restore command

`restore <archive>` requires an explicit archive path under the configured backup
directory. It validates the archive's database entry, stops the service, moves the
current active database to a timestamped safety location, extracts the selected
archive into the configured data directory, and restarts the service. It must not
modify experiment databases. If extraction or startup fails, the safety copy remains
available for recovery.

#### One-time database reset

The requested fresh start is an operator action for this deployment only, not part
of routine `deploy` behavior. It stops the service, waits for a clean exit, archives
the current `brain.db`, moves only that active directory aside, and starts the
service so SurrealKV creates a new active directory. Experiment databases remain in
place.

#### Operational verification contract

A successful setup is observable when:

- `GET /health` returns `{"status":"ok"}` through `127.0.0.1:8100`;
- the host has no listener for the service on a non-loopback address;
- the running container reports the configured local image and the `/data` bind
  mount;
- the fresh active database directory is distinct from the archived reset database
  and lives under the mounted host data directory;
- a service restart returns the same health response without recreating or losing
  the active database;
- a daily or pre-update archive exists in the backup directory, contains only the
  configured active database directory, and has owner-only permissions; and
- the user timer is enabled for the 03:00 local schedule.

### Technology Choices

- **Systemd user service and timer** — reuses the existing lifecycle and user
  lingering configuration. A Compose replacement would migrate an already healthy
  service, while a host-native process would couple production to the checkout's
  Python environment.
- **Quiesce before archive** — guarantees a consistent embedded SurrealKV directory
  without adding an application maintenance endpoint. Live copying risks concurrent
  write state; an export endpoint would add a runtime surface with no current need.
- **`tar.gz` archives** — available on the host, preserve the database directory in
  one portable file, and keep rotation and restore straightforward. `tar.zst` would
  add a host dependency, while directory snapshots would complicate retention.
- **Local configured image tag** — matches the single-machine deployment and avoids
  the observed registry pull failure. Commit-derived tags would improve release
  identity but add ignored configuration state that this local setup does not need.

### DR Supersessions

None. Existing decision records cover ingest and storage behavior and remain valid.

## Tests

**Pre-test-write commit:** `6d669fd125346417d5154e9d93ba96bdcbc94aa1`

### Interface Files

- `deploy/backup.sh` — command boundary for daily, pre-update, and selected-archive restore modes.
- `deploy/update.sh` — command boundary for building and installing the configured local image.
- `deploy/second-brain-backup.service.in` — systemd oneshot service template for daily archives.
- `deploy/second-brain-backup.timer.in` — persistent 03:00 local-time backup timer template.
- `deploy/deploy.env.example` — backup directory and active database configuration values.

### Test Files

- `tests/test_local_production_server.py` — component tests for archive, restore, update, installer, and Make command boundaries.

### Behaviors Covered

#### Archive command

- Daily backup defers while the intake pipeline reports ready, leased, retrying, or actively processed work.
- Daily backup stops and restarts the service around an archive of only the configured active database.
- Daily archive failure attempts service recovery and returns a failure status.
- Pre-update backup refuses non-idle intake work and archives an idle active database.
- Archives use owner-only permissions.

#### Restore command

- Restore accepts only an explicit archive under the configured backup directory.
- Restore moves the active database to a timestamped safety copy, extracts the selected archive, and leaves experiment databases unchanged.
- Restore failures retain the safety copy and report a failure.

#### Local image update

- A successful update builds the configured local image, creates a pre-update archive, and restarts the service without pulling.
- A failed image build leaves the running service and pre-update archive untouched.

#### Deployment and operations

- Installation renders loopback-only service settings and a persistent daily backup timer.
- Installation enforces owner-only application environment permissions and rejects unavailable local images.
- Make targets expose backup modes and selected-archive restore through the deployment command family.
