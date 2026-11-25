import pytest


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Isolate logs, trash and policy from the real home directory."""
    monkeypatch.setenv("CLAUDE_VERBS_LOG_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("CLAUDE_VERBS_TRASH", str(tmp_path / "trash"))
    monkeypatch.delenv("CLAUDE_VERBS_POLICY", raising=False)
    return tmp_path
