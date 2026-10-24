# Test Review: Flutter mobile client

**Plan:** `docs/plans/flutter-mobile-client.md`
**Brainstorm:** `docs/brainstorms/flutter-mobile-client.md`
**Date:** 2026-10-24

## Summary

The original tests covered transport and storage but omitted the core mobile interaction contract. The approved changes add an injected application boundary, widget coverage, and missing gateway paths. Tests use mocked transport, storage, keys, and virtual time, but require a Flutter-enabled environment for execution.

## Findings

### 1. Mobile interaction contracts had no tests

- **Category:** missing coverage
- **Severity:** critical
- **Location:** `client/mobile/test/mobile_application_test.dart:92-221`
- **Status:** resolved

The brainstorm requires Capture-first navigation, safe failed drafts, one-shot Ask, readable answers, and collapsible evidence. The architecture also specifies first-launch setup, Settings, result routing, and keyboard adaptation. No application interface or widget tests covered these behaviors. The user approved adding `MobileApplication` with injected storage, gateway factory, and key factory. The plan now defines this public seam and its accessible controls. Widget tests cover setup, Capture, retry keys, draft restoration and editing, Settings, result loading and retry, Back, Markdown, grouped evidence, and keyboard insets. System dictation, audio permissions, and Android packaging remain static or manual checks, as approved.

### 2. Endpoint timeouts lacked deterministic coverage

- **Category:** missing coverage
- **Severity:** warning
- **Location:** `client/mobile/test/gateway/http_brain_gateway_test.dart:27-61`
- **Status:** resolved

The architecture promises bounded health and request timeouts. The user approved mapping timeout failures to `NetworkException`. Tests now hold mocked HTTP responses pending and advance widget-test virtual time. They cover all three endpoints without sleeping or using network state.

### 3. Gateway and persistence paths were incomplete

- **Category:** missing coverage
- **Severity:** warning
- **Location:** `client/mobile/test/gateway/http_brain_gateway_test.dart:27-108`, `client/mobile/test/persistence/settings_store_test.dart:15-28`
- **Status:** resolved

Each endpoint now has transport, HTTP status, and malformed JSON coverage. Added cases reject invalid receipt and recall shapes, cover empty context, retain model fields, and attach an edge once to the returned `to` node when both endpoints exist. Storage tests verify replacement writes, a recreated adapter, and URL retention after clearing a draft. These additions exercise public adapter results rather than storage keys or private mapping functions. The user approved the additions.

### 4. Orphan-edge assertion selected an unspecified endpoint

- **Category:** over-specified
- **Severity:** warning
- **Location:** `client/mobile/test/gateway/http_brain_gateway_test.dart:257-263`
- **Status:** resolved

The original test required the missing `to` endpoint as the lightweight card identity. The contract requires an endpoint card but does not select an endpoint when neither node exists. The revised assertion accepts either endpoint and still requires the orphan edge on a graph evidence card. The user confirmed that standalone edge cards are forbidden. The plan also states that both returned endpoints attach the edge once to the `to` card.

## Validation limits

Neither `flutter` nor `dart` is installed in this checkout. Tests could not run locally and remain intentionally red against interface stubs. The Android smoke journey still requires a Flutter-enabled emulator or device. No tests depend on real network state, random keys, filesystem ordering, or elapsed wall-clock time.
