"""Contracts for global, layer-balanced RRF over Storage candidate lists.

RRF uses offset 60. Each note/entity path has weight 0.5. Each intake_chunk
path has weight 1. Candidate caps apply before fusion. Both result collections
share one final k limit. Tests assert strict winners, not ranking ties.
"""

from unittest.mock import create_autospec

import pytest

from second_brain.db import Storage
from second_brain.models import (
    MemorySearchCandidates,
    MemorySearchResult,
    RankedSearchCandidates,
)
from second_brain.tools.recall_tools import search_memory


def _record(table: str, key: str) -> dict:
    record: dict = {"id": f"{table}:{key}", "table": table}
    if table == "entity":
        record["name"] = key
    else:
        record["content"] = key
    if table == "intake_chunk":
        record.update({"intake_id": "intake-1", "chunk_index": 0, "state": "ready"})
    return record


def _storage(candidates: MemorySearchCandidates, k: int = 5):
    storage = create_autospec(Storage, instance=True, spec_set=True)
    expected_k = k

    async def candidate_search(query: str, k: int) -> MemorySearchCandidates:
        assert query == "memory"
        assert k == expected_k
        return candidates

    storage.search_memory_candidates.side_effect = candidate_search
    storage.get_connections.return_value = []
    return storage


def _assert_candidate_seam(storage) -> None:
    storage.search_memory_candidates.assert_awaited_once()
    storage.hybrid_search.assert_not_awaited()
    storage.search_intake_chunks.assert_not_awaited()
    storage.vector_search.assert_not_awaited()
    storage.fulltext_search.assert_not_awaited()


def _ids(result: MemorySearchResult) -> set[str]:
    return {record["id"] for record in result.nodes + result.unprocessed}


def _mixed_candidates() -> MemorySearchCandidates:
    note = _record("note", "organized")
    entity = _record("entity", "concept")
    chunk = _record("intake_chunk", "queued")
    return MemorySearchCandidates(
        note=RankedSearchCandidates(bm25=[note], vector=[note]),
        entity=RankedSearchCandidates(bm25=[entity], vector=[entity]),
        intake_chunk=RankedSearchCandidates(bm25=[chunk], vector=[chunk]),
    )


async def test_search_memory_returns_graph_and_unprocessed_evidence_separately():
    storage = _storage(_mixed_candidates())

    result = await search_memory(storage, "memory", k=5)

    assert isinstance(result, MemorySearchResult)
    assert {node["id"] for node in result.nodes} == {
        "note:organized",
        "entity:concept",
    }
    assert [chunk["id"] for chunk in result.unprocessed] == ["intake_chunk:queued"]
    assert all(node["table"] in {"note", "entity"} for node in result.nodes)
    assert all(chunk["table"] == "intake_chunk" for chunk in result.unprocessed)
    assert all(chunk.get("unprocessed") is True for chunk in result.unprocessed)
    assert len(result.nodes + result.unprocessed) == 3
    assert not any("connections" in chunk for chunk in result.unprocessed)
    _assert_candidate_seam(storage)


@pytest.mark.parametrize("k", [1, 2, 3, 4, 7])
async def test_search_memory_applies_one_total_k_limit_across_both_layers(k: int):
    candidates = MemorySearchCandidates(
        **{
            table: RankedSearchCandidates(
                bm25=[_record(table, f"candidate-{index}") for index in range(8)],
                vector=[_record(table, f"candidate-{index}") for index in range(8)],
            )
            for table in ("note", "entity", "intake_chunk")
        }
    )
    storage = _storage(candidates, k=k)

    result = await search_memory(storage, "memory", k=k)

    assert len(result.nodes) + len(result.unprocessed) == k
    assert len(_ids(result)) == k
    _assert_candidate_seam(storage)


