# Containerized Flutter development

This workflow builds and debugs the Android client without Flutter, Dart, Java,
or Android SDK tools on the host. The host needs Linux, Docker, and ADB. In
mirrored WSL, the scripts prefer the Windows ADB executable at
`/mnt/c/Tools/android-sdk/platform-tools/adb.exe` so every command reuses the
Windows ADB server and its persistent pairing key. They fall back to
`/home/alenna/android/platform-tools/adb` on hosts without that Windows path.

## Toolchain and paths

`Dockerfile` starts from `ghcr.io/cirruslabs/flutter:3.22.3` pinned to the
committed OCI digest in `versions.env`. The image verifies Flutter 3.22.3 and
Android command-line tools `10406996`, then verifies platform-tools 35.0.1 and
installs Android platform 34, build-tools 34.0.0 and the Android Gradle Plugin
8.1.0 build-tools 33.0.1, NDK 23.1.7779620, and the exact Ubuntu JDK
package version recorded in `versions.env`. It matches the app's Android
Gradle plugin 8.1.0, Kotlin 1.8.22, and Gradle wrapper 8.2.

The repository mounts at `/workspace`. The app remains at
`/workspace/client/mobile`. Named Docker volumes preserve Pub and Gradle caches:

- `second-brain-mobile-pub-cache` at `/cache/pub`;
- `second-brain-mobile-gradle-cache` at `/cache/gradle`;
- `second-brain-mobile-home` at `/tmp/mobile-home`, which preserves the Android
  debug signing key across builds.

Generated APKs stay in the host-visible
`client/mobile/build/app/outputs/flutter-apk/` directory. Containers run with
the caller's numeric UID and GID, so generated files remain editable. The
container never mounts host ADB keys. The persistent mobile home volume keeps
successive debug APKs signed by the same container-owned key, so `adb install
-r` can update the app without uninstalling it.

## Local configuration

Copy the example and edit the ignored local file:

```bash
cp .env.mobile.example .env.mobile.local
chmod 600 .env.mobile.local
```

Set these values:

```text
MOBILE_DEVICE=192.168.1.42:37123
MOBILE_SERVER_BIND_ADDRESS=192.168.1.10
MOBILE_SERVER_URL=http://192.168.1.10:8200
MOBILE_DEVTOOLS_PORT=9100
```

`MOBILE_DEVICE` is the phone's wireless ADB **connect** address. It is not the
host ADB server port and not the brain server URL. Android wireless debugging
can change this connect port after a restart. `MOBILE_SERVER_BIND_ADDRESS` is
the trusted LAN address where `server-mobile` listens. `MOBILE_SERVER_URL` uses
the same development-machine address and the isolated port `8200`. Provider
model settings and credentials also belong in `.env.mobile.local`; scripts never
print them or pass them to the Flutter container.

Pairing addresses and pairing codes are one-time inputs. Enter them directly
with `adb pair`; do not save them in `.env.mobile.local` or the repository.

## Ordered workflow

Build the pinned image once, then run checks and build the debug APK:

```bash
make mobile-image
make mobile-check
make mobile-build
```

`mobile-check` runs `flutter pub get`, `flutter analyze`, and `flutter test`.
It needs no phone or server configuration. `mobile-build` prints
`MOBILE_SERVER_URL` before it builds. Enter that URL in the app on first launch.
It produces only the debug APK. Release signing and profile builds are not part
of this workflow.

Start the isolated server profile when the phone needs the API:

```bash
make mobile-server-up
# use the printed MOBILE_SERVER_URL in the app
make mobile-server-down
```

The service is named `server-mobile`, binds only to
`MOBILE_SERVER_BIND_ADDRESS:8200`, uses real models, and stores data in the
separate `mobile-brain-data` volume at `/data/brain.db`.
The server has no authentication layer. Use it only on a trusted private LAN.
Real model calls can incur provider costs. `mobile-server-down` stops only this
service and preserves its data. It does not stop the normal `server` service or
delete any volume.

Connect and install on one wireless-debugged phone:

```bash
make mobile-connect
make mobile-install
```

`mobile-connect` starts or verifies the host ADB daemon on
`127.0.0.1:5037`, then tries `MOBILE_DEVICE`. It verifies the device state,
model, Android version, and serial through the host daemon. In mirrored WSL,
the host daemon is Windows ADB, so the Windows key in
`C:\\Users\\<user>\\.android\\adbkey` remains the one pairing identity. If the
saved address fails, it uses only mDNS wireless **connect** services. One
candidate is used. More than one candidate is an error, and the addresses are
listed without an arbitrary selection. If the phone is unauthorized, the
command shows the one-time `adb pair` instructions. Pairing keys stay on the
host and survive Flutter container recreation.

`mobile-install` selects the phone, builds the debug APK, and runs
`adb -s <serial> install -r`. It prints `MOBILE_SERVER_URL` before build and
installation. It does not rewrite `.env.mobile.local` when mDNS discovers a
changed connect port. Update `MOBILE_DEVICE` manually when you want to save the
new address.

Start an interactive debug session for hot reload, hot restart, logs, and the
Flutter VM service:

```bash
make mobile-debug
```

The command uses host ADB through Linux host networking and keeps terminal input,
interrupts, and Flutter's exit status. Flutter prints the VM service URL during
the session.

Run DevTools in a second terminal when the debug session is active:

```bash
make mobile-devtools
```

DevTools binds to `127.0.0.1:$MOBILE_DEVTOOLS_PORT` only. The command prints the
loopback URL. Paste the VM service URL printed by `mobile-debug` into DevTools.
It is not published through Compose, the LAN, or the Cloudflare tunnel.

PIMOTE preserves the terminal session when an agent client disconnects. These
commands do not add a background job database, reconnect service, or tmux
requirement.

## Diagnostics and boundaries

- Run `docker image inspect second-brain-mobile-toolchain` to inspect the image.
- Run `docker volume ls` to inspect the two cache volumes and
  `mobile-brain-data`.
- Run `adb devices -l` to inspect host ADB. In mirrored WSL this uses the
  Windows ADB server; check it with
  `/mnt/c/Tools/android-sdk/platform-tools/adb.exe devices -l`.
- Run `adb mdns services` to inspect connect and pairing services.
- Keep the ADB daemon on loopback. Never expose port 5037 on the LAN.
- A missing or malformed local value fails before Docker builds or device
  changes. `MOBILE_SERVER_URL` must use the isolated port `8200`, and the
  Compose profile uses the same environment file as the scripts.
- Direct Compose commands must pass `--env-file .env.mobile.local`. Compose
  requires `MOBILE_SERVER_BIND_ADDRESS` and refuses an empty wildcard binding.
- Device commands fail before selecting an arbitrary phone.

Container checks are automated and device-independent. Phone installation and
live debugging are manual. No connected phone or Android emulator is available
here, so real-phone installation, live debugging, and VM-service connection remain
unrun. The Android emulator smoke journey is deferred to a later environment and
does not target this debugging phone.
