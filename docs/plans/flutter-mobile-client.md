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
- attach a returned edge to its `to` endpoint when that node exists;
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
- `client/mobile/lib/src/gateway/brain_gateway.dart` — `BrainGateway` REST boundary.
- `client/mobile/lib/src/gateway/errors.dart` — typed network, HTTP status, and malformed-response exceptions.
- `client/mobile/lib/src/gateway/http_brain_gateway.dart` — injectable HTTP gateway adapter surface with bounded timeout configuration.
- `client/mobile/lib/src/gateway/models.dart` — typed intake, recall, graph, edge, and grouped evidence models.
- `client/mobile/lib/src/persistence/settings_store.dart` — `SettingsStore`, `PendingCapture`, and the Shared Preferences adapter surface.

### Test Files

- `client/mobile/test/gateway/http_brain_gateway_test.dart` — health, intake, recall, evidence projection, transport failures, and typed response errors.
- `client/mobile/test/persistence/settings_store_test.dart` — server URL and pending Capture draft persistence contracts.

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

**Local execution:** The Flutter and Dart SDKs are not installed in this checkout, so `flutter test` could not run locally. The new tests are intentionally red against the interface stubs and require a Flutter-enabled environment for the launch check.
