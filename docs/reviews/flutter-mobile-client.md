# Review: Flutter mobile client

**Plan:** `docs/plans/flutter-mobile-client.md`
**Diff range:** `9effc25e6b033bdcc46d2e1d0a5dbbfd1f31a49f..b2f99affc2c7310143285b8932f6d5a9aeac2301`
**Date:** 2026-10-24

## Summary

The implementation covers the planned Flutter modules and keeps the listed test files immutable. The gateway, persistence, setup, Capture, Ask, evidence, and keyboard flows are present, but Capture is unusable on first entry because its submit action does not react to typing. Several additional navigation, response-validation, timeout, and URL-handling risks remain open.

## Findings

### 1. Capture submission never enables after typing

- **Category:** code correctness
- **Severity:** critical
- **Location:** `client/mobile/lib/src/screens/capture_screen.dart:70,148,158-181`
- **Status:** open
- **Fix:** Call `setState` from `_textChanged` for every text change, or listen to the controller when building the button.

`build` computes whether the Capture button is enabled, but `_textChanged` only calls `setState` after a failed request. Typing into an initially empty composer therefore never rebuilds the parent, so the button stays disabled on first use and after a successful capture. The Capture widget tests also fail on this path.

### 2. Malformed recall context is silently accepted

- **Category:** plan deviation
- **Severity:** warning
- **Location:** `client/mobile/lib/src/gateway/http_brain_gateway.dart:153-165`
- **Status:** open
- **Fix:** Validate the `context` key and nested array shapes; accept only an explicit `context: null` or a valid context object.

Step 4 requires a context object or `null` and requires malformed response fields to raise `MalformedResponseException`. The decoder treats a missing context, or missing or null `nodes`, `edges`, and `unprocessed` fields, as empty evidence. A malformed server response can therefore hide evidence without reporting an error.

### 3. Leaving Settings during health checking does not update the active gateway

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/screens/server_settings_screen.dart:200-227`
- **Status:** open
- **Fix:** Call `widget.onSaved(normalized, gateway, healthFailure)` before the `mounted` guard.

The screen saves the new URL before waiting for health, but it calls `onSaved` only after the health request. If the user presses Back while the check is pending, the screen unmounts and the callback is skipped. Storage then contains the new URL while the running application still uses the old gateway.

### 4. Capture can report failure after the server stages the request

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/gateway/http_brain_gateway.dart:16,63`
- **Status:** open
- **Fix:** Give `stageIntake` its own longer timeout, such as five minutes for server-side chunking and embedding.

The mobile adapter uses a 30-second request timeout for intake. The server performs chunking and embedding before returning, and the existing Go client allows five minutes. A long Capture can therefore be accepted by the server while the phone reports a failed Capture. The idempotency key prevents duplication, but the user receives an incorrect failure and must retry manually.

### 5. Draft persistence has dead branches and duplicated sequencing

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/screens/capture_screen.dart:43-46,207-209,229-263`
- **Status:** open
- **Fix:** Merge `_scheduleDraft` and `_clearDraft` into one revision-aware storage queue and remove unreachable error branches and `_clearRequested`.

`_storageTail` always ends in a swallowed error handler, so the later `onError` branches never run. Every schedule and clear increments the revision, making the `_clearRequested` checks redundant. The two methods also duplicate the sequencing for the same draft-storage operation, violating the codebase rule that one business operation has one implementation and increasing drift risk.

### 6. Route transitions expose a blank shell

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/mobile_application.dart:193,225-226,251,262,282,293-295`
- **Status:** open
- **Fix:** Use a zero-duration transition for the route, or keep the shell visible and hide only its navigation bar.

`_routeOpen` hides the application shell as soon as a result or settings route starts and shows it only after the route finishes popping. During both push and Back animations, the moving route reveals a blank page behind it. Navigator already covers the shell, so this extra state creates a visible transition defect.

### 7. A failed health notice remains after later successful Capture

- **Category:** code correctness
- **Severity:** nit
- **Location:** `client/mobile/lib/src/mobile_application.dart:200,274`
- **Status:** open
- **Fix:** Clear `_healthNotice` after a successful Capture or when the configured gateway succeeds.

A failed setup health check leaves its notice on Capture indefinitely. The application can later stage Captures successfully, but the stale warning still suggests that the configured server is unhealthy.

### 8. Query and fragment URLs pass validation but build invalid endpoints

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/lib/src/screens/server_settings_screen.dart:231-239`
- **Status:** open
- **Fix:** Reject normalized URLs when `uri.hasQuery` or `uri.hasFragment` is true.

The URL validator accepts query strings and fragments. Endpoint joining then appends a path after those components, producing malformed requests such as `http://host/?x/health`. The setup and Settings flows report a saved configuration that cannot be used.

### 9. Older `http` versions can corrupt non-ASCII answers

- **Category:** code correctness
- **Severity:** warning
- **Location:** `client/mobile/pubspec.yaml:14`, `client/mobile/lib/src/gateway/http_brain_gateway.dart:126`
- **Status:** open
- **Fix:** Raise the `http` lower bound to `^1.4.0`, or decode response bytes explicitly as UTF-8.

The adapter reads `response.body` while allowing older `http` versions that decode JSON without a charset as Latin-1. FastAPI responses can omit the charset, so non-ASCII answers and evidence can render with corrupted characters.
