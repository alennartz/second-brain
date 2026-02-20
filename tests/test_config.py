from second_brain.config import Settings


def test_test_mode_defaults_false():
    assert Settings.model_fields["test_mode"].default is False


def test_test_mode_from_env(monkeypatch):
    monkeypatch.setenv("BRAIN_TEST_MODE", "true")
    s = Settings(_env_file=None)  # pyright: ignore[reportCallIssue]
    assert s.test_mode is True
