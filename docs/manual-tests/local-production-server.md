# Manual Testing — local-production-server

**Plan:** `docs/plans/local-production-server.md`

## Smoke Suite

- **Fresh active-database reset:** perform the agreed one-time reset, then verify
  the service starts on a new `brain.db` while the archived database and
  experiment databases remain recoverable.
- **Runtime health and restart persistence:** verify health, image identity,
  loopback binding, `/data` mount, and persistence across a service restart.
- **Backup and timer operation:** create a daily archive, verify its contents and
  permissions, and inspect the persistent 03:00 user timer.

## Topic-Specific Tests

- **Clean archive lifecycle:** with intake idle, exercise daily and pre-update
  archive commands, service stop/start state, active database contents, and
  independent retention behavior.
- **Restore safety:** validate an explicitly selected archive and verify safety
  copy retention and untouched experiment databases in a disposable deployment.
- **Installer contract:** render the local image, loopback-only service, data
  mount, stop timeouts, backup oneshot, and persistent timer.

## Tools

- **Reused:** `systemctl --user`, `docker`, `curl`, `ss`, `tar`, `stat`, `find`,
  `journalctl`, `loginctl`, and `make` through the shell.
- **New:** none. The deployment commands are the reusable drivers.
- **Improved:** `install.sh` now uses `$HOME/.config` when
  `XDG_CONFIG_HOME` is unset, renders the host UID:GID into Docker, and keeps
  application logs in the systemd journal.

## Harness Limitations

The suite used the real local Docker daemon, systemd user manager, image,
mounted data directory, and provider-backed service. It used no mocks. The
provider accepted embedding requests, but one manual intake worker remained
leased through the shutdown grace period. The runtime persistence check therefore
used queued unprocessed evidence and recall before and after restart. It did not
verify completed graph ingestion or graph recall. Deployment, archive, health,
and lifecycle checks do not depend on LLM completion. Restore extraction and
startup-failure safety were not run because no disposable deployment exists and
restore would mutate the active database beyond the approved reset.

## Preconditions

- Use the configured systemd user service and local image.
- Confirm the active database is `BRAIN_DEPLOY_DATA_DIR/brain.db`.
- Record experiment database paths and checksums before operations.
- Confirm the environment file has mode `0600`.
- Run the container as the current host UID:GID so host archives can read the database.
- Keep all credentials out of recorded results.
- Do not repeat the fresh reset during routine updates.

## One-time fresh start

This operation resets the active database. It is an operator action, not a
routine deployment command.

1. Stop the service and confirm a clean container exit before reading database files.
2. Archive only the active `brain.db` directory into a dated, owner-only archive.
3. Inspect the archive and confirm it contains the complete active database, without experiment data.
4. Move only the active directory to a dated safety location.
5. Start the service and request `GET http://127.0.0.1:8100/health`.
6. Confirm the response is `{"status":"ok"}`.
7. Confirm a new active directory exists under the mounted host data directory.
8. Confirm the new directory is distinct from the safety directory.
9. Confirm the safety directory retains the old contents.
10. Confirm experiment paths and checksums remain unchanged.

**Pass:** A fresh active database runs on the original port, and the archived database remains recoverable.

## Runtime verification

1. Inspect host listeners and confirm the service binds only to `127.0.0.1:8100`.
2. Inspect the container and confirm its image matches `BRAIN_IMAGE`.
3. Confirm its `/data` bind mount points to `BRAIN_DEPLOY_DATA_DIR`.
4. Store a unique note through the public API or client and wait for ingestion to finish.
5. Confirm recall finds the note before restarting.
6. Restart the systemd user service and confirm the health response remains `{"status":"ok"}`.
7. Confirm recall still finds the note and the active directory was not replaced.
8. Confirm journal logs show application shutdown and subsequent startup.
9. Confirm the user manager has lingering enabled and the service is enabled.
10. Confirm no application authentication or public proxy was introduced.

**Pass:** The existing local client works, network access stays local, and restart preserves stored knowledge.

## Backup and restore verification

