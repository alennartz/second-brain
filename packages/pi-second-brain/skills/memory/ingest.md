# Capture organization

## Search and reconcile

Search before writing. Read relevant notes and entities with `memory_get_node`
and inspect their relationships with `memory_explore`.

- If evidence repeats or extends an existing fact, consolidate it into the
  existing note with `memory_update_node`. Retain useful details and source
  attribution. Do not append duplicate text.
- Preserve attribution to both older and newer sources when extending a note.
  Keep distinct claims distinguishable when sources disagree.
- Create a new note only for an independent fact not covered by an existing note.
- Reuse canonical entities. Create an entity only when the evidence identifies
  a person, project, or concept not already represented.
- For long documents, organize independent facts into notes rather than storing
  one undifferentiated document.

## Corrections and precedence

When evidence explicitly corrects a name, search for both names and inspect the
candidate entities. If they identify one real-world entity, update its name and
reconcile its description. Use the same canonical ID for later evidence.

Compare source capture times when deciding precedence between conflicting
claims. When capture time is unavailable, use `freshnessAt` as a recency signal.
Prefer newer supported corrections, not recency alone. Neither timestamp is the
time of an event. Preserve useful older facts and source attribution. Preserve
quoted source wording when reconciling facts.

## Relationships

Use `memory_store_edge` to connect facts and entities when evidence supports a
relationship. Read both endpoints first and use existing canonical IDs. Choose
the edge type and direction that express the evidence. Evidence links do not
require one fixed type or direction.

## Mutations and completion

For `memory_store_node`, note payloads contain only kind, content, source, and
summary. Entity payloads contain only kind, name, type, and description.

Before `memory_update_node`, read the current value and apply one exact edit.
Notes accept content, source, and summary. Entities accept name, type, and
description. If a call reports a field-kind or parameter validation error, correct
the arguments before trying again.

Each successful mutation commits immediately. Verify that the facts are stored
or reconciled and supported relationships exist. Report failures and unresolved
ambiguities without claiming the capture succeeded.
