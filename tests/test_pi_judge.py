from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from experiments.pi_judge import (
    PiJudgeError,
    resolve_cheap_model,
    run_pi_judge,
)
from experiments.run_experiment import (
    _cross_domain_coverage_error,
    _domain_probe_error,
    _parse_judge_output,
    judge_score_text,
)


def test_resolve_cheap_uses_global_tier(tmp_path: Path):
    agent_dir = tmp_path / "agent"
    agent_dir.mkdir()
    (agent_dir / "model-tiers.json").write_text(
        json.dumps({"cheap": "zai/glm-5.3:max"})
    )

    assert resolve_cheap_model(agent_dir=agent_dir, project_dir=tmp_path) == (
        "zai/glm-5.3:max"
    )


def test_project_cheap_overrides_global(tmp_path: Path):
    agent_dir = tmp_path / "agent"
    project_dir = tmp_path / "project"
    agent_dir.mkdir()
    (project_dir / ".pi").mkdir(parents=True)
    (agent_dir / "model-tiers.json").write_text(
        json.dumps({"cheap": "zai/glm-5.3:max"})
    )
    (project_dir / ".pi" / "model-tiers.json").write_text(
        json.dumps({"cheap": "openai/gpt-6-luna-1:high"})
    )

    assert resolve_cheap_model(agent_dir=agent_dir, project_dir=project_dir) == (
        "openai/gpt-6-luna-1:high"
    )


def test_missing_cheap_fails_instead_of_using_another_model(tmp_path: Path):
    with pytest.raises(PiJudgeError, match=r"cheap.*not configured"):
        resolve_cheap_model(agent_dir=tmp_path, project_dir=tmp_path)


def test_pi_judge_uses_configured_model_and_disables_tools(monkeypatch):
    calls = []

    def fake_run(command, **kwargs):
        calls.append((command, kwargs))
        return SimpleNamespace(returncode=0, stdout="[1]", stderr="")

    monkeypatch.delenv("PI_JUDGE_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setattr("experiments.pi_judge.subprocess.run", fake_run)

    assert (
        run_pi_judge("score this", model_ref="zai/glm-5.3:max", executable="pi")
        == "[1]"
    )
    command, kwargs = calls[0]
    assert command[:3] == ["pi", "--model", "zai/glm-5.3:max"]
    assert "--no-tools" in command
    assert "--no-extensions" in command
    assert "--no-session" in command
    assert kwargs["timeout"] == 900


def test_judge_output_requires_every_assertion():
    parsed = _parse_judge_output(
        '[{"n":1,"pass":true,"reason":"A direct edge supports it."}]',
        ["A relates to B"],
    )
    assert parsed == [
        {
            "assertion": "A relates to B",
            "pass": True,
            "reason": "A direct edge supports it.",
        }
    ]
    with pytest.raises(ValueError, match="omitted assertion"):
        _parse_judge_output("[]", ["A relates to B"])


def test_failed_judge_section_is_not_reported_as_zero_score():
    assert judge_score_text({}, {"space": "Pi is unavailable"}, "space", 22) == (
        "NOT SCORED"
    )


def test_cross_domain_isolation_requires_nodes_from_both_domains():
    error = _cross_domain_coverage_error(
        [{"domain": "SPACE", "node": None}, {"domain": "RENAISSANCE", "node": None}]
    )
    assert error == "Not scored: cross-domain graph coverage is incomplete."
    assert (
        _cross_domain_coverage_error(
            [
                {"domain": "SPACE", "node": {"name": "Apollo 11"}},
                {"domain": "RENAISSANCE", "node": {"name": "Michelangelo"}},
            ]
        )
        is None
    )
    assert "coverage is incomplete" in _cross_domain_coverage_error(
        [
            {"domain": "SPACE", "node": {"name": "Apollo 11"}},
            {"domain": "RENAISSANCE", "node": None, "error": "HTTP 500"},
        ]
    )


def test_domain_relationship_score_is_unscored_when_probe_coverage_is_incomplete():
    error = _domain_probe_error(
        [
            {"domain": "SPACE", "node": {"name": "Apollo 11"}},
            {"domain": "SPACE", "node": None, "error": "HTTP 500"},
            {"domain": "RENAISSANCE", "node": None, "error": "no citation"},
        ],
        "SPACE",
    )
    assert error == (
        "Not scored: Space graph coverage is incomplete "
        "(1 lookup error, 1 probe without node data)."
    )
