# Review: Mobile development environment

**Plan:** `docs/plans/mobile-dev-environment.md`
**Diff range:** `f19871b7f3520a5c77032b76b56a7c89971f974a..eabea4a5455f42cc3bbde8dc077bf0e11e1fea64`
**Date:** 2026-10-24

## Summary

The implementation adds most planned mobile scripts, container seams, and documentation. It is not ready to close: the toolchain image cannot satisfy its build contract, and an invalid mobile server URL can direct phone traffic to the normal server database. The review also found plan deviations and ADB, signal, cache, network, and mDNS edge cases.

## Findings

### 1. Toolchain image contract is not buildable

- **Category:** plan deviation
- **Severity:** critical
- **Location:** `tools/mobile/Dockerfile:26-54`, `tools/mobile/versions.env:5,12`
- **Status:** resolved
- **Fix:** Correct the SDK-tools assertion, enforce the committed version pins, and fail when license acceptance fails.

Step 2 requires a buildable image that reports the committed Flutter, Android, Java, and Gradle versions. The Dockerfile checks an undefined `ANDROID_SDK_TOOLS_VERSION` against `10406996`, so the image build fails or cannot verify the intended value. It also suppresses license failures and does not verify the recorded command-line-tools or Gradle versions.

### 2. A wrong server URL can reach the normal database

- **Category:** code correctness
- **Severity:** critical
- **Location:** `tools/mobile/common.sh:89-93`, `tools/mobile/mobile-server-up:12-31`, `docker-compose.yml:29-46`
- **Status:** resolved
- **Fix:** Require `MOBILE_SERVER_URL` to use port `8200` and verify health through the `server-mobile` Compose service.

Validation checks the URL shape but not its port. A value using port `8000` can pass the health wait against the normal server, while the script reports the mobile server as healthy. The phone can then send Capture and recall traffic to the normal database, breaking the isolated-data contract.

### 3. Application files changed outside the plan

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/android/app/build.gradle:25-26`; `client/mobile/android/app/src/main/res/values/styles.xml:3,9`; `client/mobile/lib/src/gateway/errors.dart:17-19`; `client/mobile/lib/src/mobile_application.dart:314`; `client/mobile/lib/src/screens/capture_screen.dart`; `client/mobile/lib/src/widgets/evidence_cards.dart`
- **Status:** resolved
- **Fix:** Revert application changes or amend the plan with the required compatibility migration before retaining them.

Steps 2 and 6 say not to change application code or upgrade the app to accommodate the toolchain. These Dart, Android, and resource changes are outside the planned environment seams. They need an explicit plan decision before they become part of this implementation.

### 4. Implementation modified an existing test

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/test/mobile_application_test.dart:75-79,174-183`
- **Status:** resolved
- **Fix:** Restore the test and record any intended test changes in a separate test-writing step.

The plan has no `pre-test-write-commit`; using its pre-implementation commit as the fallback baseline shows changes to test timing and assertions. Implementation must not alter the test oracle without a planned test change.

### 5. Claimed fake-ADB verification is absent

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `docs/plans/mobile-dev-environment.md:195-196`
- **Status:** resolved
- **Fix:** Add the fake-ADB smoke harness or mark that verification as unrun.

Step 5 claims coverage for direct authorization, mDNS selection, ambiguous candidates, and pairing diagnostics. The diff contains no fake-ADB harness or tests, so the plan records a verification result that cannot be reproduced from the repository.

### 6. Server startup can report success without health verification

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `tools/mobile/mobile-server-up:18-35`
- **Status:** resolved
- **Fix:** Require `curl` or inspect the Compose health state and fail when `server-mobile` is unhealthy.

When host `curl` is unavailable, the script prints `docker compose ps` and exits successfully without checking `/health`. Step 4 requires health reporting, and the README does not list `curl` as a prerequisite.

### 7. Install can use a different ADB daemon than selection

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/common.sh:118-124`, `tools/mobile/mobile-install:16-21`
- **Status:** resolved
- **Fix:** Export `ADB_SERVER_SOCKET` in the parent shell or pass it explicitly to the install command.

`mobile_select_device` runs inside command substitution, so its `ADB_SERVER_SOCKET=tcp:127.0.0.1:5037` export is lost. If the caller has another ADB socket configured, selection uses the host daemon but installation uses a different daemon and serial.

### 8. The mobile server publishes on every host interface

- **Category:** code correctness
- **Severity:** warning
- **Location:** `docker-compose.yml:31-32`
- **Status:** resolved
- **Fix:** Bind port `8200` to an explicit trusted LAN address supplied by local configuration.

The unauthenticated real-model service uses Docker's wildcard port binding. This can expose stored memory and provider spending on interfaces outside the intended private LAN, including hosts where the firewall does not protect published Docker ports.

### 9. First-time wireless pairing can lack diagnostics

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/common.sh:131-139,164-172,182-183,195-196,209-223`
- **Status:** resolved
- **Fix:** Preserve `adb connect` errors and show pairing guidance for authentication failures or advertised pairing services.

