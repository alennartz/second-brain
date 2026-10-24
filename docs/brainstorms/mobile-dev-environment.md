# Mobile development environment

## The idea

Create a simple Docker-based Flutter development environment for the Android mobile client. It must support repeatable builds and widget tests, wireless live debugging on a real phone, and a separate server endpoint for mobile work without requiring Java or Flutter on the host.

## Key decisions

- **Provide both ordinary checks/builds and interactive debugging.** Bash or Make invocations are enough. PIMOTE already preserves agent sessions across client disconnects, so no custom job runner, daemon, or tmux requirement belongs in this scope.
- **Use a project-owned pinned toolchain image.** Docker contains Flutter, its bundled Dart SDK, JDK 17, Gradle, Android command-line tools, and the required SDK/build tools. Pub and Gradle caches use persistent Docker volumes. The host does not need Java or Flutter.
- **Keep ADB on the host.** The host already has ADB, USB bridging, and wireless debugging setup. The container uses the host ADB server instead of creating a new ADB identity, which avoids repeated pairing when containers are recreated.
- **Use saved address plus mDNS recovery.** An ignored local file stores the phone's current wireless ADB connect address and the mobile server URL. The helper tries that address first, then uses `adb mdns services` to recover a changed port. Pairing codes and ADB keys never enter the repository.
- **Run an isolated mobile server endpoint.** A Docker Compose mobile profile runs on the same development machine with real models, a dedicated LAN port, a separate database volume, and a separate ignored environment file. It never points mobile work at the normal database.
- **Target the physical phone for live debugging.** The real phone receives manual debug builds and runs `flutter run` over wireless ADB. Automated checks remain device-independent widget tests for now.
- **Add an emulator smoke suite later.** Autoflow-style manual smoke coverage will run on an Android emulator in a later phase, not on the real phone.
- **Support terminal and server-local DevTools debugging.** Terminal hot reload and logs are the required path. Flutter DevTools is optional, binds to loopback on the development machine, and is used only by the PIMOTE agent. It is never exposed to the phone, LAN, or Cloudflare tunnel.

## Direction

The environment will expose thin commands for:

- building or refreshing the pinned Docker image;
- running `flutter pub get`, analyze, and widget tests in the container;
- building a debug APK into a host-visible output directory;
- starting the isolated real-model mobile server;
- connecting and verifying the phone through host ADB and mDNS fallback;
- installing a debug APK on the selected phone;
- starting an interactive `flutter run` session and optional DevTools forwarding.

The mobile server binds a dedicated private-LAN port because the phone cannot use loopback. It has no new authentication layer. Its isolated database and private-LAN scope limit the impact of the existing trust model. Cloudflare tunneling remains outside this environment plan.

## Open questions

### Sharp questions

- Which exact Flutter release, Android SDK platform/build-tools versions, and Gradle cache layout will the pinned image use?
- How will the Linux container reach the host ADB server, and how will scripts prevent the container from starting its own ADB server?
- What Compose service name, LAN port, volume path, and environment-file contract will define the isolated mobile server?
- Which host-visible output and DevTools port-forwarding paths will the Bash commands expose?
- What device identity and mDNS matching rule will select the intended phone when more than one device is visible?

### Fog

- Whether this Wi-Fi permits mDNS reliably or requires the saved-address path most of the time.
- Which Android emulator image and API level will support the later smoke suite.
- Whether a future CI runner needs the same image or a separate headless image.