1. With intake idle, run a daily or pre-update backup through its public command.
2. Confirm the service returns to its previous running state and health succeeds.
3. Inspect the archive and confirm all entries belong to the configured active database.
4. Confirm archive permissions are `0600`.
5. Confirm the user backup timer is enabled and persistent, with a 03:00 local schedule.
6. Confirm the timer invokes the daily backup command.
7. In a disposable deployment, restore an explicit archive from the configured backup directory.
8. Confirm the restored contents match the selected archive and the safety copy preserves the previous database.
9. Confirm health succeeds and experiment data remains unchanged.

**Pass:** Backup creation, timer installation, and selected-archive recovery work through the operator interfaces.

## Results

- **Fresh active-database reset — fixed-inline.** Built `second-brain:local`,
  completed the local configuration, and ran the reset procedure twice. The
  final reset archived
  `/home/alenna/repos/second-brain/backups/reset-2026-10-24T112916Z-891786.tar.gz`
  with mode `0600`, containing only `brain.db`. It moved the prior active
  directory to `data/brain.db.safety-2026-10-24T112916Z-891786`, then started a
  distinct fresh `data/brain.db`. Health returned `{"status":"ok"}`. The two
  experiment database checksums matched before and after. The first live archive
  attempt exposed root-owned database files. The inline fix runs Docker as
  `1000:1000`, and the final reset passed. **Coherence:** looks coherent.
- **Runtime health and restart persistence — pass.** `GET /health` returned
  `{"status":"ok"}` after install, reset, backup, update, and restart. `ss`
  showed only `127.0.0.1:8100`. Docker reported image `second-brain:local`,
  user `1000:1000`, and the configured `/data` bind. A queued marker remained
  visible through `/recall` before and after restart. The active directory inode
  and manifest checksum stayed unchanged. Journal entries showed application
  shutdown and startup. Lingering was `yes`, and both service and timer were
  enabled. **Coherence:** looks coherent.
- **Backup and timer operation — pass.** `bash deploy/backup.sh daily` created
  `daily-2026-10-24T112928Z.tar.gz`; `bash deploy/backup.sh pre-update`
  created `pre-update-2026-10-24T112940Z.tar.gz`; `make deploy` created
  `pre-update-2026-10-24T113352Z.tar.gz`. Each archive had mode `0600` and only
  `brain.db` members. The active service returned after each operation and
  health succeeded. The timer was enabled and waiting with
  `OnCalendar=*-*-* 03:00:00`, `Persistent=true`, and the daily oneshot unit.
  **Coherence:** looks coherent.
- **Clean archive lifecycle — pass.** Idle daily and pre-update archives
  stopped and restarted the active service, verified a successful systemd stop,
  and published owner-only archives. A live ready intake produced `deferred`
  with exit `0` for daily mode and an error with exit `1` for pre-update mode.
  Neither non-idle check stopped the service. Automated rotation tests cover
  seven-file independent retention; this live run did not create nine archives.
  **Coherence:** looks coherent.
- **Restore safety — open.** Parent authorization explicitly excludes restore
  against the active database. No disposable deployment is configured, so
  selected-archive extraction, safety-copy retention after failure, and
  experiment preservation remain unexecuted.
- **Installer contract — fixed-inline.** The first install exposed a path bug:
  with `XDG_CONFIG_HOME` unset, `install.sh` rendered units under
  `$HOME/systemd/user` and failed to find the timer. The fix uses
  `$HOME/.config`. The final install rendered loopback binding, `--pull never`,
  host UID:GID, `/data`, both stop timeouts, backup oneshot, and persistent timer.
  Focused tests passed: `75 passed`. **Coherence:** looks coherent.

## Plan Updates

Empty. No primary user journey changed.

## Open Issues

- Restore remains unexecuted because it would mutate the active database beyond
  the approved reset and no disposable deployment exists.
- The provider-backed intake worker exceeded the shutdown grace during one live
  marker test. The service recovered and archives completed, but this harness
  cannot establish completed graph ingestion under that provider timing.
