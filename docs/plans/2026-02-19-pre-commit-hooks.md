# Pre-commit Hooks Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add pre-commit hooks that run ruff format, ruff check, and basedpyright before every commit.

**Architecture:** Use the `pre-commit` framework with official ruff hooks and a local basedpyright hook. Config lives in `.pre-commit-config.yaml` (committed). Git hook installed locally via `pre-commit install`.

**Tech Stack:** pre-commit, ruff (via ruff-pre-commit), basedpyright (local hook)

---

### Task 1: Add pre-commit dependency and create config

**Files:**
- Modify: `pyproject.toml` (dependency-groups.dev)
- Create: `.pre-commit-config.yaml`

**Step 1: Add pre-commit as a dev dependency**

Run: `uv add --dev pre-commit`

Expected: `pre-commit` added to `[dependency-groups] dev` in `pyproject.toml`.

**Step 2: Create `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.15.1
    hooks:
      - id: ruff-format
      - id: ruff
        args: [--fix, --exit-non-zero-on-fix]

  - repo: local
    hooks:
      - id: basedpyright
        name: basedpyright
        entry: uv run basedpyright src/
        language: system
        types: [python]
        pass_filenames: false
```

Notes:
- `ruff-format` runs before `ruff` (order in the file = execution order).
- `--exit-non-zero-on-fix` ensures the commit is rejected if ruff auto-fixed anything (so the fixed files get re-staged).
- basedpyright uses `pass_filenames: false` because it needs whole-project context, not individual files.

**Step 3: Install the git hook**

Run: `uv run pre-commit install`

Expected: Output like `pre-commit installed at .git/hooks/pre-commit`.

**Step 4: Verify the hook works**

Run: `uv run pre-commit run --all-files`

Expected: All three hooks pass (ruff-format, ruff, basedpyright).

**Step 5: Commit**

Stage `pyproject.toml`, `uv.lock`, `.pre-commit-config.yaml` and commit.

---

### Task 2: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add setup instructions and hook info**

In the Commands section, after the existing commands, add:

```bash
# Setup (run once after clone)
uv run pre-commit install

# Run all hooks manually
uv run pre-commit run --all-files
```

**Step 2: Commit**

Stage `CLAUDE.md` and commit.
