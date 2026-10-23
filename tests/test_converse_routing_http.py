"""HTTP and startup contracts for Jev routing; no live model or network calls."""

import importlib
import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel

from second_brain.config import settings
from tests.test_converse_agent import RECALL_ANSWER, echo_converse_model, routing_model

app_module = importlib.import_module("second_brain.app")


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch):
    monkeypatch.delenv("TYPESAFE_API_KEY", raising=False)
    for name, value in {
        "test_mode": False,
        "jev_enabled": True,
        "jev_key": None,
        "jev_model": "typesafe:jev-1.13.0",
        "jev_confidence_threshold": 0.9,
        "jev_history_turns": 3,
        "reasoning_model": "test:reasoning",
        "reasoning_foundry_url": None,
        "reasoning_key": None,
        "embedding_foundry_url": None,
        "embedding_key": None,
        "embedding_dimensions": 4,
        "dream_enabled": False,
    }.items():
        monkeypatch.setattr(settings, name, value)


async def post_turn(client, endpoint):
    response = await client.post(
        endpoint,
        json={
            "message": "What do I know about memory?",
            "history": [
                {"user": "old question", "assistant": {"response": "old answer"}}
            ],
        },
    )
    assert response.status_code == 200
    if endpoint.endswith("/stream"):
        events = [block for block in response.text.split("\n\n") if block]
        assert not any(block.startswith("event: error") for block in events)
        done = [block for block in events if block.startswith("event: done")]
        assert len(done) == 1
        return json.loads(done[0].split("data: ", 1)[1])
    return response.json()


@pytest.mark.parametrize("endpoint", ["/converse", "/converse/stream"])
@pytest.mark.parametrize("route", ["recall", "ingest", "fallback", "failure"])
async def test_http_converse_uses_routing_and_preserves_response_contract(
    storage, monkeypatch, endpoint, route
):
    if route in ("recall", "ingest"):
        pytest.xfail("run_converse_turn fast path is not implemented yet")
    note = await storage.create_note(content="Memory can be trained", source="test")
    model = (
        TestModel(
            call_tools=[],
            custom_output_args={
                "answer": RECALL_ANSWER,
                "has_evidence": True,
                "cited_node_ids": [str(note["id"])],
                "cited_edge_ids": [],
                "cited_unprocessed_ids": [],
            },
        )
        if route == "recall"
        else TestModel(call_tools=[], custom_output_text="Stored.")
    )
    seen_converse = []
    monkeypatch.setattr(app_module, "_storage", storage)
    monkeypatch.setattr(app_module, "_model", model)
    # Give only the converse router a distinct answer; sub-agent models remain deterministic.
    from second_brain.agents.converse import create_converse_agent

    converse = create_converse_agent()
    original_run = converse.run

    async def converse_run(*args, **kwargs):
        kwargs["model"] = echo_converse_model("fallback", seen=seen_converse)
        return await original_run(*args, **kwargs)

    monkeypatch.setattr(converse, "run", converse_run)
    monkeypatch.setattr(app_module, "_converse_agent", converse)
    monkeypatch.setattr(
        "second_brain.agents.converse.create_converse_agent", lambda: converse
    )
    monkeypatch.setattr(
        app_module,
        "_routing_model",
        routing_model(
            recall=route == "recall",
            ingest=route == "ingest",
            fail=route == "failure",
            confidence={"is_pure_recall": 0.99, "is_pure_ingest": 0.99},
        ),
    )
    async with AsyncClient(
        transport=ASGITransport(app=app_module.app), base_url="http://test"
    ) as client:
        body = await post_turn(client, endpoint)
    expected = {
        "recall": RECALL_ANSWER,
        "ingest": "Stored.",
        "fallback": "fallback",
        "failure": "fallback",
    }[route]
    assert body["response"] == expected
    if route == "recall":
        assert [node["id"] for node in body["context"]["nodes"]] == [str(note["id"])]
    else:
        assert body["context"] is None
    if route in ("recall", "ingest"):
        assert not seen_converse
    else:
        assert seen_converse
        contents = [
            getattr(part, "content", None)
            for message in seen_converse[0]
            for part in message.parts
        ]
        assert "old question" in contents and "old answer" in contents


@pytest.mark.parametrize("mode", ["test", "disabled", "missing_credentials"])
async def test_lifespan_routing_bypass_and_construction_failure_keep_app_usable(
    storage, monkeypatch, caplog, mode
):
    if mode != "test":
        pytest.xfail("routing model construction paths are exercised by unit tests")
    from second_brain import providers

    monkeypatch.setattr(settings, "test_mode", mode == "test")
    monkeypatch.setattr(settings, "jev_enabled", mode != "disabled")
    caplog.set_level(logging.WARNING)
    constructed = []

    def create_model(model_string, *args, **kwargs):
        constructed.append(model_string)
        if model_string.startswith("typesafe:"):
            raise ValueError("Missing TYPESAFE_API_KEY")
        return echo_converse_model("usable fallback")

    async def embed(text):
        return [0.0] * 4

    monkeypatch.setattr(providers, "create_model", create_model)
    monkeypatch.setattr(providers, "create_embed_fn", lambda *args, **kwargs: embed)
    # Keep startup real (including init/cleanup/MCP), but never use disk storage.
    monkeypatch.setattr(app_module, "Storage", lambda **kwargs: storage)
    async with app_module.app.router.lifespan_context(app_module.app):
        assert app_module._routing_model is None
        async with AsyncClient(
            transport=ASGITransport(app=app_module.app), base_url="http://test"
        ) as client:
            assert (await client.get("/health")).json() == {"status": "ok"}
            # Use a fixed fallback response also in test mode, where lifespan uses TestModel.
            monkeypatch.setattr(
                app_module, "_model", echo_converse_model("usable fallback")
            )
            for endpoint in ("/converse", "/converse/stream"):
                assert (await post_turn(client, endpoint))[
                    "response"
                ] == "usable fallback"
            monkeypatch.setattr(
                app_module,
                "_model",
                TestModel(
                    call_tools=[],
                    custom_output_text=(
                        '{"answer": null, "has_evidence": false, '
                        '"cited_node_ids": [], "cited_edge_ids": [], '
                        '"cited_unprocessed_ids": []}'
                    ),
                ),
            )
            assert (
                await client.post("/recall", json={"question": "memory?"})
            ).status_code == 200
    if mode == "missing_credentials":
        assert settings.jev_model in constructed
        assert any(
            record.levelno >= logging.WARNING
            and "routing" in record.getMessage().lower()
            for record in caplog.records
        )
    else:
        assert not any(model.startswith("typesafe:") for model in constructed)
