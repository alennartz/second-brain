# Dream Iteration Log

Tracking changes to dream agent prompts and their effects on graph quality.

## Baseline State

**Database:** 8 snippets ingested (5 space, 3 renaissance — some failed on content filter/timeout)
**Known duplicates pre-dream:**
- 2× Filippo Brunelleschi (exact name)
- 2× Sergei Korolev (exact name)
- 2× Linear perspective (exact name)
- 2× Venice (exact name)
- 2× Rome (exact name)
- 2× Florence Cathedral (variant names)

**After 5 dream cycles (original prompts):**
- Rome: ✓ MERGED
- Brunelleschi: ⚠ still 2× exact dupe
- Korolev: ⚠ still 2× exact dupe  
- Linear perspective: ⚠ still 2× exact dupe
- Venice: ⚠ still 2× exact dupe

**Problems identified:**
1. Batch selection (10 items) doesn't prioritize dedup candidates
2. Dedup agent checks each batch item individually with find_similar, but many duplicates never land in the same batch
3. When duplicates ARE found by find_similar, the model sometimes doesn't merge them
4. 83 entities with batch_size=10 means 8+ cycles to touch everything once
5. Connect agent creates edges with overly specific table names (connected_funding_for, authored_by)

---

## Iteration 1: Dedup prompt — bump k, add urgency (MARGINAL)

**Changes to `dream_dedup.py` prompt:**
- Added "call find_similar with k=10" (was 5)
- Added "Do NOT skip any batch member"
- Added threshold guidance: "Similarity > 0.95 with similar names is almost always a duplicate"
- Changed default k from 5 to 10 in find_similar tool signature

**Results (5 cycles):**
- Korolev: ✓ merged (was still dupe after 5 cycles with old prompt)
- Brunelleschi: ⚠ still 2× exact dupe
- Linear perspective: ⚠ still 2× exact dupe
- Venice: ⚠ still 2× exact dupe
- Rome: ⚠ still 2× exact dupe
- Total merges: 3 across 5 cycles

**Diagnosis:** Marginal improvement. The threshold guidance (>0.95) was WRONG — actual
similarity between exact-name duplicates is ~0.56 because embeddings encode descriptions,
not just names. The model saw a 0.56 similarity score and didn't merge.

---

## Iteration 2: Dedup prompt — name-first, ignore similarity scores (MAJOR)

**Key insight from testing:** `find_similar('Sergei Korolev')` returns the duplicate
at position #2 with similarity 0.56 — but Hermann Oberth ranks HIGHER at 0.61.
The model was correctly following the threshold guidance (>0.95) and skipping merges.

**Changes to `dream_dedup.py` prompt:**
- CRITICAL new rule: "Identical names = same entity, period. Do not look at the
  similarity score — it reflects description/embedding differences, NOT name matching."
- Removed misleading threshold guidance (>0.95)
- Added real-world examples: "Two entities both named 'Venice' are duplicates."
- Added variant matching: "'Florence Cathedral' and 'Cathedral of Santa Maria del Fiore'
  are the same place"
- Added anti-example: "'Brunelleschi' vs 'Brunelleschi's dome' — do NOT merge"

