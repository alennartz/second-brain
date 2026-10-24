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

For `daily`, the command checks `/ingest/pipeline`. Positive `ready`, `leased`,
`retry_wait`, `worker_count`, or `active_leases` values mean non-idle intake.
Paused-only work does not block an archive. Non-idle intake or a pipeline request
or parsing error produces a logged deferred result without stopping the service.
The next timer run retries it. This check is not the correctness guarantee for
dreaming or other requests. The host uses `jq` to parse the pipeline response.

For `pre-update`, non-idle intake or a pipeline error is an error. The update must
not restart the service without a successful pre-update archive.

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
- Daily and pre-update modes cover each non-idle field, paused-only intake, and pipeline request or parsing errors.
- Retention keeps seven newest archives per mode without changing the other mode or unrelated archives.
- Failed service stops prevent archives. Failed starts report failure. Archive failure preserves a previously inactive service.
- Update aborts before installation or restart when pre-update backup fails.
- Restore rejects invalid database entries before stopping and retains safety copies after startup failure.
- Installation rejects each missing required value, mounts the configured data directory, and sets both stop timeouts above ingestion grace.

### Manual Test Contract

- `docs/manual-tests/local-production-server.md` covers the one-time reset, live health, loopback listeners, image identity, mounted data, restart persistence, journal lifecycle, lingering, and backup timer verification.
- The reset is an operator action, not a routine deployment command.
- Manual journeys remain unexecuted until deployment verification.

**Review status:** approved

## Steps

**Pre-implementation commit:** `ec8f99fca103218395b35741112f79015b565bd0`

### Step 1: Validate deployment configuration

In `deploy/install.sh`, require all seven deployment values listed above before
changing units or starting services. Resolve the checkout from the script location,
not the caller's working directory. Preserve support for `XDG_CONFIG_HOME`.

Require an existing application environment file and a locally available
`BRAIN_IMAGE`, checked through Docker image inspection. Never pull an image.
Create the configured data and backup directories. Set the application environment
file to mode `0600` before enabling services.

Update `deploy/deploy.env.example` to use `second-brain:local`, port `8100`, a
sibling backup directory, and active database name `brain.db`. Document the
application setting `BRAIN_DB_PATH=/data/brain.db` so storage uses the mounted
active database. Do not change the ignored machine configuration.

**Verify:** Installer tests reject every missing required value and unavailable image. The environment permission test passes.
**Status:** done

### Step 2: Render the local service and backup timer

Change `deploy/second-brain.service.in` to remove the registry-pull command and
publish only `127.0.0.1:{{PORT}}:8000`. Keep `--pull never`, the configured `/data`
bind mount, and `Restart=on-failure`.

In `deploy/install.sh`, read `BRAIN_INTAKE_SHUTDOWN_GRACE_SECONDS` from the
application environment file without executing its contents. Use the default of
60 seconds from `src/second_brain/config.py` when unset. Render integer Docker
stop and systemd stop timeouts above the configured grace, including fractional
grace values. Give systemd additional time beyond Docker's stop timeout.

Render and install `${BRAIN_DEPLOY_NAME}.service`,
`${BRAIN_DEPLOY_NAME}-backup.service`, and
`${BRAIN_DEPLOY_NAME}-backup.timer` under the systemd user unit directory.
Extend template substitution for the stop timeouts and backup script's absolute
path. Render `deploy/second-brain-backup.service.in` with an executable invocation
of `deploy/backup.sh daily`. Keep the timer's existing persistent 03:00 schedule
and configured backup unit name.

Reload the user manager. Enable the main service and enable the backup timer with
`--now`. Keep all runtime lifecycle changes outside `src/second_brain/app.py`.
Its existing lifespan already stops the pipeline and scheduler, then closes Storage.

**Verify:** Installer tests confirm all three units, loopback binding, local image policy, data mount, restart policy, timer enablement, and timeouts above a 90-second grace.
**Status:** done

### Step 3: Implement quiesced archives

Replace the stub in `deploy/backup.sh` with the `daily` and `pre-update` command
modes. Load configuration relative to the script and validate the values needed
for the archive operation. Keep service recovery and archive handling behind this
command interface. Use explicit function arguments and invocation-local lifecycle
state, not shared mutable state.

Request `http://127.0.0.1:${BRAIN_DEPLOY_PORT}/ingest/pipeline` with `curl` and
parse the response with host `jq`. Check `ready`, `leased`, `retry_wait`,
`worker_count`, and `active_leases`. Accept absent optional activity fields as
zero, as existing tests supply count-only snapshots. Ignore paused-only work.
Treat request failures and invalid snapshots as non-idle. Daily mode prints a
`deferred` result and exits successfully without stopping. Pre-update mode exits
with an error without stopping.

