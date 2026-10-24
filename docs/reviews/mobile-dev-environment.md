# Review: Mobile development environment

**Plan:** `docs/plans/mobile-dev-environment.md`
**Diff range:** `eabea4a5455f42cc3bbde8dc077bf0e11e1fea64..61d18bd4a5e4778fdd63950095b5bb893c6d9148`
**Date:** 2026-10-24

## Summary

The fixes resolve the critical toolchain, server URL, test-scope, ADB selection, cache, mDNS, and validation findings from the prior review. Two prior issues remain partial: signal forwarding still does not stop all Flutter child processes, and direct Compose invocation can still expose the server on every interface. The fix diff adds pairing false positives and leaves smaller reproducibility and path-handling risks.

## Prior Findings Verified

- **Resolved:** toolchain image contract. Build arguments now drive the checks, and SDK, Java, Gradle, plugin, Kotlin, and license checks fail correctly.
- **Resolved:** application changes outside the original plan. The plan now allows minimal pinned-toolchain compatibility changes without product-behavior changes.
- **Resolved:** test immutability concern. The plan now records the compatibility-only test adjustment, and no test file changed in the fix diff.
- **Resolved:** unsupported fake-ADB verification claim. The plan now records that the harness does not exist and the checks did not run.
- **Resolved:** fail-open mobile server health check. Compose health is checked even when host `curl` is unavailable.
- **Resolved:** installation using a different ADB daemon. ADB setup now runs before command substitution.
- **Resolved:** wrong server URL port reaching the normal database. URL validation requires port `8200`, and startup checks the mobile container.
- **Partly resolved:** wildcard mobile-server binding. Script validation rejects empty and `0.0.0.0` values, but direct Compose invocation still has no safe default. See Finding 2.
- **Resolved:** missing first-time pairing diagnostics. Connect errors and pairing services now produce guidance. The new logic can also print that guidance when pairing is not required. See Finding 3.
- **Resolved:** recursive cache ownership race. Ownership changes are conditional, and DevTools skips cache preparation.
- **Partly resolved:** interactive command interruption. `--init` was added, but the wrapper shell still keeps non-`exec` Flutter children alive. See Finding 1.
- **Resolved:** leading-zero port parsing.
- **Resolved:** immediate device-state check after connect. The helper now polls for authorization. The extra wait after hard failure remains inefficient. See Finding 7.
- **Resolved:** false mDNS ambiguity. Services are grouped and TLS candidates are preferred.
- **Partly resolved:** duplicated and unenforced toolchain pins. Most pins are checked, but the JDK package version still floats. See Finding 4.
- **Resolved:** incorrect Java PATH construction.
- **Resolved:** hidden Android license failures.
- **Resolved:** stale APK and missing-image checks.
- **Partly resolved:** script and Compose environment-file divergence. Both now receive the selected file, but relative paths can resolve from different directories. See Finding 5.

## Findings

### 1. Non-interactive interrupts still leave Flutter children running

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/run-container:95, mobile-check:10-15, mobile-build:13-17, mobile-debug`
- **Status:** open
- **Fix:** Enable `TINI_KILL_PROCESS_GROUP=1` or `exec` each Flutter command so interrupts reach every child.

The runner now uses `--init`, but Tini forwards SIGINT to its direct wrapper-shell child. The shell does not `exec` the Flutter commands, so `pub get`, `analyze`, or `test` can continue after Ctrl-C and the shell can start the next step. This leaves the documented interruption contract incomplete.

### 2. Direct Compose use can still publish the mobile server on every interface

- **Category:** code correctness
- **Severity:** warning
- **Location:** `docker-compose.yml:32`, `tools/mobile/common.sh:106-118`
- **Status:** open
- **Fix:** Require `MOBILE_SERVER_BIND_ADDRESS` in Compose interpolation or default it to a safe loopback address.

The service now uses `MOBILE_SERVER_BIND_ADDRESS`, and the scripts reject unsafe values. Compose itself has no default. When an operator runs the mobile profile without the wrapper and variable, Docker expands an empty host address and publishes port `8200` on every interface. That preserves the prior debugger-exposure risk through a supported Compose entry point.

### 3. Pairing instructions can appear when pairing is not required

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/common.sh:225-232,289-294,321-322`
- **Status:** open
- **Fix:** Print pairing instructions only after an unauthorized state or an authentication/pairing failure, with mDNS pairing data as supplemental detail.

The helper now detects pairing services, but it prints `adb pair` instructions whenever one is advertised. A pairing service can exist while the selected device failed for another reason. The command then gives a misleading one-time pairing procedure, contrary to the interface requirement that it appear only when authorization is needed.

### 4. The JDK package is still not pinned reproducibly

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `tools/mobile/Dockerfile:17-24`, `tools/mobile/versions.env:12-14`
- **Status:** open
- **Fix:** Pin the exact JDK package version or document and enforce a deliberate major-only JDK policy.

The fix verifies that Java reports version 17, but the apt package remains floating. A later repository update can change the compiler patch release without changing the recorded toolchain inputs. Step 2 requires committed toolchain versions for the materialized image.

### 5. Relative mobile environment paths can still diverge

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/common.sh:139-142`, `docker-compose.yml:33`
- **Status:** open
- **Fix:** Resolve `MOBILE_ENV_FILE` to an absolute repository-relative path before passing it to both scripts and Compose.

The scripts and Compose now accept the same selected environment file, but a relative override is resolved from the caller's current directory by the scripts and from the repository root by Compose. The script can validate one file while Compose loads another.

### 6. The standalone Gradle download has no integrity check

- **Category:** code correctness
- **Severity:** nit
- **Location:** `tools/mobile/Dockerfile:101-112`
- **Status:** open
- **Fix:** Verify the published SHA-256 checksum or remove the standalone download and verify the wrapper distribution instead.

The image downloads a Gradle archive from `services.gradle.org` without checking its checksum. The project uses the wrapper, so the downloaded binary is only needed for version reporting and does not justify an unverified supply-chain input.

### 7. Failed ADB connections wait through the full retry window

- **Category:** code correctness
- **Severity:** nit
- **Location:** `tools/mobile/common.sh:157-192`
- **Status:** open
- **Fix:** Return immediately after a failed connect when the serial is absent, and poll only after a reachable target is found.

The helper now polls for up to ten seconds, but it does so even after `adb connect` fails outright. A single mDNS candidate can cause another ten-second wait before the same failure is reported, slowing diagnostics without improving selection.

### 8. A crashed Compose container produces a misleading startup error

- **Category:** code correctness
- **Severity:** nit
- **Location:** `tools/mobile/mobile-server-up:16-17`
- **Status:** open
- **Fix:** Query all containers with `docker compose ps -aq` or inspect the service state directly.

Using `compose ps -q` without `-a` hides an exited container. If the service crashes during startup, the script reports that it did not create a container instead of showing the exit state. It still exits nonzero, but the diagnostic misdirects the operator.
