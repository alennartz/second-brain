# Implementation Plan: Dream Backoff & Convergence Stop

**Date:** 2026-04-13
**Goal:** Stop the dream scheduler from looping forever by adding exponential backoff and a cycle cutoff based on graph size.
**Design doc:** `docs/plans/2026-04-13-dream-backoff-design.md`

## Modules Affected

- **`src/second_brain/config.py`**: Rename `dream_idle_timeout` → `dream_idle_timeout_minutes`, add `dream_delay_multiplier` and `dream_max_delay_minutes`
- **`src/second_brain/scheduler.py`**: Add backoff state, cutoff logic, node counting, and rework `run_forever` loop
- **`src/second_brain/app.py`**: Update config field references when constructing `DreamScheduler`
- **`tests/test_scheduler.py`**: New tests for backoff, cutoff, and reset; update existing fixture
- **`.env`**: Rename `BRAIN_DREAM_IDLE_TIMEOUT` → `BRAIN_DREAM_IDLE_TIMEOUT_MINUTES`
- **`.env.example`**: Add documented dream config section
- **`CLAUDE.md`**: Update config table

## Future Work

- **DB layer refactor**: SQL queries are currently spread across `scheduler.py`, `app.py`, `tools/recall_tools.py`, `tools/ingest_tools.py`, and `tools/dream_tools.py` (~50+ raw `.query()` calls). All SQL should be encapsulated in `db.py` as a proper data access layer. Out of scope for this PR — tracked separately.

---

## Task 1: Rename config field and update references (AUTO)

**Goal:** Rename `dream_idle_timeout` → `dream_idle_timeout_minutes` across config, app, env files, and docs.

**Files:**
- `src/second_brain/config.py` (modify)
- `src/second_brain/app.py` (modify)
- `.env` (modify)
- `.env.example` (modify)
- `CLAUDE.md` (modify)

**Steps:**
1. In `config.py`, rename `dream_idle_timeout` to `dream_idle_timeout_minutes`
2. In `app.py`, update `settings.dream_idle_timeout` → `settings.dream_idle_timeout_minutes`
3. In `.env`, rename `BRAIN_DREAM_IDLE_TIMEOUT` → `BRAIN_DREAM_IDLE_TIMEOUT_MINUTES`
4. In `.env.example`, add dream config section with `BRAIN_DREAM_IDLE_TIMEOUT_MINUTES`
5. In `CLAUDE.md`, update the config table to reflect new name
6. Run `make check` — should pass with no errors
7. Commit: `rename dream_idle_timeout to dream_idle_timeout_minutes`

---

## Task 2: Add new config fields (AUTO)

**Goal:** Add `dream_delay_multiplier` and `dream_max_delay_minutes` to Settings.

**Files:**
- `src/second_brain/config.py` (modify)
- `.env.example` (modify)
- `CLAUDE.md` (modify)

**Steps:**
1. Add `dream_delay_multiplier: float = 1.5` and `dream_max_delay_minutes: float = 720` to `Settings`
2. Add commented entries to `.env.example`
3. Update `CLAUDE.md` config table
4. Run `make check` — should pass
5. Commit: `add dream backoff config: delay_multiplier, max_delay_minutes`

---

## Task 3: Test cutoff computation (REVIEW)

**Goal:** TDD the `_compute_max_cycles` method — pure math, `ceil(sqrt(total / batch))`.

**Files:**
- `tests/test_scheduler.py` (modify)
- `src/second_brain/scheduler.py` (modify)

**Steps:**
1. Write tests for `_compute_max_cycles`: small graph (25 nodes, batch 25 → 1), medium (1000 nodes, batch 25 → 7), large (10000 nodes, batch 25 → 20), edge case (0 nodes → 0 or 1)
2. Run `uv run pytest tests/test_scheduler.py -v` — watch fail
3. Implement `_compute_max_cycles` as a static method on `DreamScheduler`
4. Run tests — watch pass
5. Commit: `add dream cycle cutoff computation`

---

## Task 4: Test node counting (REVIEW)

**Goal:** TDD `_count_nodes` method that queries total entity + note count.

**Files:**
- `tests/test_scheduler.py` (modify)
- `src/second_brain/scheduler.py` (modify)

**Steps:**
1. Write test: create some entities and notes in DB, call `_count_nodes`, assert correct total
2. Run test — watch fail
3. Implement `_count_nodes` on scheduler (queries `SELECT count() FROM entity` + `SELECT count() FROM note`)
4. Run test — watch pass
5. Commit: `add node count query for dream cutoff`

---

## Task 5: Test backoff state and reset (REVIEW)

**Goal:** TDD the backoff progression, cap, and reset behavior.

**Files:**
- `tests/test_scheduler.py` (modify)
- `src/second_brain/scheduler.py` (modify)

**Steps:**
1. Write tests:
   - After construction: `_current_delay == idle_timeout`, `_cycle_count == 0`, `_max_cycles is None`
   - `_advance_backoff()` multiplies delay by multiplier, caps at max_delay
   - `touch_activity()` resets `_cycle_count`, `_current_delay`, and `_max_cycles`
2. Run tests — watch fail
3. Add `_current_delay`, `_cycle_count`, `_max_cycles` fields to `__init__`; add `_advance_backoff()` method; update `touch_activity()` to reset state
4. Run tests — watch pass
5. Commit: `add dream backoff state, progression, and reset`

---

## Task 6: Wire new config into app.py (AUTO)

**Goal:** Pass `dream_delay_multiplier` and `dream_max_delay_minutes` to the scheduler constructor.

**Files:**
- `src/second_brain/app.py` (modify)
- `src/second_brain/scheduler.py` (modify — update `__init__` signature)

**Steps:**
1. Add `delay_multiplier` and `max_delay` params to `DreamScheduler.__init__`, store them, use them to initialize backoff state
2. Update `app.py` to pass `delay_multiplier=settings.dream_delay_multiplier` and `max_delay=settings.dream_max_delay_minutes * 60`
3. Update existing test fixture to pass new params (or verify defaults work)
4. Run `make check` — should pass
5. Commit: `wire dream backoff config through app to scheduler`

---

## Task 7: Rework `run_forever` loop (REVIEW)

**Goal:** Replace the tight idle-poll loop with backoff delays and cycle cutoff.

**Files:**
- `tests/test_scheduler.py` (modify)
- `src/second_brain/scheduler.py` (modify)

**Steps:**
1. Write tests:
   - `run_forever` stops running cycles when `_cycle_count >= _max_cycles` (mock `run_cycle`, count invocations)
   - `run_forever` waits `_current_delay` between cycles (mock `asyncio.sleep`, verify values)
   - After cutoff reached, new `touch_activity` allows dreaming again
2. Run tests — watch fail
3. Rework `run_forever`:
   - Wait `_current_delay` instead of polling every 1s
   - On first cycle: call `_count_nodes` and `_compute_max_cycles` to set `_max_cycles`
   - After each cycle: increment `_cycle_count`, call `_advance_backoff()`
   - If `_cycle_count >= _max_cycles`: log and wait for activity (await `_cancel` event)
4. Run tests — watch pass
5. Run `make check` — full suite green
6. Commit: `rework dream run_forever with backoff and cycle cutoff`

---

## Task 8: Clean up exploration script (AUTO)

**Goal:** Remove `dream_cutoff_explore.py` from repo root.

**Steps:**
1. Delete `dream_cutoff_explore.py`
2. Commit: `remove dream cutoff exploration script`
