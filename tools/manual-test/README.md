# Manual Test Tools

The manual suite exercises the Bun server through its public HTTP routes and
shipped clients. It does not use MCP or conversation routes.

## Drivers

- **HTTP API:** use `curl` from a shell against a Bun server.
- **Go CLI:** invoke `client/brain` against the same server.
- **Android Flutter app:** use `tools/mobile/README.md` for container checks and
  real-phone debugging. The emulator smoke journey remains deferred.

## Start a local server

```bash
cp .env.example .env
# Set workflow model references and provider credentials.
bun run src/main.ts
```

Use `make dev` for hot reload. The server listens on port 8000 and creates a
fresh SurrealKV database at `BRAIN_DB_PATH`.

Add reusable parameterized tools under this directory when a repeated journey
needs more than these drivers.
