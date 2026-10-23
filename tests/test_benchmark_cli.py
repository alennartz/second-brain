from __future__ import annotations

from experiments import run_experiment


def test_help_prints_usage_without_creating_a_run(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(run_experiment.sys, "argv", ["run_experiment.py", "--help"])
    monkeypatch.setattr(run_experiment, "EXPERIMENTS_DIR", str(tmp_path))
    monkeypatch.setattr(run_experiment, "_install_signal_handlers", lambda _state: None)

    def reject_server_start(*_args, **_kwargs):
        raise AssertionError("help must not start a benchmark server")

    monkeypatch.setattr(run_experiment, "ServerSupervisor", reject_server_start)

    run_experiment.main()

    assert "Usage:" in capsys.readouterr().out
    assert list(tmp_path.iterdir()) == []
