# Manual Test Tools

The manual suite currently uses existing interfaces rather than bespoke tools.

## Drivers

- **HTTP API:** invoke `curl` with `bash` against a test-mode server.
- **Go CLI:** invoke `client/brain` with `bash` against the same server.
- **Android Flutter app:** use an Android emulator or device with a Flutter-enabled environment. The first smoke journey is deferred; see [`PLAN.md`](PLAN.md).
- **MCP:** use a direct configured MCP tool call when a local transport is
  available. Record a harness limitation when no transport is exposed.

Add reusable parameterized tools under this directory when a repeated journey
needs more than these drivers.
