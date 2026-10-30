# Evidence research

1. Search with `memory_search` using the question and relevant hints.
2. Read promising records with `memory_get_node`. Follow supported
   relationships with `memory_explore`.
3. Refine the search when evidence is incomplete or ambiguous.
4. Answer from the inspected evidence. Distinguish established facts, conflicting
   claims, and gaps.

## Evidence and precedence

Search returns graph nodes and unprocessed intake evidence separately. Treat
unprocessed intake as source evidence, not organized knowledge. It can support
an answer before ingestion finishes, but do not invent graph relationships for it.

When evidence conflicts, compare source capture times when available. Otherwise,
use graph `freshnessAt` as a recency signal. Prefer newer supporting evidence,
not recency alone. Neither timestamp describes when an event occurred. Preserve
useful older facts and identify unresolved conflicts.

## Answers and citations

Cite only records returned by successful read tools during this research. Never
invent citations. Match citations to the claims they support, not merely to the
search topic. If nothing supports the answer, say that no evidence was found.
Report failed reads rather than treating them as proof that knowledge is absent.
