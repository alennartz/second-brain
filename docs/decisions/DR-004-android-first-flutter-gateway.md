# DR-004: Android-First Flutter Client with a Typed Gateway Seam

## Status
Accepted

## Context

Second Brain needed a small mobile client for two fast actions without coupling the server to a mobile UI. The first release targets Android, but a second native implementation for iOS would duplicate the client behavior. The client also needed transport, persistence, and screen behavior that could be tested without a live server or device. The repository has no existing Flutter CI convention, and this checkout does not have a Flutter or Android toolchain.

The main alternatives were a native Android implementation, a broader Flutter stack with Dio and Riverpod or Bloc, and an SDK-only Flutter implementation. Native Android would make later iOS packaging a second implementation. A state framework would add concepts and dependencies before the client had shared state or history. SDK-only code would avoid dependencies but require custom Markdown rendering and durable storage logic.

## Decision

Build an Android-first Flutter client while keeping its Dart code portable. Expose one injected `BrainGateway` interface at the application boundary. Keep `HttpBrainGateway` as the production REST adapter, with typed request and response models and typed transport, status, and malformed-response errors. Inject the gateway, settings store, and key factory into the application so widget tests can replace each boundary.

Use Flutter SDK local state and focused packages: `http` for REST, `shared_preferences` for local settings and draft persistence, `flutter_markdown` for limited answer rendering, and `uuid` for stable capture keys. Add explicit `build-mobile`, `test-mobile`, and `analyze-mobile` Makefile targets, but keep them out of `check-all` so environments without Flutter do not lose the existing repository checks.

## Consequences

- The mobile UI, persistence, and transport remain replaceable and testable through small seams.
- The client stays independent from the Go client and server implementation while relying on the server's REST contracts.
- Flutter and Android tooling are required for mobile checks, APK builds, and the deferred Android smoke journey. Those checks cannot run in the current checkout.
- iOS packaging remains future work, but the Dart code does not depend on Android-only UI code.
- Local state and focused dependencies keep the first release small. A future need for shared state, richer networking, or conversation history can justify revisiting the stack.
- Mobile targets are discoverable without forcing Flutter installation or execution on every repository check.
