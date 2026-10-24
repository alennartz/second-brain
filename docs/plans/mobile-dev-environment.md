# Plan: Mobile development environment

## Context

Provide a Docker-based development environment for the Android-first Flutter client. The environment must build APKs, run automated widget checks, install debug builds on one wireless-debugged phone, and support interactive Flutter debugging without installing Java or Flutter on the host. The approved exploration is recorded in [`docs/brainstorms/mobile-dev-environment.md`](../brainstorms/mobile-dev-environment.md).

The host already has Docker and ADB at `/home/alenna/android/platform-tools/adb`, but no Flutter, Dart, JDK, Android SDK manager, or emulator. The existing Compose file already uses profiles and named volumes for server variants. DR-004 remains settled context for the Flutter application architecture.

## Architecture

### Impacted Modules

**Client** — keep the Flutter application under `client/mobile/`. Add development scripts and Make aliases around it. The Flutter application code does not gain build-environment logic. Existing Go client commands remain unchanged.

**API** — add a `server-mobile` Compose profile that runs the existing server image with a separate database volume, real model configuration, and a dedicated private-LAN port. The normal server and production loopback deployment remain unchanged.

**Manual Test Tools** — retain the deferred Android emulator smoke journey. It will target the later emulator environment, not the real debugging phone. No on-device automated suite is added now.

### New Modules

**Mobile toolchain** (`tools/mobile/`) — owns the project Dockerfile, version pins, cache mounts, local configuration loading, container command wrappers, host ADB connection, mDNS fallback, APK installation, and loopback DevTools launch.

Dependencies: Docker, host ADB, the `client/mobile/` Flutter project, and the `server-mobile` Compose profile. It does not own ADB pairing keys or server data.

**Mobile development server profile** (`docker-compose.yml`) — a Compose service named `server-mobile` under the `mobile` profile. It builds the existing server image, loads `.env.mobile.local`, overrides `BRAIN_DB_PATH=/data/brain.db`, mounts a dedicated `mobile-brain-data` volume, publishes a dedicated LAN port such as `8200`, and uses the existing `/health` health check. It runs with real models. The profile is for a trusted private LAN and does not add authentication.

### Interfaces

#### Local mobile configuration

Commit `.env.mobile.example` with safe placeholders and ignore `.env.mobile.local`. The local file carries values such as:

```text
MOBILE_DEVICE=192.168.1.42:37123
MOBILE_SERVER_URL=http://192.168.1.10:8200
MOBILE_DEVTOOLS_PORT=9100
```

`MOBILE_DEVICE` is the wireless ADB connect address, not the host ADB server port and not the brain server URL. Pairing addresses and pairing codes are one-time inputs and never persist in repository configuration. Provider credentials remain in the ignored environment file.

The scripts validate required values, print the effective target without secrets, and fail before building or installing when the configuration is incomplete.

#### Toolchain container

The project-owned Dockerfile starts from a pinned Flutter base image. It adds or verifies the exact Android command-line tools, SDK platforms, build tools, JDK 17, and Gradle compatibility required by the app’s Android project. The image pins one Flutter release instead of using a floating stable tag. The exact release and Android package versions are selected and committed when the image is first materialized because the current checkout has no Flutter toolchain.

Each container command:

- mounts the repository at a stable workspace path;
- mounts named Pub and Gradle cache volumes;
- mounts host-visible build output;
- runs with the caller’s UID and GID so generated files remain editable;
- uses `ADB_SERVER_SOCKET=tcp:127.0.0.1:5037` with Linux host networking when device access is needed;
- returns the underlying Flutter or Gradle exit code.

The container owns Flutter, Dart, Java, Gradle, and Android SDK tools. The host owns Docker, ADB, the ADB key, and wireless pairing.

#### Host ADB and device selection

`mobile-connect` is the host-side seam:

1. start or verify the host ADB server on `127.0.0.1:5037`;
2. try the saved `MOBILE_DEVICE` connect address;
3. if it fails, query `adb mdns services` through the host daemon;
4. connect the only discovered wireless device and report its address;
5. fail with the discovered candidates when selection is ambiguous;
6. show the one-time `adb pair` instructions only when the phone is not authorized.