**Results (8 cycles from fresh baseline):**
- Brunelleschi person: ✓ merged (cycle 2, along with 8 other merges!)
- Linear perspective: ✓ merged
- Rome: ✓ merged  
- Venice: ✓ merged (cycle 6)
- Korolev: ⚠ still 2× (batch scheduling — hasn't been selected yet)
- Total merges: 11 across 8 cycles vs 4 across 5 with iteration 1

**Cycle 2 was the breakthrough: 9 merges in one cycle.** The model started
aggresively scanning find_similar results for name matches and merging immediately.

**Remaining issue:** Batch scheduling. With 80+ entities and batch_size=10, some
duplicates wait 8+ cycles to be processed. Korolev's two entries haven't been
in the same batch or had find_similar find each other yet.

---

## Iteration 3: Entity-only dedup batches (MAJOR)

**Key insight:** Cycle 1 with the old scheduler picked 9 notes and 1 entity because
notes had lower dream_age. Most duplicates are entities, so the dedup agent was
spending cycles comparing notes (which are all unique) instead of finding entity dupes.

**Changes to `scheduler.py`:**
- `_select_batch()` now accepts optional `table_filter` parameter
- `run_cycle()` uses entity-only batch for dedup phase, mixed batch for connect phase
- This ensures every dedup cycle processes entity duplicates, not notes

**Results (7 cycles from fresh baseline):**

| Cycle | Merges | Cumulative |
|-------|--------|------------|
| 1     | 4      | 4          |
| 2     | 3      | 7          |
| 3     | 1      | 8          |
| 4     | 1      | 9          |
| 5     | 1      | 10         |
| 6     | 3      | 13         |
| 7     | 0      | 13         |

**All 5 known exact-name duplicates resolved:**
- Brunelleschi: ✓ merged (cycle 6)
- Korolev: ✓ merged (by cycle 3)
- Linear perspective: ✓ merged (by cycle 3)
- Venice: ✓ merged (by cycle 5)
- Rome: ✓ merged (by cycle 3)
- Plus 8 other merges (variant names, concepts)

**Comparison:**
| Metric | Original | Iteration 2 | Iteration 3 |
|--------|----------|-------------|-------------|
| Cycles to clear all 5 dupes | never (5+ cycles, 1 fixed) | 8 cycles (4/5 fixed) | 7 cycles (5/5 fixed) |
| Total merges in 5 cycles | 4 | 11 | 10 |
| Merges in first 3 cycles | 2 | 2 | 8 |

---

## Iteration 4: Hybrid find_similar, strip scores, judgment-based prompt (KEPT)

**Philosophy change:** The dedup agent shouldn't be thresholding numbers. It should
read names, look at connections, and decide like a human would.

**Changes:**
- **`dream_tools.py` find_similar**: Now does hybrid search (vector + BM25 on
  name/content) with RRF fusion. Exact-name duplicates reliably surface via BM25
  even when embeddings diverge. Similarity scores stripped from results entirely.
- **`dream_dedup.py` prompt**: Rewritten around judgment. "Read the candidates.
  Look at their names, types, and descriptions." No mention of scores.
- **`dream_dedup.py` tools**: Added `explore` tool so the agent can see what
  each candidate is connected to. Two entities with the same name connected
  to the same people/places are obviously duplicates.
- **Test updated**: `test_find_similar_strips_scores` replaces
  `test_find_similar_includes_similarity_score`.

**Results (5 cycles from fresh baseline):**
- All 5 known exact-name duplicates resolved: Brunelleschi ✓, Korolev ✓,
  Linear perspective ✓, Venice ✓, Rome ✓
- 9 merges in 5 cycles
- 54 explore calls — the agent is actively checking connections
- BM25 hits appearing (ft=1) when name tokens match

**Comparison across all iterations (5 cycles each, fresh baseline):**

| Metric | Original | Iter 2 (name-first) | Iter 4 (hybrid+judgment) |
|--------|----------|---------------------|-------------------------|
| Dupes resolved (of 5) | 1 | 4 | **5** |
| Total merges | 4 | 10 | **9** |
| Explore calls | 0 | 0 | **54** |
| BM25 in find_similar | no | no | **yes** |
| Scores shown to agent | yes | yes | **no** |

---

## Summary of changes kept

1. **dream_dedup.py prompt**: Judgment-based — read names, check connections via
   explore, decide like a human. No similarity scores, no thresholds.
2. **dream_dedup.py tools**: Added `explore` for relationship context.
   `find_similar` default k=10.
3. **dream_tools.py find_similar**: Hybrid vector+BM25 search, scores stripped.
4. **scheduler.py**: Entity-only batch for dedup phase, mixed batch for connect.
