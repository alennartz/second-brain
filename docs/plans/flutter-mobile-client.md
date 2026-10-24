# Plan: Flutter mobile client

## Context

Build an Android-first Flutter client for the brain server. The client is a two-action utility: Capture stages a thought, and Ask performs one-shot recall. The approved direction is recorded in [`docs/brainstorms/flutter-mobile-client.md`](../brainstorms/flutter-mobile-client.md).

## Architecture

### Impacted Modules

**Client** — add the Flutter client under `client/mobile/` beside the existing Go client. The Go CLI and TUI remain unchanged. The Flutter client consumes the server through its REST interface and owns its mobile interaction state.

**API** — no server implementation changes. The client uses the existing `GET /health`, `POST /ingest`, and `POST /recall` contracts. Capture retries use the existing `Idempotency-Key` header supported by the intake staging endpoint.

### New Modules

**Mobile client** (`client/mobile/`) — a self-contained Flutter application targeting Android first while keeping Dart code portable for later iOS packaging.

Responsibilities:

- first-launch server setup and stored server URL;
- Capture and Ask tabs with mobile keyboard-aware layout;
- settings route with health status and editable server URL;
- typed REST adapter and typed response models;
- persistent failed Capture drafts and idempotent retries;
- result route with answer rendering and grouped evidence;
- opt-in Flutter analyze, test, and build commands exposed by the repository Makefile.

Dependencies: Flutter Material widgets, the REST server, and the focused packages listed under Technology Choices. It does not import the Go client or server code.

### Interfaces

#### UI to brain gateway

The application shell injects one gateway at the screen seams. Screens do not construct HTTP clients or inspect JSON.

```dart
abstract interface class BrainGateway {
  Future<void> checkHealth();

  Future<IngestReceipt> stageIntake(
    String text, {
    required String idempotencyKey,
  });

  Future<RecallResult> recall(String question);
}
```

`HttpBrainGateway` is the only production adapter for this interface. It receives a normalized base URL and an injectable `http.Client`. Tests can provide a fake gateway or a mocked HTTP client.

The gateway contract is:

- `checkHealth` calls `GET /health` and accepts only a successful response whose JSON status is `ok`.
- `stageIntake` calls `POST /ingest` with `{ "text": text, "hints": [], "source": "mobile" }` and an `Idempotency-Key` header. It returns `IngestReceipt(chunksStored)` from `{ "chunks_stored": number }`.
- `recall` calls `POST /recall` with `{ "question": question, "hints": [] }`. It returns a typed `RecallResult` from `{ "answer": string, "context": Context | null }`.
- The adapter owns URL joining, JSON encoding, response decoding, endpoint timeouts, and HTTP status errors. Health checks use a short timeout. Intake staging and recall use a longer bounded timeout because both can wait on server-side model work.
- Network, malformed-response, and non-success HTTP failures cross the seam as typed client exceptions. Screens keep their input and render an actionable retry state.

#### Gateway models

The gateway maps server responses into models owned by the mobile client:

```dart
final class IngestReceipt {
  final int chunksStored;
}

final class RecallResult {
  final String answer;
  final List<EvidenceItem> evidence;
}

sealed class EvidenceItem {}

final class GraphNodeEvidence extends EvidenceItem {
  final GraphNode node;
  final List<LinkedEdge> links;
}

final class UnprocessedEvidence extends EvidenceItem {
  final IntakeChunk chunk;
}
```

`GraphNode` retains `id`, `table`, and optional `content`, `name`, `type`, `description`, and `summary`. `LinkedEdge` retains `id`, `table`, `from`, `to`, and optional `context`. `IntakeChunk` retains the safe unprocessed-evidence fields exposed by the server: intake ID, chunk position, content, source, hints, and the unprocessed marker.

The evidence projection is a pure mapping inside the gateway or a private domain mapper. It never emits an edge as a standalone item:

