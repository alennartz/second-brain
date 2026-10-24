# DR-005: Pinned Mobile Toolchain with Host-Owned ADB

## Status
Accepted

## Context

The Android-first Flutter client needs reproducible checks, debug APK builds, and interactive phone debugging. The development host does not have Flutter, Dart, Java, or the Android SDK. Recreating a development container must not recreate wireless-debugging pairing state or leave generated files owned by root.

A host-installed toolchain would add setup steps and permit compiler and SDK drift. A floating Flutter image would silently change build inputs. Installing every dependency into a generic base image would create a second toolchain contract to maintain. Running ADB inside the container would lose pairing state when the container is replaced, while exposing the host ADB daemon on the LAN would add an unnecessary device-control surface.

## Decision

Own the Flutter and Android toolchain in a project Docker image pinned to an immutable Flutter image digest and committed versions for the Android command-line tools, SDK platforms, build tools, NDK, JDK 17, and Gradle compatibility. Run commands through thin repository scripts. Mount named Pub and Gradle caches, the repository, and host-visible build output. Run the container with the caller's UID and GID so generated files remain editable.

Keep the ADB daemon and wireless-debugging identity on the Linux host. Device commands use the host daemon on loopback through `ADB_SERVER_SOCKET` and host networking. The scripts select the saved wireless connect address or one unambiguous mDNS connect candidate, and never persist pairing inputs. DevTools binds to loopback on the development host instead of exposing a debugger to the phone's LAN or a tunnel.

## Consequences

- Builds and widget checks use fixed compiler and SDK inputs without requiring Flutter or Java on the host.
- The repository must maintain the pinned image and its package versions, and device commands require Linux, Docker, and host ADB.
- Pub and Gradle caches persist outside command containers, while generated APKs remain visible and editable on the host.
- Pairing keys remain available across container recreation, but pairing and live device sessions remain operator-managed; the container cannot provide a device when none is connected.
- The current environment passed containerized Flutter checks and the debug APK build. No connected phone or Android emulator was available, so real-phone installation, live debugging, VM-service connection, and the later emulator smoke journey remain deferred.
- Loopback-only DevTools limits debugging access to the development host. A future remote debugging workflow would need a separate security decision.
