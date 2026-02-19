# Pre-commit Hooks Design

## Context

The project has ruff (lint + format) and basedpyright (type checking) configured but no automation to enforce them before code lands. The primary workflow is Claude Code-driven, often with parallel sessions in the same working directory (one coding, one brainstorming).

## Constraints

- Must not interfere with parallel Claude Code sessions. This rules out Claude Code event hooks (stop, PostToolUse) since a brainstorming session would get lint errors from the coding session's in-progress changes.
- Tests excluded from the hook to keep commits fast.

## Decision

Use the `pre-commit` framework with a `.pre-commit-config.yaml` checked into the repo. Git pre-commit hooks only fire on `git commit`, avoiding multi-session interference. Output is visible to both Claude and the developer.

## Hooks (in order)

1. **ruff format** -- Auto-formats staged Python files. Runs first so formatting is applied before lint.
2. **ruff check --fix** -- Lints and auto-fixes safe issues. Fails on unfixable errors.
3. **basedpyright** -- Type checks `src/`. Runs as a `local` hook (`uv run basedpyright src/`) since it needs full project context.

Ruff hooks use the official `ruff-pre-commit` repo maintained by the ruff team. Basedpyright uses a local system hook against the project venv.

## Setup

- `pre-commit` added as a dev dependency
- Developer runs `uv run pre-commit install` once after clone
- Documented in CLAUDE.md

## Failure behavior

- If ruff modifies files, the commit is rejected. Re-stage and commit again.
- If basedpyright finds errors, the commit is rejected with diagnostic output.
- `--no-verify` available as escape hatch for WIP commits.