- create one graph evidence item for each returned node;
- attach a returned edge once to its `to` endpoint when that node exists, including when both endpoints are returned;
- if only the `from` endpoint exists, attach the edge there;
- if neither endpoint has a returned node, retain the edge on a lightweight linked-record card identified by its endpoint rather than dropping it or rendering a standalone edge card;
- retain each unprocessed chunk as its own evidence item;
- preserve edge context and direction for the node card’s connection row.

When context is `null`, `RecallResult.evidence` is empty and the result view does not show an evidence control.

#### Local persistence

The application injects a small storage seam backed by `shared_preferences`:

```dart
abstract interface class SettingsStore {
  Future<String?> loadBaseUrl();
  Future<void> saveBaseUrl(String value);
  Future<PendingCapture?> loadPendingCapture();
  Future<void> savePendingCapture(PendingCapture value);
  Future<void> clearPendingCapture();
}

final class PendingCapture {
  final String text;
  final String idempotencyKey;
}
```

Only the server URL and one failed Capture draft are persisted. Answers, questions, graph data, and history are not cached.

Capture behavior across this seam is explicit:

- create and persist a new idempotency key before the first request for a new or edited draft;
- retain the same text and key after any failed request;
- retry with the same key;
- clear the pending draft only after a successful staging response;
- load a pending draft on startup without submitting it automatically;
- editing a loaded or failed draft creates and persists a new key.

The setup and settings flows validate an absolute `http` or `https` URL, attempt `/health`, and save the URL even when the health check fails. A failed check reports the failure but does not block later Capture or Ask attempts.

#### Interaction and state seams

The public application seam is an injectable widget:

```dart
MobileApplication({
  required SettingsStore settingsStore,
  required BrainGateway Function(String baseUrl) gatewayForBaseUrl,
  required String Function() createIdempotencyKey,
})
```

The widget owns startup loading and flow composition. The gateway factory receives the configured URL. The key factory supplies new keys for new or edited drafts. Widget tests inject deterministic factories and storage, then exercise visible controls and persisted outcomes.

Accessible control labels are `Save`, `Capture`, `Ask`, `Retry`, and `Evidence`. The settings action has the tooltip `Settings`. Material button style remains an implementation choice. Setup and Settings report health failure while retaining the saved URL. Recall timeout failures use `NetworkException`, as do health and staging timeouts.

The application uses Flutter SDK state local to each flow. No state framework is introduced.

- **Application shell:** gates first launch on stored URL presence, opens Capture by default, owns bottom navigation, and hides navigation on Settings and the result route.
- **Capture screen:** uses a flexible composer and one submit action. It shows a success acknowledgement with the stored chunk count. Failed requests keep the draft and change the action to Retry.
- **Ask composer:** owns one question and submits one recall request. Example questions are optional affordances only and do not create history.
- **Ask result route:** opens immediately in a loading state. Its top bar contains Back and its title only. The body is reserved for loading, answer, evidence, empty-evidence, or retry content. It has no input, bottom navigation, settings control, or other persistent chrome. Back returns to Ask with the question retained.
- **Evidence:** defaults expanded when the response contains evidence. The user can collapse it. Graph edges appear inside their linked node card. Unprocessed evidence remains a separate card.
- **Keyboard adaptation:** composer screens use `Scaffold(resizeToAvoidBottomInset: true)`, safe-area insets, flexible layout constraints, and a scrollable body. Text fields start compact, grow with content, and scroll internally when space is limited. The submit action stays above `MediaQuery.viewInsets.bottom` while the keyboard is open. No fixed tall input box or fixed bottom action may cover the keyboard.
- **System dictation:** Capture uses an ordinary text field. The phone keyboard supplies speech-to-text through its built-in microphone. The app requests no audio permission, records no audio, and adds no transcription service.