async def test_global_rrf_balances_the_two_organized_tables_against_intake():
    """A rank-3 chunk consensus beats rank-1 organized consensus.

    Weighted scores are 2/63 for the chunk and 1/61 for each top graph node.
    Unweighted table fusion drops the chunk behind four organized candidates.
    """
    note_records = [_record("note", f"organized-{index}") for index in range(3)]
    entity_records = [_record("entity", f"organized-{index}") for index in range(3)]
    consensus = _record("intake_chunk", "consensus")
    candidates = MemorySearchCandidates(
        note=RankedSearchCandidates(bm25=note_records, vector=note_records),
        entity=RankedSearchCandidates(bm25=entity_records, vector=entity_records),
        intake_chunk=RankedSearchCandidates(
            bm25=[
                _record("intake_chunk", "keyword-first"),
                _record("intake_chunk", "keyword-second"),
                consensus,
            ],
            vector=[
                _record("intake_chunk", "vector-first"),
                _record("intake_chunk", "vector-second"),
                consensus,
            ],
        ),
    )
    storage = _storage(candidates, k=3)

    result = await search_memory(storage, "memory", k=3)

    assert "intake_chunk:consensus" in _ids(result)
    assert result.unprocessed[0]["id"] == "intake_chunk:consensus"
    assert len(result.nodes) + len(result.unprocessed) == 3
    _assert_candidate_seam(storage)


@pytest.mark.parametrize("table", ["note", "entity"])
async def test_organized_consensus_competes_equally_with_intake_single_paths(
    table: str,
):
    """Top graph consensus ties two rank-1 chunks and beats lower-rank chunks.

    All three top scores are 1/61. The cutoff excludes every 1/62 contender.
    Intake-first concatenation or underweighted organized paths drops the graph.
    """
    consensus = _record(table, "consensus")
    candidates = MemorySearchCandidates(
        **{table: RankedSearchCandidates(bm25=[consensus], vector=[consensus])},
        intake_chunk=RankedSearchCandidates(
            bm25=[_record("intake_chunk", f"keyword-{index}") for index in range(3)],
            vector=[_record("intake_chunk", f"vector-{index}") for index in range(3)],
        ),
    )
    storage = _storage(candidates, k=3)

    result = await search_memory(storage, "memory", k=3)

    assert _ids(result) == {
        f"{table}:consensus",
        "intake_chunk:keyword-0",
        "intake_chunk:vector-0",
    }
    _assert_candidate_seam(storage)


async def test_global_rrf_rank_two_consensus_outranks_single_path_rank_one():
    keyword_first = _record("note", "keyword-first")
    vector_first = _record("note", "vector-first")
    consensus = _record("note", "consensus")
    candidates = MemorySearchCandidates(
        note=RankedSearchCandidates(
            bm25=[keyword_first, consensus],
            vector=[vector_first, consensus],
        ),
        entity=RankedSearchCandidates(bm25=[_record("entity", "keyword-first")]),
    )
    storage = _storage(candidates, k=3)

    result = await search_memory(storage, "memory", k=3)

    assert result.nodes[0]["id"] == "note:consensus"
    assert len(result.nodes) == 3
    assert len(_ids(result)) == 3
    assert result.unprocessed == []
    _assert_candidate_seam(storage)


async def test_global_rrf_ranks_entities_against_notes_instead_of_concatenating():
    note = _record("note", "keyword-only")
    entity = _record("entity", "consensus")
    storage = _storage(
        MemorySearchCandidates(
            note=RankedSearchCandidates(bm25=[note]),
            entity=RankedSearchCandidates(bm25=[entity], vector=[entity]),
        ),
        k=2,
    )

    result = await search_memory(storage, "memory", k=2)

    assert [node["id"] for node in result.nodes] == [
        "entity:consensus",
        "note:keyword-only",
    ]
    assert result.unprocessed == []
    _assert_candidate_seam(storage)