The script prints pairing instructions only when `adb devices` reports `unauthorized`. Android wireless debugging can fail before that state when the host is not paired. The connect output is discarded, leaving the operator without the one-time `adb pair` guidance required by the interface.

### 10. Concurrent container runs recursively chown shared caches

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/run-container:56-71`
- **Status:** resolved
- **Fix:** Change ownership only when the cache root owner differs, and skip cache preparation for DevTools-only runs.

Every invocation recursively changes the full Pub and Gradle cache volumes. The documented parallel `mobile-debug` and `mobile-devtools` workflow can encounter a long ownership walk or a failure while another process writes cache files. This adds avoidable latency and a shared-volume race.

### 11. Interrupts can leave non-interactive containers running

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/run-container:73-86,101-104`
- **Status:** resolved
- **Fix:** Run the container with an init process that forwards signals to the Flutter process group.

The runner does not configure process-group signal forwarding. Ctrl-C can reach the PID 1 shell without stopping its Flutter child, so `mobile-check`, `mobile-build`, or `mobile-install` can continue after the operator interrupts them instead of removing the command container promptly.

### 12. Device state is checked before wireless authorization settles

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/common.sh:135-137`
- **Status:** resolved
- **Fix:** Poll the selected serial until it is authorized or time out with the device state.

The helper reads device state immediately after `adb connect`. A reachable phone can briefly report `connecting` or `authorizing`, causing a false failure and unnecessary mDNS fallback.

### 13. mDNS can falsely report multiple devices

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/common.sh:141-151,202-206`
- **Status:** resolved
- **Fix:** Prefer TLS connect services and deduplicate service records by device rather than by address alone.

The candidate filter accepts both legacy and TLS connect services. One phone advertising both can be treated as two candidates, while an already connected mDNS serial is not recognized. The required single-phone fallback then fails as ambiguous.

### 14. Recorded toolchain pins are duplicated and unenforced

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/versions.env:2-4,12-14`, `tools/mobile/Dockerfile:2,28,32-37`
- **Status:** resolved
- **Fix:** Pass the version file values as build arguments and verify every recorded Gradle, AGP, Kotlin, SDK, and platform-tools version.

The Dockerfile repeats Flutter values as literals and does not consume or verify several values in `versions.env`. Platform-tools and JDK packages float. The image can therefore drift from the documented Gradle and Android contract without a build failure.

### 15. The Dockerfile builds an incorrect Java PATH

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/Dockerfile:8-13`
- **Status:** resolved
- **Fix:** Set `JAVA_HOME` first, then add `$JAVA_HOME/bin` in a separate `ENV` instruction.

`$JAVA_HOME` is expanded while the same `ENV` instruction is evaluated, before the later assignment takes effect. The resulting PATH contains `/bin` instead of the JDK bin directory, and the hard-coded `amd64` path does not match a multi-architecture image.

### 16. APK checks can accept an old artifact

- **Category:** code correctness
- **Severity:** nit
- **Location:** `tools/mobile/mobile-build:19`, `tools/mobile/mobile-install:19`
- **Status:** resolved
- **Fix:** Check that the APK was created or updated by the current build, or remove the redundant post-build existence check.

The existence checks run after a successful build and do not compare the APK timestamp with the build start. A stale APK can satisfy the check if a future build fails to refresh the output through an unexpected path.

### 17. Missing images produce an opaque Docker pull failure

- **Category:** code correctness
- **Severity:** nit
- **Location:** `tools/mobile/run-container:61-67,70-71`
- **Status:** resolved
- **Fix:** Inspect the local image first and tell the operator to run `make mobile-image` when it is absent.

The runner can ask Docker to pull `second-brain-mobile-toolchain` when the project image was never built. The resulting registry access error hides the intended setup command and does not preserve the image contract.

### 18. Port parsing mishandles leading zeroes

- **Category:** code correctness
- **Severity:** nit
- **Location:** `tools/mobile/common.sh:97-100,105-106`
- **Status:** resolved
- **Fix:** Reject leading zeroes or parse decimal values with `10#` before Bash arithmetic.

Bash arithmetic treats values such as `09` as invalid octal and treats `010` as decimal eight. The validators can therefore fail valid-looking input or accept and print a different port than the operator entered.

### 19. Script and Compose environment files can diverge

- **Category:** code correctness
- **Severity:** warning
- **Location:** `tools/mobile/common.sh:11`, `docker-compose.yml:33`
- **Status:** resolved
- **Fix:** Remove the script-only environment-file override or pass the same file explicitly to Compose.

`MOBILE_ENV_FILE` changes which file the scripts validate, but Compose still loads `.env.mobile.local`. The scripts can validate one server URL and start a service with another configuration.
