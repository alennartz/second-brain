from unittest.mock import Mock

import pytest
from experiments import run_experiment


@pytest.fixture(autouse=True)
def no_retry_sleep(monkeypatch):
    monkeypatch.setattr(run_experiment.time, "sleep", lambda _seconds: None)


def test_entity_probe_raises_when_recall_returns_http_error():
    response = Mock(status_code=500)
    client = Mock()
    client.post.return_value = response

    with pytest.raises(run_experiment.GraphProbeLookupError, match="HTTP 500"):
        run_experiment.find_entity_id(client, "http://brain", "Apollo 11")

    assert client.post.call_count == 3


def test_entity_probe_raises_when_recall_returns_no_cited_context():
    response = Mock(status_code=200)
    response.json.return_value = {"context": None}
    client = Mock()
    client.post.return_value = response

    with pytest.raises(run_experiment.GraphProbeLookupError, match="no cited entity"):
        run_experiment.find_entity_id(client, "http://brain", "Apollo 11")

    assert client.post.call_count == 3


def test_entity_probe_does_not_return_an_unrelated_entity():
    response = Mock(status_code=200)
    response.json.return_value = {
        "context": {
            "nodes": [
                {
                    "id": "entity:unrelated",
                    "table": "entity",
                    "name": "Wernher von Braun",
                }
            ]
        }
    }
    client = Mock()
    client.post.return_value = response

    with pytest.raises(run_experiment.GraphProbeLookupError, match="Apollo 11"):
        run_experiment.find_entity_id(client, "http://brain", "Apollo 11")


def test_entity_probe_returns_matching_entity_id():
    response = Mock(status_code=200)
    response.json.return_value = {
        "context": {
            "nodes": [
                {"id": "entity:korolev", "table": "entity", "name": "Sergei Korolev"}
            ]
        }
    }
    client = Mock()
    client.post.return_value = response

    assert (
        run_experiment.find_entity_id(client, "http://brain", "Korolev")
        == "entity:korolev"
    )
    client.post.assert_called_once()


def test_graph_report_preserves_lookup_failure_reason():
    graph_text = run_experiment._format_graph_neighborhood(
        [
            {
                "name": "Apollo 11",
                "domain": "SPACE",
                "id": None,
                "node": None,
                "connections": [],
                "error": "POST /recall returned HTTP 500",
            }
        ]
    )
    assert "LOOKUP FAILED" in graph_text
    assert "HTTP 500" in graph_text
    assert "NOT FOUND IN GRAPH" not in graph_text