The first Android smoke journey is deferred to the manual-test phase because this checkout has no Flutter SDK or Android toolchain. A Flutter-enabled environment must exercise first-launch setup, Capture success, failed Capture retry, Ask recall, expanded evidence, Back from the result route, and submission while the keyboard is open. The exact emulator or physical device remains an environment choice, not an application contract.

### Interaction Mocks

- `docs/mocks/flutter-mobile-client/index.html` — approved low-fidelity interaction contract for setup, Capture, Ask, keyboard-aware submission, Settings, result states, grouped evidence, retry behavior, and the white-and-bronze theme.

### Technology Choices

**Chosen: Flutter SDK state with focused packages.** Use Flutter Material 3 widgets and local `StatefulWidget` state. Add `http` for REST, `shared_preferences` for the server URL and pending Capture, `flutter_markdown` for limited answer Markdown, and `uuid` for stable Capture idempotency keys. Use Flutter’s built-in test tools and HTTP mock adapter support.

This gives the small client a deep gateway interface without introducing a state framework. It also keeps persistence, rendering, and transport replaceable at clear seams.

Alternatives considered:

- **Dio plus Riverpod or Bloc:** offers broader interceptors or provider/event patterns, but adds framework concepts and package surface before the client has shared state or conversation history.
- **SDK-only implementation:** avoids dependencies, but custom Markdown parsing and durable draft storage would create more code and weaker behavior at the exact seams this client needs.

**Chosen: opt-in repository targets.** Add explicit `build-mobile`, `test-mobile`, and `analyze-mobile` Makefile targets. Do not add Flutter to the existing `check-all` target because the repository currently has no Flutter SDK or CI convention. Flutter-enabled environments still get one discoverable entry point for each check.

## Tests

**Pre-test-write commit:** `9effc25e6b033bdcc46d2e1d0a5dbbfd1f31a49f`

### Interface Files

- `client/mobile/pubspec.yaml` — Flutter package metadata and the focused REST, persistence, Markdown, and key-generation dependencies.
- `client/mobile/lib/second_brain_mobile.dart` — public exports for the mobile client seams.
- `client/mobile/lib/src/mobile_application.dart` — public injected application widget boundary.
- `client/mobile/lib/src/gateway/brain_gateway.dart` — `BrainGateway` REST boundary.
- `client/mobile/lib/src/gateway/errors.dart` — typed network, HTTP status, and malformed-response exceptions.
- `client/mobile/lib/src/gateway/http_brain_gateway.dart` — injectable HTTP gateway adapter surface with bounded timeout configuration.
- `client/mobile/lib/src/gateway/models.dart` — typed intake, recall, graph, edge, and grouped evidence models.
- `client/mobile/lib/src/persistence/settings_store.dart` — `SettingsStore`, `PendingCapture`, and the Shared Preferences adapter surface.

### Test Files

- `client/mobile/test/gateway/http_brain_gateway_test.dart` — health, intake, recall, evidence projection, transport failures, and typed response errors.
- `client/mobile/test/persistence/settings_store_test.dart` — server URL and pending Capture draft persistence contracts.
- `client/mobile/test/mobile_application_test.dart` — setup, Capture, Settings, Ask result, evidence, Markdown, and keyboard-aware submission contracts.

### Behaviors Covered

#### HTTP brain gateway

- Health checks use `GET /health` and accept only a successful JSON response with `status: ok`.
- Intake staging sends the mobile source payload and supplied `Idempotency-Key`, then returns `chunks_stored`.
- Recall sends a question with empty hints and maps graph nodes, directed links, and unprocessed chunks into grouped evidence.
- Directed links attach to the returned `to` node, fall back to the returned `from` node, or remain on a linked-record card when neither endpoint is present.
- A null recall context produces an answer with no evidence items.
- Non-success HTTP responses, network failures, and malformed JSON cross the gateway as typed client exceptions.

#### Settings store

