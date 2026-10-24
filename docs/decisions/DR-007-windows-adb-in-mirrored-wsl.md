# DR-007: Windows ADB as the Canonical Daemon in Mirrored WSL

## Status
Accepted

## Context

The Android development environment runs in mirrored WSL networking. The first device connection used the Linux ADB key, while mirrored networking later caused WSL commands to reach the Windows ADB server instead. Android treats those keys as different hosts, so the phone required pairing again. Separate ADB daemons also made mDNS discovery and device state inconsistent across WSL, Windows, and Docker.

The Windows host had explicit Public-profile firewall block rules for `adb.exe`, which prevented inbound mDNS responses. The development workflow needs one durable ADB identity, changing wireless connect ports discovered without repeated pairing, and a loopback-only ADB server that containers can reuse.

## Decision

Use the Windows ADB installation at `C:\Tools\android-sdk\platform-tools\adb.exe` as the canonical ADB client and daemon when WSL runs in mirrored mode. WSL scripts and Flutter containers act as ADB clients through the Windows daemon on loopback port `5037`. The Windows ADB key under the user profile remains the single pairing identity and never enters the repository or a container.

Mobile tooling prefers the Windows ADB executable when it exists and falls back to the Linux ADB executable on non-Windows hosts. Wireless device selection tries the saved connect address, then Windows ADB mDNS discovery. Pairing addresses and codes remain one-time operator inputs. The Windows firewall permits only the required mDNS UDP traffic from the trusted LAN, while ADB port `5037` remains loopback-only.

## Consequences

- Recreating WSL or Flutter containers does not create a new ADB identity or require another pairing.
- Windows ADB, its persistent user key, and its firewall policy become prerequisites for mirrored-WSL device work.
- A phone can still change its wireless connect port. mDNS or a local address update must recover that change without pairing again.
- A reset of the Windows ADB key, a phone-side revocation of paired hosts, or a factory reset still requires one manual pairing action. Android does not provide a safe silent pairing path.
- Linux-only hosts retain the existing host-owned ADB fallback, but they use their own host key and pairing state.
- The workflow must not expose ADB port `5037` on the LAN or mount the Windows key into containers.