The first release optimizes for one phone. The helper must never select an arbitrary device when more than one candidate is visible. Recreating the Flutter container must not recreate the ADB identity or require pairing again.

#### Command interface

Expose thin shell commands under `tools/mobile/` and short Make aliases:

```text
make mobile-image
make mobile-check
make mobile-build
make mobile-server-up
make mobile-server-down
make mobile-connect
make mobile-install
make mobile-debug
make mobile-devtools
```

Contracts:

- `mobile-image` builds or refreshes the pinned toolchain image.
- `mobile-check` runs `flutter pub get`, `flutter analyze`, and `flutter test` in the container. It does not require a phone or server.
- `mobile-build` produces a debug APK in a host-visible output path. Release signing and profile builds are out of scope.
- `mobile-server-up` and `mobile-server-down` control only the Compose `mobile` profile and its isolated volume. They never touch the normal server or database.
- `mobile-connect` performs host ADB connection and verification. It reports the selected model, Android version, and ADB serial.
- `mobile-install` installs or replaces the debug APK on the selected phone with ADB.
- `mobile-debug` runs an interactive `flutter run` session against the selected phone. It provides hot reload, hot restart, logs, and the Flutter VM service.
- `mobile-devtools` starts Flutter DevTools on loopback for the PIMOTE agent. It never binds a LAN interface and never uses the Cloudflare tunnel.

Commands are ordinary Bash invocations. They do not create a job database, persistent build daemon, or custom reconnect service. PIMOTE supplies session durability when an agent client disconnects.

#### Server and client connectivity

The phone uses `MOBILE_SERVER_URL` for the isolated server profile. The URL points to the development machine’s LAN address and dedicated port. The server profile binds only for private-LAN development. The mobile app’s existing first-launch URL setup remains the runtime fallback.

The Flutter debug process reaches the phone through host ADB. DevTools reaches the Flutter VM service through the Flutter/ADB forwarding established by the debug command and remains local to the development machine.

#### Validation boundaries

- Automated local checks: Flutter analyze and widget tests in the toolchain container.
- Real phone: manual `mobile-connect`, install, and live `mobile-debug` sessions only.
- Later emulator: Autoflow-style smoke journey for setup, Capture, retry, Ask, evidence, Back navigation, and keyboard submission.
- No real-phone integration suite, release signing, iOS packaging, or public DevTools exposure in this scope.

### Technology Choices

**Chosen: project Dockerfile from a pinned Flutter base image.** This keeps the repository in control of the image contract while avoiding a hand-maintained Flutter and Android installation from a generic Debian base. A floating public image was rejected because it would silently change the compiler, SDK, and Gradle inputs. Building every tool from scratch was rejected because it adds maintenance without improving this project’s first environment.

**Chosen: host ADB server with Linux host networking.** The host already owns USB and wireless pairing. The container uses the host ADB server through `ADB_SERVER_SOCKET` and cannot create a second pairing identity. Direct container-owned ADB was rejected because recreated containers would lose pairing state. Binding the host ADB server to a LAN interface was rejected because it exposes a device-control port unnecessarily.

**Chosen: existing Compose file with a `mobile` profile.** This follows the repository’s existing `server-test` profile and keeps the server image, health check, and commands discoverable. A separate Compose file was rejected because it would duplicate server configuration.

**Chosen: thin shell scripts with Make aliases.** Shell scripts keep Docker, ADB, mDNS, and error handling in one readable implementation. Make provides discoverable entry points without becoming a job runner. Inline Make-only recipes were rejected because quoting and platform checks would spread across the Makefile.

**Chosen: real models with an isolated database.** Live phone debugging needs realistic recall and intake behavior. Test mode remains appropriate for the later emulator smoke profile, but it would not exercise the real model path used during manual debugging. Reusing the normal database was rejected because mobile work could mutate working knowledge.

**Chosen: loopback-only DevTools.** The PIMOTE agent runs on the development machine and is the only intended DevTools operator. LAN and tunnel exposure would add an unnecessary debugger attack surface.