- The configured server URL survives a save and load cycle, while an unset URL loads as null.
- A pending Capture retains its text and idempotency key across a save and load cycle.
- A missing pending Capture loads as null, and clearing one removes it.

#### Application widget

- First launch validates the URL and saves valid configuration despite failed health.
- Stored configuration opens Capture by default. Settings hides navigation and saves edited configuration despite failed health.
- Capture persists text and a new key before staging, reports chunk count, and clears successful drafts.
- Failed Capture retains the draft. Retry uses the same key. Startup restores without auto-submission. Editing rotates and persists the key.
- Ask opens a loading result route without composer, navigation, or settings. Back retains the question.
- Successful results render limited Markdown and grouped evidence, expanded by default and collapsible.
- Recall failure offers explicit retry with the same question. Empty evidence hides the Evidence control.
- Both composers retain a visible submit action above keyboard insets without layout overflow.

#### Additional gateway and storage paths

- Each endpoint maps transport, HTTP status, malformed JSON, and deterministic bounded timeout failures to typed exceptions.
- Malformed receipt and recall response shapes fail at the gateway boundary.
- Empty context returns empty evidence. Both-endpoint edges attach once to the `to` card. Orphan edges remain on a lightweight endpoint card.
- Graph and unprocessed evidence retain all defined fields.
- Replacement writes retain only the latest URL and draft, readable through a recreated storage adapter. Clearing the draft retains the URL.

System dictation, absence of audio permissions, Android packaging, and physical keyboard behavior remain static or manual checks. Widget inset tests cover the application layout contract without claiming device validation.

**Local execution:** The Flutter and Dart SDKs are not installed in this checkout, so `flutter test` could not run locally. The new tests are intentionally red against the interface stubs and require a Flutter-enabled environment for the launch check. Review also confirmed that neither `flutter` nor `dart` is available.

**Review status:** approved

## Steps

### Step 1: Generate the Android application scaffold

In a Flutter-enabled environment, run `flutter create --platforms=android --project-name=second_brain_mobile client/mobile` from the repository root. Retain the existing package metadata, public interfaces, and immutable tests. Remove generated sample application code and sample tests, not the existing contract tests.

Resolve the dependencies already declared in `client/mobile/pubspec.yaml` with `flutter pub get`. Use package-manager commands for any manifest changes. Add `client/mobile/analysis_options.yaml` using the declared `flutter_lints` package. Keep generated build output out of Git through `client/mobile/.gitignore`.

In `client/mobile/android/app/src/main/AndroidManifest.xml`, enable Internet access and allow the approved HTTP server URLs. Do not add audio permissions or recording integrations. Keep the application source portable and add no iOS packaging in this phase.

**Verify:** Flutter resolves the existing dependencies. Android scaffolding exists without replacing the contract tests. The main Android manifest permits server requests and contains no audio permission.
**Status:** not started

### Step 2: Implement durable settings and draft storage

Replace the five method stubs in `client/mobile/lib/src/persistence/settings_store.dart`. Keep `SettingsStore`, `PendingCapture`, and the injected `SharedPreferencesSettingsStore(preferences)` interface unchanged.

Store the base URL under one private key. Store the complete pending Capture as one serialized value under a separate private key. Replacement writes retain only the latest value. Decode both draft fields when loading. Return null when the corresponding value is absent. Clear only the draft key, never the server URL. Await preference writes before completing each mutation method.

**Verify:** `flutter test test/persistence/settings_store_test.dart` passes from `client/mobile`, including replacement, recreated-adapter, and clear-retains-URL cases.
**Status:** not started

### Step 3: Implement typed HTTP transport

Replace the endpoint stubs in `client/mobile/lib/src/gateway/http_brain_gateway.dart`. Retain the injected client and existing five-second health and thirty-second request timeout defaults.

Keep URL joining, request encoding, successful-status checks, and JSON object validation private to the adapter. Join normalized base URLs with `health`, `ingest`, and `recall` without duplicate separators. Encode POST bodies as JSON with the JSON content type.