Record the prior active service state. Stop the configured user service and wait
for successful completion before invoking `tar`. A failed stop must prevent any
archive operation. Create a uniquely dated temporary archive in the backup
directory. Archive only `BRAIN_DEPLOY_DB_NAME`, relative to
`BRAIN_DEPLOY_DATA_DIR`. Set owner-only permissions and atomically publish the
completed archive as `daily-*.tar.gz` or `pre-update-*.tar.gz`.

Start the service after successful publication and report startup failures.
On failure, remove temporary output and attempt to recover a previously active
service. Do not start a previously inactive service during failure recovery.
Return a non-zero status for stop, archive, publication, or startup failures.

**Verify:** Archive tests pass for each non-idle field, paused-only intake, pipeline errors, database contents, mode-specific results, `0600` permissions, lifecycle ordering, and recovery failures.
**Status:** done

### Step 4: Rotate independent archive sets

In `deploy/backup.sh`, rotate archives only after publishing a completed archive.
Keep the seven newest matching files for the selected mode. Exclude temporary
files, the other mode's archives, and unrelated operator archives from deletion.
Keep filenames unique when two commands run within the same timestamp interval.

**Verify:** Both retention tests preserve seven newest archives, every archive in the other mode, and the unrelated operator archive.
**Status:** done

### Step 5: Implement selected-archive restore

Add `restore <archive>` to `deploy/backup.sh`. Reject a missing argument, missing
archive, or resolved archive path outside the configured backup directory before
stopping the service. Validate the complete archive listing before modifying data.
Require entries under the configured database directory. Reject absolute paths,
parent traversal, foreign database entries, and entries that can extract outside
that directory through links.

Stop the configured user service successfully before moving data. Move only the
active database directory to a unique `${BRAIN_DEPLOY_DB_NAME}.safety-*` location
under the data directory. Extract the selected archive into the configured data
directory and start the service. Leave experiment databases unchanged.

Return a failure status when extraction or startup fails. Preserve the safety
copy for operator recovery. Apply the archive command's prior-state recovery
contract on failure without deleting that copy or treating a partial restore as
successful.

**Verify:** Restore tests pass for explicit archive selection, path and member rejection before stopping, restored contents, untouched experiments, and retained safety copies after extraction or startup failures.
**Status:** done

### Step 6: Connect local updates and Make commands

Replace the stub in `deploy/update.sh`. Load configuration from its script-relative
checkout and build that checkout into `BRAIN_IMAGE` with Docker. On build failure,
exit without invoking backup, installation, or service lifecycle commands.

After a successful build, invoke `deploy/backup.sh pre-update`. Continue only on
success. Invoke `deploy/install.sh` to render the current units, then restart
`${BRAIN_DEPLOY_NAME}.service`. Propagate each command failure. Never invoke a
registry pull.

Change `Makefile`'s `deploy` recipe to call `bash deploy/update.sh`. Add
`deploy-backup` with `MODE=daily` as its default and a recipe that passes `MODE`
to `bash deploy/backup.sh`. Add `deploy-restore`, require a nonempty `ARCHIVE`,
and pass its quoted value to `bash deploy/backup.sh restore`.

Extend `deploy-undeploy` to disable and remove the backup timer and oneshot unit
alongside the main service, then reload the user manager. Keep the existing
configured status and journal commands.

**Verify:** Update tests confirm build, archive, and restart order. Build and pre-update failures leave later operations untouched. Make dry-run tests expose both backup and explicit restore commands.
**Status:** done

### Step 7: Document local operation and recovery

Rewrite `deploy/README.md` for the local-image workflow. List all deployment
scripts and templates. Document host prerequisites, including Docker, the user
manager, `curl`, `jq`, and `tar`. Describe application environment permissions,
loopback-only access, and the absence of application authentication.

Explain first installation with an available local image through `install.sh`,
routine updates through `make deploy`, and the pre-update archive requirement.
Document backup modes, daily deferral, independent seven-file retention,
03:00 persistent scheduling, explicit restore selection, and safety-copy recovery.
Provide commands to inspect service status, journal logs, timer status, and user
lingering. Keep the fresh database reset a separate operator procedure. State that
it archives and moves only `brain.db`, never experiment databases.

Update `README.md`'s production deployment section to point to the local systemd
workflow instead of presenting the Compose production commands as this setup.
Link `docs/manual-tests/local-production-server.md` for deployment verification.
Keep its results unexecuted until the operator performs the live journeys.

**Verify:** Run the existing `tests/test_local_production_server.py` suite during implementation. Documentation matches the command interfaces and manual verification contract. No reset occurs during routine deployment.
**Status:** done
