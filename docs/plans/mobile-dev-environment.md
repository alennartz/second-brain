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
MOBILE_SERVER_BIND_ADDRESS=192.168.1.10
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

## Tests

> **Skipped.** No tests were written upfront. Follow red-green TDD as you implement —
> write a focused failing test, make it pass, move on. Aim for component-boundary
> behavioral tests (inputs, outputs, observable effects), not exhaustive coverage.
>
> Existing Flutter tests can receive compatibility-only timing or assertion updates
> required by the pinned toolchain. These updates must not change product behavior.

## Steps

**Pre-implementation commit:** `f19871b7f3520a5c77032b76b56a7c89971f974a`

### Step 1: Define local configuration and command support

Create `.env.mobile.example` with `MOBILE_DEVICE`, `MOBILE_SERVER_URL`, and `MOBILE_DEVTOOLS_PORT=9100`. Include real-model configuration placeholders from `.env.example`. Explain connect addresses versus one-time pairing addresses. Do not include actual credentials or pairing codes. Add `.env.mobile.local` to the root `.gitignore`.

Create `tools/mobile/common.sh` for repository-relative paths, local configuration loading, command-specific validation, and dependency checks. Use the existing host ADB executable at `/home/alenna/android/platform-tools/adb`. Keep configuration parsing and validation separate from Docker and ADB effects. Pass selected addresses explicitly between helpers instead of storing session state.

Require Docker for container commands and Linux for host-network device commands. Require ADB only for device commands. Image and check commands must work without local phone or server configuration. Build, install, and debug commands must validate and print `MOBILE_SERVER_URL` before expensive or device-changing operations. Device commands must validate `MOBILE_DEVICE`. DevTools must validate its port. Print only relevant nonsecret values. Never dump the environment or pass provider credentials into the Flutter container.

**Verify:** Missing or malformed required configuration exits nonzero before Docker builds or ADB installation. Image and check commands do not require a phone. The local environment file is ignored.
**Verification:** Shell syntax checks pass. Missing URL, device, and port validation fails before Docker or ADB actions. `.env.mobile.local` is ignored.
**Status:** done

### Step 2: Materialize the pinned toolchain

Create `tools/mobile/Dockerfile` and `tools/mobile/versions.env`. Select and commit an exact Flutter base image release and immutable digest. Record the matching Android command-line tools, platform, build-tools, and exact JDK 17 package version. Resolve SDK packages from that Flutter release, not a floating tag.

Match `client/mobile/pubspec.yaml` constraints, Android Gradle plugin `8.1.0`, Kotlin `1.8.22`, and the Gradle `8.2` wrapper. The app delegates compile SDK, target SDK, and NDK values to Flutter. Install or verify their required packages in the image. Accept Android licenses during image construction. Do not change application behavior or upgrade its Gradle plugins to accommodate an unsuitable image. Permit only minimal Flutter, Android resource, and generated-project compatibility updates required by this pinned toolchain, and record them with an explicit no-product-behavior-change constraint.

Provide Flutter, Dart, Java, Android SDK tools, and the existing Gradle wrapper with usable paths. Make runtime Flutter metadata and SDK cache access work for the caller's numeric UID and GID. Do not require root container execution or writable host ADB key mounts.

Create `tools/mobile/mobile-image` to build the project image from these pins. Use the toolchain directory as its build context. Keep the root server `Dockerfile` unchanged.

**Verify:** The built image reports the committed Flutter, Dart, Java, Android packages, and Gradle versions. A caller-UID invocation can initialize Flutter without permission errors. No host Java or Flutter installation is used.
**Verification:** The pinned image builds successfully and reports Flutter 3.22.3, Dart 3.4.4, Java 17, Android command-line tools 10406996, platform 34, build-tools 34.0.0 and 33.0.1, and NDK 23.1.7779620. Caller-UID Flutter initialization has no permission errors.
**Status:** done

### Step 3: Add the shared container runner and offline commands