Implement `checkHealth()` with GET and require `status: ok`. Implement `stageIntake()` with text, empty hints, source `mobile`, and the supplied `Idempotency-Key`. Require an integer `chunks_stored` and return the existing `IngestReceipt` model. Implement the recall request with question and empty hints, ready for the projection in Step 4.

Use the existing exceptions in `client/mobile/lib/src/gateway/errors.dart`. Map transport failures and endpoint timeouts to `NetworkException`. Map non-success responses to `HttpStatusException`, preserving status and body. Map invalid JSON and invalid response shapes to `MalformedResponseException`. Do not convert an existing typed HTTP failure into a network or decoding failure.

**Verify:** Health and intake cases in `test/gateway/http_brain_gateway_test.dart` pass, including deterministic timeouts and invalid receipt shapes. Recall transport and status cases pass.
**Status:** not started

### Step 4: Decode recall and group evidence

Complete `recall()` in `client/mobile/lib/src/gateway/http_brain_gateway.dart`. Put private pure decoding and evidence-projection helpers there or in `client/mobile/lib/src/gateway/recall_mapper.dart`. Preserve the public constructors and fields in `client/mobile/lib/src/gateway/models.dart` and the exports in `client/mobile/lib/second_brain_mobile.dart`.

Require a string answer and a context object or null. Map graph nodes and edges to their existing typed fields. Map document chunk `intake_id`, `chunk_index`, `total_chunks`, `content`, `source`, `hints`, and `unprocessed` to the corresponding `IntakeChunk` fields, retaining its record ID. Reject malformed field shapes through `MalformedResponseException`.

Produce one `GraphNodeEvidence` for each returned node. Attach each directed edge once, preferring its returned `to` node and then its returned `from` node. For an orphan edge, create a lightweight `GraphNode` for its `to` endpoint, deriving the table from the record ID. Group orphan links for the same endpoint on that card. Retain direction, table, ID, and context in each `LinkedEdge`. Append separate `UnprocessedEvidence` items for document chunks. Null or empty context yields empty evidence.

**Verify:** `flutter test test/gateway/http_brain_gateway_test.dart` passes from `client/mobile`. Both-endpoint links attach once, orphan links remain visible, and all defined evidence fields survive decoding.
**Status:** not started

### Step 5: Build startup, setup, and settings flows

Implement `client/mobile/lib/src/mobile_application.dart` behind the existing `MobileApplication` constructor. Use local Flutter state for startup and flow composition. Load the stored URL and pending Capture before showing the configured application. Show setup when no URL exists. Otherwise create the gateway with `gatewayForBaseUrl` and open Capture by default.

Add `client/mobile/lib/src/screens/server_settings_screen.dart` for setup and Settings. Validate an absolute HTTP or HTTPS URL with a host. Normalize surrounding whitespace and trailing separators before creating the gateway and saving the URL. Reject invalid input without saving. Check health and save valid configuration even when health fails. Report the health outcome visibly. After setup, open Capture and retain any health-failure notice. Settings saves update the shell's gateway for later requests.

Use `MaterialApp` with Material 3 and the white-and-bronze palette from `docs/mocks/flutter-mobile-client/index.html`. The shell owns Capture and Ask bottom navigation. Its settings action uses tooltip `Settings`. Push Settings without bottom navigation. Use the accessible `Save` button label.

**Verify:** Setup and Settings cases in `test/mobile_application_test.dart` pass. Stored configuration opens Capture. Invalid URLs remain unsaved, failed health does not block configuration, and Settings hides navigation.
**Status:** not started

### Step 6: Implement Capture and explicit retries

Add `client/mobile/lib/src/screens/capture_screen.dart` and compose it from `mobile_application.dart`. Inject the active gateway, settings store, key factory, and startup draft. Keep request state local to this flow.

