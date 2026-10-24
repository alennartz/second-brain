# Review: Local Production Server

**Plan:** `docs/plans/local-production-server.md`
**Diff range:** `6d669fd125346417d5154e9d93ba96bdcbc94aa1..a5faf2c554b036ac293176fb519e92cf615c9b97`
**Date:** 2026-10-24

## Summary

The implementation covers all seven planned steps, and the focused test suite passes 50 tests. The operational path still has critical defects: the live pipeline reports its worker-loop count as active work, invalid pipeline responses can be accepted, and failed restores or updates can leave the service on the wrong data or image. Several recovery and concurrency paths also do not meet the plan's safety contract.

## Findings

### 1. Running worker loops prevent every archive

- **Category:** code correctness
- **Severity:** critical
- **Location:** `deploy/backup.sh:51-66`
- **Status:** resolved
- **Fix:** Remove `worker_count` from the activity predicate, or expose a separate count for workers processing leases rather than long-lived worker loops.

`worker_count` is the number of live ingestion worker tasks, not the number of active intake operations. The default service therefore reports at least one worker while it is running. Daily backups always defer, and pre-update backups always fail, so `make deploy` cannot complete and no archive is created.

### 2. Invalid pipeline snapshots can pass as idle

- **Category:** plan deviation
- **Severity:** critical
- **Location:** `deploy/backup.sh:76-89`
- **Status:** resolved
- **Fix:** Remove the trailing-brace retry and require exactly one JSON value before evaluating activity fields.

The parser retries a failed `jq` parse after deleting one trailing `}`. It also accepts multiple JSON values and compares only the resulting text to `true`. Malformed responses can therefore be treated as idle, allowing the script to stop the service and archive without a valid quiescence check. Step 3 requires request or parsing errors to fail closed as non-idle.

### 3. Failed restore extraction starts the service on wrong data

- **Category:** code correctness
- **Severity:** critical
- **Location:** `deploy/backup.sh:345-362`
- **Status:** resolved
- **Fix:** Extract into a staging directory, remove it on failure, restore the safety copy, then recover the service.

The command moves the active database to the safety copy before extraction. On extraction failure, recovery starts the service while the partial or missing active directory remains. SurrealKV can then open partial data or create an empty database, making the service appear healthy while serving incorrect state.

### 4. The update retags the image before the pre-update archive

- **Category:** code correctness
- **Severity:** critical
- **Location:** `deploy/update.sh:33-37`
- **Status:** resolved
- **Fix:** Build to an image ID without changing the configured tag, archive first, then tag the successful image before installation and restart.

`docker build -t "$BRAIN_IMAGE"` changes the running tag before `backup.sh pre-update` stops and starts the service. Archive failure recovery can start the new image, and an installation failure leaves that new image under the old unit. The documented guarantee that archive failure leaves the running service untouched is false.

### 5. Backup and restore operations can overlap

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `deploy/backup.sh:134-177`, `204-244`, and `335-362`
- **Status:** resolved
- **Fix:** Acquire one exclusive lock for the complete backup or restore lifecycle and publish archive names with an atomic no-clobber retry.

The timer, manual backups, restore, and update share no lock. Two invocations can stop the service concurrently, archive while the other operation moves the database, and start the service in the middle of extraction. The existence check followed by `mv` can also overwrite an archive selected by another invocation. This violates the quiesced snapshot and unique-name requirements.

### 6. The reset procedure is not failure-safe

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `deploy/README.md:137-147`
- **Status:** resolved
- **Fix:** Run the reset commands with fail-fast checks and move the active database only after successful stop and archive operations.

The documented one-time reset does not chain or check `systemctl stop`, `tar`, `chmod`, or archive setup. A failed stop or archive can still reach the move and start commands, risking a live-database move or a reset without a recovery archive.

### 7. A successful stop does not prove a clean shutdown before archiving

- **Category:** code correctness
- **Severity:** warning
- **Location:** `deploy/backup.sh:219` and `335`; `deploy/install.sh:80-81`
- **Status:** resolved
- **Fix:** Verify a successful systemd stop result before archiving and size Docker and systemd timeouts for the full ingestion shutdown path.

The ingestion pipeline can wait through its grace period and a post-cancel wait, then the scheduler and storage still shut down. The Docker timeout is only `ceil(grace)+1`, so Docker can kill the container while systemd still reports a successful stop. The script can then archive a database that did not close cleanly.

### 8. Pre-update backup cannot recover when the service is already down

- **Category:** code correctness
- **Severity:** warning
- **Location:** `deploy/backup.sh:72` and `383-400`
- **Status:** resolved
- **Fix:** Skip the HTTP pipeline check when the service was inactive, archive the quiescent database, and preserve the prior inactive state.

Both modes require a reachable `/ingest/pipeline` endpoint. A stopped or crash-looping service makes `pre-update` fail, which prevents deploying a fix when an update is most needed. Daily mode defers successfully without a useful alert and can remain deferred indefinitely.

### 9. Restore is blocked when the active database is missing

- **Category:** code correctness
- **Severity:** warning
- **Location:** `deploy/backup.sh:326-330`
- **Status:** resolved
- **Fix:** Allow restore to proceed when the active database directory is absent and is not a symlink.

The command rejects a missing active database before it can restore the selected archive. That is a primary recovery case and should not require a safety move for a directory that does not exist.

### 10. Failure signals can leave the service stopped

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `deploy/backup.sh:204-244`
- **Status:** resolved
- **Fix:** Add an exit and signal cleanup path that removes temporary output and recovers only a service that was active before the operation.

After stopping the service, an interrupt or termination during archive creation exits without cleanup or prior-state recovery. The plan requires failure paths to remove temporary output and recover the prior active state.

### 11. `deploy-undeploy` has invalid Make continuations

- **Category:** code correctness
- **Severity:** warning
- **Location:** `Makefile:117-121`
- **Status:** resolved
- **Fix:** Use one backslash at each recipe line end.

The recipe uses `\\` instead of `\`. GNU Make does not treat that as a continuation, so the shell receives a literal backslash command and exits before disabling or removing any units.

### 12. Archive rotation matches unrelated operator files

- **Category:** code correctness
- **Severity:** warning
- **Location:** `deploy/backup.sh:192`
- **Status:** resolved
- **Fix:** Match only timestamped archive names and order them by their timestamped filename rather than filesystem mtime.

The broad `daily-*.tar.gz` and `pre-update-*.tar.gz` patterns include operator-created files such as `daily-keep.tar.gz`. Rotation also uses mtime, so copying an old archive can displace a real archive from the seven-file retention set.

The focused `tests/test_local_production_server.py` suite passed, but it does not cover the live worker count, malformed multi-value responses, concurrent invocations, or the reset failure path.
