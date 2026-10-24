# Local Production Server Verification

**Plan:** `docs/plans/local-production-server.md`

## Preconditions

- Use the configured systemd user service and local image.
- Confirm the active database is `BRAIN_DEPLOY_DATA_DIR/brain.db`.
- Record experiment database paths and checksums before operations.
- Confirm the environment file has mode `0600`.
- Keep all credentials out of recorded results.

## One-time fresh start

This operation resets the active database. Do not repeat it during routine updates.

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

Record the date, configured service and image, archive path, checks, and pass/fail result after execution.
These journeys have not yet been executed.
