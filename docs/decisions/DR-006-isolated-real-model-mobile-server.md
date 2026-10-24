# DR-006: Isolated Real-Model Mobile Server Profile

## Status
Accepted

## Context

The Flutter client cannot reach a development server through the phone's loopback interface. It needs a private-LAN endpoint, and live debugging must exercise the real model path rather than only the test model. Mobile work must not mutate the normal knowledge database.

Reusing the normal Compose service and `brain-data` volume would mix phone experiments with working knowledge. A test-mode service would avoid credentials and provider cost, but would not represent the behavior being debugged. A separate Compose file would duplicate the server image, health check, and lifecycle configuration. Binding a service to every host interface would widen an unauthenticated API beyond the trusted development LAN.

## Decision

Add `server-mobile` to the existing Compose file under the `mobile` profile. Load the ignored `.env.mobile.local` file, force real models, override the database path to `/data/brain.db`, and mount a dedicated `mobile-brain-data` volume. Publish port 8200 only through the explicitly configured `MOBILE_SERVER_BIND_ADDRESS`. Reuse the server image and health check, and provide service-scoped start and stop scripts that preserve the mobile volume and leave the normal server untouched.

Treat the profile as a trusted private-LAN development endpoint. Do not add a second authentication layer in this scope. Keep provider credentials and changing device values in the ignored local file, and print only the non-secret mobile URL and health information from the scripts.

## Consequences

- Phone debugging uses realistic intake and recall behavior while keeping mobile data separate from the normal database.
- Operators must provide real provider credentials, accept model usage costs, choose a reachable private-LAN bind address, and protect that network because the endpoint has no new authentication.
- The existing server and production deployment remain unchanged, while the mobile profile has its own lifecycle and data-retention behavior.
- The phone's first-launch URL points to the development machine's LAN address and port 8200, not to loopback.
- No connected phone or Android emulator was available for this phase. Client installation, live debugging, and the later emulator smoke journey remain deferred even though containerized checks and the debug APK build passed.
