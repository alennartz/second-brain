# Review: Local Production Server

**Plan:** `docs/plans/local-production-server.md`
**Diff range:** `a5faf2c554b036ac293176fb519e92cf615c9b97..5b70679cc85f391c34690e51d928e7299803283a`
**Date:** 2026-10-24

## Summary

The fix commit resolves most baseline defects, including the activity parser, image-tag ordering, staged restore, archive locking, reset checks, Make continuations, and archive rotation. The focused suite passes 54 tests, and shell syntax checks pass. The fix still allows an unsafe fail-open service-state check, can restart on a partial safety-copy recovery, leaves a lock gap around updates, and does not verify a clean stop result before archiving.

## Prior Finding Verification

| Prior finding | Status | Verification |
|---|---|---|
| 1. Worker loops prevented every archive | Resolved in code; plan conflict remains | `worker_count` is excluded from the predicate. The plan still says positive `worker_count` means non-idle work. |
| 2. Invalid pipeline snapshots passed as idle | Resolved | The parser requires one JSON object and rejects malformed or multi-value responses. |
| 3. Failed restore started on partial or empty data | Resolved in the extraction path; recovery defect remains | Restore stages extraction and publishes atomically. The safety-copy rollback is unchecked. See Finding 2. |
| 4. Update retagged before pre-update archive | Resolved | The image is tagged only after the pre-update archive succeeds. |
| 5. Backup and restore operations overlapped | Partially resolved | Backup and restore use a lock, but update releases it before installation and restart. The reset procedure does not use it. See Finding 4. |
| 6. Reset procedure was not failure-safe | Resolved in the command sequence; operator-shell defect remains | The procedure checks each operation and recovers on failure. Its shell-scoped execution is unsafe. See Finding 8. |
| 7. Stop success did not prove clean shutdown | Partially resolved | Timeouts are longer, but the archive paths do not verify the systemd stop result. See Finding 5. |
| 8. Backup failed when the service was down | Resolved in code; state detection can fail open | Inactive services skip the endpoint check, but systemd errors and transitional states are treated as inactive. See Finding 1. |
| 9. Restore rejected a missing active database | Resolved | Restore permits a missing active database and avoids starting on an empty path during failure recovery. |
| 10. Signals left the service stopped | Resolved | Exit and signal cleanup recover the prior active state and remove temporary output. |
| 11. `deploy-undeploy` had invalid continuations | Resolved | The recipe uses single-backslash continuations. |
| 12. Rotation matched unrelated files | Resolved in the filename filter; same-second ordering has an edge case | Rotation now uses a timestamp pattern and filename ordering. See Finding 9. |

## Findings

### 1. Service-state detection fails open

- **Category:** code correctness
- **Severity:** critical
- **Location:** `deploy/backup.sh:167-178`, `325-351`
- **Status:** open
- **Fix:** Read `ActiveState`, skip only `inactive` or `failed`, and treat systemd bus errors and transitional states as errors or stop them first.

The inactive-service path treats `systemctl --user is-active` exit statuses for bus failures and transitional states as ordinary inactivity. It can therefore skip the pipeline check and stop operation while the database is still live or while systemd will restart the container. The archive can capture concurrent writes, and a crash-loop can restart during the archive.

### 2. Safety-copy rollback ignores copy failure

- **Category:** code correctness
- **Severity:** warning
- **Location:** `deploy/backup.sh:87-102`
- **Status:** open
- **Fix:** Move the safety copy back with `mv`, or check `cp -a` and forbid service start when recovery fails.

Failure cleanup copies the safety database back with `cp -a` but does not check its status. Disk exhaustion can leave a partial active database, after which cleanup starts the service. The service can then open and write the partial restore.

### 3. The update lock ends before installation and restart

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `deploy/backup.sh:203-211`, `deploy/update.sh:47-50`, `deploy/README.md:152-188`
- **Status:** open
- **Fix:** Hold the deployment lock through image tagging, installation, and restart, and acquire the same lock for the reset procedure.

The backup command releases its lock when the pre-update archive completes. Another daily backup can then stop and restart the service while `update.sh` installs the new unit and restarts it. The reset procedure also runs without the lock. This leaves a race between the update or reset lifecycle and archive operations.

### 4. The plan does not describe the inactive-service exception

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `deploy/backup.sh:320-341`, `369-375`; `deploy/README.md:76-91`
- **Status:** open
- **Fix:** Amend the plan and operator documentation to state that an inactive service skips the pipeline request and remains inactive after a successful archive.

The fix safely skips the pipeline request when the service is inactive and preserves that prior state. The plan still requires the request for daily and pre-update modes and says the service starts after publication. The implementation and plan now specify different operational contracts.

### 5. Archive paths still do not verify a clean stop result

- **Category:** code correctness
- **Severity:** warning
- **Location:** `deploy/backup.sh:349-356`, `499-506`
- **Status:** open
- **Fix:** Require `systemctl --user show -p Result --value` to report `success` before reading or moving the database.

The timeout calculation now allows two grace periods plus margin, but a Docker kill can still produce a successful `systemctl stop` command result. The archive paths proceed without checking the unit result, so they can read a database after an unclean container termination.

### 6. Reset leaves an initially inactive service stopped

- **Category:** plan deviation | code correctness
- **Severity:** warning
- **Location:** `deploy/README.md:152-188`
- **Status:** open
- **Fix:** Start the service unconditionally after a successful safety move; keep prior-state checks only in failure cleanup.

The reset starts the service only when it was active before the reset. If it was initially inactive, SurrealKV does not create the requested fresh active directory, contrary to the reset contract.

### 7. A hung pipeline request now blocks every operation under the lock

- **Category:** code correctness
- **Severity:** warning
- **Location:** `deploy/backup.sh:144`, `203-211`
- **Status:** open
- **Fix:** Add a finite `curl --max-time`, such as 10 seconds, and release the lock on timeout through the existing cleanup path.

The pipeline request has no timeout. The new exclusive lock is held while it runs, so a hung endpoint blocks restores, manual backups, the timer, and later updates indefinitely.

### 8. The reset instructions mutate the operator's interactive shell

- **Category:** code correctness
- **Severity:** nit
- **Location:** `deploy/README.md:141-189`
- **Status:** open
- **Fix:** Present the procedure as a standalone script or a `bash -euo pipefail` heredoc so traps and shell options do not persist in the operator's shell.

Pasting the documented block into an interactive shell enables `set -euo pipefail` and installs an `EXIT` trap that calls `exit`. The successful procedure leaves those settings and the trap in the operator's shell, while a later unrelated command failure can close the session.

### 9. Same-second archive suffixes sort in the wrong order

- **Category:** code correctness
- **Severity:** nit
- **Location:** `deploy/backup.sh:286-304`
- **Status:** open
- **Fix:** Sort the numeric suffix separately, or zero-pad suffixes before reverse sorting.

The collision suffixes are not zero-padded. Reverse lexical ordering ranks the base name and `-2` above `-10`, so a burst of same-second archives can rotate out the newest archive at the seven-file boundary.
