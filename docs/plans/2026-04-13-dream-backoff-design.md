# Dream Scheduler Backoff & Convergence Stop

## Problem

Once the server goes idle, the dream scheduler runs cycles back-to-back forever. There is no mechanism to slow down or stop dreaming when the graph has been sufficiently processed.

## Design

Two complementary mechanisms:

### 1. Exponential Backoff

After each dream cycle, the delay before the next cycle increases by a multiplier.

- **Initial delay**: `dream_idle_timeout_minutes` (existing setting, renamed)
- **Multiplier**: `dream_delay_multiplier` (default: 1.5)
- **Cap**: `dream_max_delay_minutes` (default: 720, i.e. 12 hours)
- **Reset**: any user activity (`touch_activity`) resets delay back to `idle_timeout`

Progression with defaults (idle_timeout=10m): 10m, 15m, 22.5m, 33.75m, ... capped at 12h.

### 2. Cycle Cutoff (Convergence Stop)

Stop dreaming after a computed number of cycles based on graph size.

- **Formula**: `ceil(sqrt(total_nodes / batch_size))`
- **Total nodes** counted once when idle period begins (first cycle)
- **Cycle counter** resets to 0 on user activity

Sub-linear growth means large graphs don't burn excessive cycles:
- 100 nodes / 25 batch = 2 cycles
- 1000 nodes / 25 batch = 7 cycles
- 10000 nodes / 25 batch = 20 cycles

### Config Renames

All time-related dream settings include their unit in the name:

| Old | New |
|-----|-----|
| `dream_idle_timeout` | `dream_idle_timeout_minutes` |
| (new) | `dream_max_delay_minutes` |
| (new) | `dream_delay_multiplier` |

Env vars follow the `BRAIN_` prefix convention: `BRAIN_DREAM_IDLE_TIMEOUT_MINUTES`, etc.

## Component Changes

Entirely within `DreamScheduler` and `Settings`. No agent or tool changes.

### Scheduler gains

- `_cycle_count: int` — incremented after each cycle (including failures), reset by `touch_activity`
- `_max_cycles: int | None` — computed once from node count when idle begins
- `_current_delay: float` — starts at `idle_timeout`, grows by multiplier, capped at `max_delay`

### `run_forever` flow

```
touch_activity() -> resets cycle_count=0, current_delay=idle_timeout, max_cycles=None

run_forever loop:
  wait current_delay
  if max_cycles is None -> query total node count, compute ceil(sqrt(total/batch))
  if cycle_count >= max_cycles -> sleep, don't run, wait for activity
  run_cycle()
  cycle_count += 1
  current_delay = min(current_delay * multiplier, max_delay)
```

### Error handling

No change to cycle error handling. Failed cycles still increment the counter (a failed cycle used a turn).

## Testing Approach

- Cutoff computation: pure math, unit test directly
- Backoff progression and cap: unit test delay sequence
- `touch_activity` resets counter and delay: unit test state
- `run_forever` stops cycling at max_cycles: integration test with mock cycle