@pytest.mark.parametrize("table", ["note", "entity", "intake_chunk"])
async def test_candidate_caps_exclude_adversarial_consensus_tails_before_rrf(
    table: str,
):
    bm25 = [_record(table, f"keyword-{index}") for index in range(2)]
    vector = [_record(table, f"vector-{index}") for index in range(2)]
    tail = _record(table, "out-of-cap-consensus")
    baseline = MemorySearchCandidates(
        **{table: RankedSearchCandidates(bm25=bm25, vector=vector)}
    )
    adversarial = MemorySearchCandidates(
        **{table: RankedSearchCandidates(bm25=[*bm25, tail], vector=[*vector, tail])}
    )
    baseline_storage = _storage(baseline, k=2)
    adversarial_storage = _storage(adversarial, k=2)

    baseline_result = await search_memory(baseline_storage, "memory", k=2)
    adversarial_result = await search_memory(adversarial_storage, "memory", k=2)

    assert _ids(baseline_result) == {f"{table}:keyword-0", f"{table}:vector-0"}
    assert _ids(adversarial_result) == _ids(baseline_result)
    assert tail["id"] not in _ids(adversarial_result)
    _assert_candidate_seam(baseline_storage)
    _assert_candidate_seam(adversarial_storage)


async def test_balanced_fusion_does_not_reserve_a_slot_for_the_weaker_layer():
    chunks = [_record("intake_chunk", f"consensus-{index}") for index in range(2)]
    storage = _storage(
        MemorySearchCandidates(
            note=RankedSearchCandidates(bm25=[_record("note", "keyword-only")]),
            entity=RankedSearchCandidates(vector=[_record("entity", "vector-only")]),
            intake_chunk=RankedSearchCandidates(bm25=chunks, vector=chunks),
        ),
        k=2,
    )

    result = await search_memory(storage, "memory", k=2)

    assert result.nodes == []
    assert [chunk["id"] for chunk in result.unprocessed] == [
        "intake_chunk:consensus-0",
        "intake_chunk:consensus-1",
    ]
    storage.get_connections.assert_not_awaited()
    _assert_candidate_seam(storage)


async def test_search_memory_enriches_only_selected_graph_nodes_once():
    storage = _storage(_mixed_candidates())
    connections = {
        "note:organized": [
            {
                "edge_label": "references",
                "direction": "out",
                "adjacent_id": "entity:concept",
            }
        ],
        "entity:concept": [
            {
                "edge_label": "references",
                "direction": "in",
                "adjacent_id": "note:organized",
            }
        ],
    }
    storage.get_connections.side_effect = lambda record_id: connections[record_id]

    result = await search_memory(storage, "memory", k=5)

    assert storage.get_connections.await_count == 2
    assert {call.args[0] for call in storage.get_connections.await_args_list} == {
        "note:organized",
        "entity:concept",
    }
    assert all(node["connections"] == connections[node["id"]] for node in result.nodes)
    assert all("connections" not in chunk for chunk in result.unprocessed)
    _assert_candidate_seam(storage)


async def test_empty_candidates_return_empty_collections_without_enrichment():
    storage = _storage(MemorySearchCandidates())

    result = await search_memory(storage, "memory", k=5)

    assert isinstance(result, MemorySearchResult)
    assert result.nodes == []
    assert result.unprocessed == []
    storage.get_connections.assert_not_awaited()
    _assert_candidate_seam(storage)


async def test_unprocessed_only_candidates_never_receive_graph_enrichment():
    chunk = _record("intake_chunk", "queued")
    storage = _storage(
        MemorySearchCandidates(
            intake_chunk=RankedSearchCandidates(bm25=[chunk], vector=[chunk])
        )
    )

    result = await search_memory(storage, "memory", k=5)

    assert result.nodes == []
    assert [record["id"] for record in result.unprocessed] == ["intake_chunk:queued"]
    assert result.unprocessed[0]["unprocessed"] is True
    assert "connections" not in result.unprocessed[0]
    storage.get_connections.assert_not_awaited()
    _assert_candidate_seam(storage)


async def test_graph_only_candidates_receive_connections_without_intake_evidence():
    note = _record("note", "organized")
    entity = _record("entity", "concept")
    storage = _storage(
        MemorySearchCandidates(
            note=RankedSearchCandidates(bm25=[note], vector=[note]),
            entity=RankedSearchCandidates(bm25=[entity], vector=[entity]),
        )
    )

    result = await search_memory(storage, "memory", k=5)

    assert {record["id"] for record in result.nodes} == {
        "note:organized",
        "entity:concept",
    }
    assert result.unprocessed == []
    assert all(record["connections"] == [] for record in result.nodes)
    assert storage.get_connections.await_count == 2
    _assert_candidate_seam(storage)