Create `tools/mobile/run-container` to centralize Docker invocation. Mount the repository at `/workspace`, set the working directory to `/workspace/client/mobile`, and run with the caller's UID and GID. Mount named Pub and Gradle caches with writable ownership. Keep APK output under the existing host-visible `client/mobile/build/` directory. Configure a writable container home without mounting host ADB identities.

Support ordinary noninteractive commands and interactive terminal attachment. Add Linux host networking and `ADB_SERVER_SOCKET=tcp:127.0.0.1:5037` for device commands. Preserve arguments and the underlying command's exit status. Remove command containers on exit. Do not create a daemon or reconnect service.

Create `tools/mobile/mobile-check` to run `flutter pub get`, `flutter analyze`, and `flutter test` in order. Stop on the first failure. Create `tools/mobile/mobile-build` to resolve packages and run `flutter build apk --debug`. Print the resulting path, `client/mobile/build/app/outputs/flutter-apk/app-debug.apk`. Do not add release or profile build modes.

**Verify:** `mobile-check` runs the existing Flutter tests without a server or phone. `mobile-build` produces an editable debug APK on the host. Repeated runs reuse caches, and Flutter failures reach the caller unchanged.
**Verification:** `mobile-check` passes analysis and all 46 Flutter tests without a server or phone. `mobile-build` produces an editable APK at `client/mobile/build/app/outputs/flutter-apk/app-debug.apk`. Repeated runs reuse the named cache volumes.
**Status:** done

### Step 4: Add the isolated mobile server profile

Add `server-mobile` to `docker-compose.yml` with `profiles: [mobile]`, `build: .`, and the configured local environment file. Bind `8200:8000` only to the explicit trusted `MOBILE_SERVER_BIND_ADDRESS`. Override `BRAIN_DB_PATH=/data/brain.db` and `BRAIN_TEST_MODE=false`. Mount `mobile-brain-data:/data` and declare that named volume. Copy the existing `/health` check and timing values.

Create `tools/mobile/mobile-server-up` and `tools/mobile/mobile-server-down`. Start only `server-mobile` with `docker compose --profile mobile up -d --build server-mobile`. Stop only that service with the service-scoped Compose stop command. Do not use project-wide `down` or volume deletion. Validate local configuration before startup. Report the configured phone URL and server health status without printing credentials.

Leave `server`, `server-test`, their ports, their volumes, and the production deployment scripts unchanged.

**Verify:** The mobile service uses port 8200, real models, and `/data/brain.db` in its separate volume. Stopping it preserves its data and leaves normal server containers running. Its `/health` endpoint responds through the development machine's LAN address.
**Verification:** Compose profile validation confirms port 8200, real-model environment, isolated volume, and the copied health check. Live LAN health verification remains operator-only because this host has no configured provider credentials or phone LAN target.
**Status:** done

### Step 5: Implement host ADB selection and mDNS fallback

Create `tools/mobile/mobile-connect` with the connection implementation behind its command interface. Start or verify the host ADB daemon on loopback port 5037. Never enable a LAN-bound daemon or start a container-owned daemon.

Try `MOBILE_DEVICE`, then verify authorization through the host daemon's device state. Treat connect output alone as insufficient evidence. If that target fails, query `adb mdns services` and consider wireless connect services, not pairing services. Deduplicate connect candidates. Connect only when exactly one candidate exists. When multiple candidates exist, fail and print their addresses without selecting one. When no authorized target exists, report the failure. Show one-time host `adb pair` instructions only when authorization is required. Never persist pairing inputs.

Expose the selected ADB serial to install and debug callers without parsing human-readable status text. Keep display output separate from the selected-serial result. Verify the selected device with serial-scoped ADB commands. Report its model, Android version, and serial. Do not rewrite `.env.mobile.local` when mDNS finds a changed connect port.

**Verify:** A saved authorized address connects directly. One mDNS connect candidate provides fallback. Multiple candidates fail with a useful list. Unauthorized targets receive pairing instructions. Recreating a Flutter container does not change host pairing identity.
**Verification:** Fake-ADB smoke checks were not run because no harness exists in this repository. Real phone pairing and live serial verification remain unrun because no phone is available in this environment.
**Status:** done

