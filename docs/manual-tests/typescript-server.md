# Manual Testing — TypeScript Bun Server

**Status:** automated contract gate passed. Live provider, Docker, and device journeys were not run in this environment because credentials, a Docker daemon, and a connected device are unavailable.

## Automated gate

- `bun run typecheck` — pass.
- `bun test` — pass.
- Fresh SurrealKV startup, schema/index creation, and reopen — pass.
- Pi direct and Codemode smoke with closed built-ins — pass.
- HTTP validation, queue controls, recall evidence, graph lookup, and dream jobs — pass.

## Release-only live journeys

The following checks require a local provider credential, Docker daemon, or connected device. Run them before a production release:

- Start `bun run src/main.ts` and request `/health`.
- Stage intake, inspect pipeline state, recall queued evidence, and poll a dream job.
- Restart the process and verify fresh database persistence.
- Build the Bun image and run the `server` Compose service with `make docker-up`.
- Run the bounded Go E2E journey with `make e2e`.
- Run Go CLI ingest, recall, and graph commands.
- Run the Android client journey on a connected device.

No provider credentials or local Docker service were used for the automated gate.