Restore a pending draft without staging it. For a new or edited draft, create a new key and persist the text/key pair before staging. Editing a restored or failed draft must persist the replacement before submission and must not reuse its old key. Preserve persistence ordering so an older edit cannot overwrite a newer draft or restore a cleared successful draft.

Use `Capture` for normal submission. During staging, prevent duplicate submissions. After failure, retain text and key, report the failure, and expose `Retry`. Retry sends the same text/key pair. After a successful receipt, clear persisted pending Capture, clear the composer, and acknowledge the stored chunk count. Report staging, not completed graph organization.

Use an ordinary multiline text field for keyboard-provided dictation. Introduce no microphone action or transcription integration.

**Verify:** Capture cases in `test/mobile_application_test.dart` pass, including persistence before staging, success clearing, restored drafts, edit key rotation, and stable-key retry.
**Status:** not started

### Step 7: Implement Ask and the isolated result route

Add `client/mobile/lib/src/screens/ask_screen.dart` and `client/mobile/lib/src/screens/recall_result_screen.dart`. Retain the Ask text controller in the composer flow while the result route is open.

On `Ask`, push the result route immediately and start `gateway.recall(question)` there. Its app bar contains only Back and the result title. Do not include input, bottom navigation, or Settings. Display loading until the request completes. Handle typed gateway failures with an actionable message and a `Retry` button. Retry uses the same question. Back returns to the retained composer. Ignore asynchronous UI completion after the route is disposed.

Render successful answers with the declared `flutter_markdown` package. Add `client/mobile/lib/src/widgets/evidence_cards.dart` to render grouped typed evidence without JSON access. Graph cards show node content and directed connection rows with edge context. Orphan endpoint cards use their record identity. Document chunks render as separate unprocessed-evidence cards.

Show `Evidence` only when evidence exists. Expand evidence initially and support collapse. For empty evidence, retain the answer and any empty-state copy without an Evidence control.

**Verify:** Ask loading, Back, failure retry, Markdown, grouped evidence, collapse, and empty-evidence cases in `test/mobile_application_test.dart` pass.
**Status:** not started

### Step 8: Complete keyboard-aware composer layout

Complete layout in `capture_screen.dart`, `ask_screen.dart`, and the shell in `mobile_application.dart`. Match the approved interaction mock without introducing additional persistent controls.

Use `Scaffold(resizeToAvoidBottomInset: true)`, safe areas, flexible constraints, and a scrollable composer body. Start text fields compact, let them grow, and allow internal scrolling when space is limited. Keep submit actions within the resized viewport above keyboard insets. Do not reserve a fixed tall field or place an action behind the keyboard.

**Verify:** The keyboard-inset test in `test/mobile_application_test.dart` passes for both composers at a 400-by-700 viewport with a 300-pixel bottom inset. Both submit buttons remain at or above vertical position 400, with no layout exception.
**Status:** not started

### Step 9: Wire production startup and repository commands

Replace generated `client/mobile/lib/main.dart` with production composition. Initialize Flutter bindings and Shared Preferences, construct `SharedPreferencesSettingsStore`, and inject an owned `http.Client` through the gateway factory. Supply UUID keys through the declared `uuid` package. Run `MobileApplication` through its public seam. Close the owned HTTP client when its production owner is disposed. Screens must not construct transport or storage adapters.

Add opt-in `.PHONY` targets to the repository `Makefile`: `build-mobile` runs `cd client/mobile && flutter build apk`, `test-mobile` runs `cd client/mobile && flutter test`, and `analyze-mobile` runs `cd client/mobile && flutter analyze`. Include help descriptions using the existing `##` convention. Leave `check-all` unchanged.

**Verify:** In a Flutter-enabled environment, `make test-mobile`, `make analyze-mobile`, and `make build-mobile` succeed. `make help` lists all three targets. Static inspection confirms no server or Go client changes. Device journeys remain deferred to the manual-test phase.
**Status:** not started