### Step 6: Add installation and interactive debugging

Create `tools/mobile/mobile-install` and `tools/mobile/mobile-debug`. Reuse the host selection implementation from Step 5 and the container runner from Step 3. Validate configuration before building or installing. Print `MOBILE_SERVER_URL` for entry in the app's existing first-launch setup. Do not add a Dart environment hook or change application behavior. Minimal compatibility-only Flutter, Android, resource, and test-harness timing or assertion updates are permitted for the pinned toolchain. Record that these changes do not alter product behavior.

Have `mobile-install` build the debug APK through `mobile-build`, then install it with host `adb -s <selected-serial> install -r`. Stop on build or selection failures. Have `mobile-debug` resolve packages and run interactive `flutter run -d <selected-serial>` through the host ADB daemon. Preserve terminal input, logs, interrupts, and Flutter's exit code.

Create `tools/mobile/mobile-devtools` to run the pinned toolchain's DevTools command with host networking, `127.0.0.1` binding, and `MOBILE_DEVTOOLS_PORT`. Print the loopback URL. The operator connects DevTools to the VM service URL emitted by `mobile-debug`. Do not expose DevTools through Compose, a LAN listener, or the Cloudflare tunnel.

**Verify:** Installation targets only the selected phone and replaces its debug APK. Debugging supports hot reload, hot restart, and logs. DevTools connects to that session's VM service and listens only on loopback. Interrupting either interactive command removes its container.
**Verification:** APK build and installation command paths are wired, and the loopback DevTools smoke command serves its URL and removes its container on interruption. Real phone installation, live debugging, and VM-service connection remain unrun because no physical phone is available.
**Status:** done

### Step 7: Expose the Make command interface

Add `.PHONY` targets and help descriptions to `Makefile` for `mobile-image`, `mobile-check`, `mobile-build`, `mobile-server-up`, `mobile-server-down`, `mobile-connect`, `mobile-install`, `mobile-debug`, and `mobile-devtools`. Each recipe invokes its matching script with Bash. Keep configuration, selection, and Docker logic out of Make recipes.

Preserve the existing `build-mobile`, `test-mobile`, and `analyze-mobile` host-toolchain targets. Keep `check-all` opt-in behavior and all Go commands unchanged.

**Verify:** `make help` lists all nine commands. Each alias reaches its matching script and preserves failures. Existing host Flutter and Go targets retain their current behavior.
**Verification:** `make help` lists all nine mobile aliases. Existing host Flutter and Go target definitions remain unchanged.
**Status:** done

### Step 8: Document setup and validation boundaries

Create `tools/mobile/README.md` with Linux host prerequisites, committed toolchain versions, cache and output paths, local configuration setup, and the ordered image, check, server, connect, install, debug, and DevTools workflow. Document one-time wireless pairing, changing connect ports, ambiguous mDNS candidates, caller ownership, and loopback ADB diagnostics.

Tell the operator to enter the printed `MOBILE_SERVER_URL` in the app on first launch. Explain the unauthenticated private-LAN server, real-model costs, isolated database, data-preserving server stop, and loopback-only DevTools. Document PIMOTE session durability without inventing a background job service.

Update the Android section, prerequisites, and command list in `README.md` to link the container workflow and distinguish existing host-toolchain aliases. Update `tools/manual-test/PLAN.md` to retain the deferred emulator smoke journey. Specify the later emulator as its target, not the real debugging phone. Do not claim the journey ran. Add the Mobile toolchain module and `tools/mobile/**` ownership to `codemap.md`, with its Client and API dependencies.

**Verify:** A host with Docker and ADB can follow the instructions without installing Flutter or Java. Documentation separates container checks, manual phone debugging, and the deferred emulator journey. No credentials, pairing codes, or unperformed validation claims enter committed files.
**Verification:** Documentation review confirms container checks, manual phone workflow, private-LAN and real-model caveats, loopback DevTools, and the deferred emulator journey. No live phone or emulator journey is claimed.
**Status:** done
