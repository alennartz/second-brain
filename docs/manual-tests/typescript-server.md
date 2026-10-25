# Manual Testing — TypeScript Bun Server

**Status:** automated contract gate passed; live provider and Docker journeys pending.

## Automated gate

- `npx tsc --noEmit` — pass.
- `npx bun test` — 178 tests passed.
- Fresh SurrealKV startup, schema/index creation, and reopen — pass.
- Pi direct and Codemode smoke with closed built-ins — pass.
- HTTP validation, queue controls, recall evidence, graph lookup, and dream jobs — pass.

## Pending live journeys

The following checks need a local provider credential and Docker daemon:

- Start `bun run src/main.ts` and request `/health`.
- Stage intake, inspect pipeline state, recall queued evidence, and poll a dream job.
- Restart the process and verify fresh database persistence.
- Build the Bun image and run the `server` Compose service.
- Run Go CLI ingest, recall, and graph commands.
- Run the Android client journey on a connected device.

No provider credentials or local Docker service were used for the automated gate.
