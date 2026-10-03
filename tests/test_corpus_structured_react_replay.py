"""Explicit experimental react profile and process-isolated product replays."""

from __future__ import annotations

import pytest


@pytest.fixture
def profiles(monkeypatch, tmp_path):
    import dotenv

    import apodex.profiles as profiles

    # Profile loading is tested with fake configuration, never a real .env.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(profiles, "_USER_DIR", tmp_path / "profiles")
    monkeypatch.setenv("OPENAI_MODEL", "synthetic-main")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://synthetic.invalid/v1")
    profiles._CACHE.clear()
    profiles._workflow_tool_names.cache_clear()
    yield profiles
    profiles._CACHE.clear()
    profiles._workflow_tool_names.cache_clear()


def test_react_semantic_profile_is_explicit_and_uses_workflow_tools(profiles, monkeypatch):
    monkeypatch.setenv("REACT_WORKFLOW_PROFILE", "tui-semantic")
    experiment = profiles.get_profile("react")
    assert experiment.workflow_profile == "tui-semantic"
    assert experiment.declared_tools == ()
    assert {"corpus_semantic_query", "corpus_fetch"} <= set(experiment.tool_names)
    profiles._CACHE.clear()
    monkeypatch.delenv("REACT_WORKFLOW_PROFILE")
    default = profiles.get_profile("react")
    assert default.workflow_profile == "tui"
    assert "corpus_semantic_query" not in default.tool_names
    assert set(experiment.tool_names) - set(default.tool_names) == {"corpus_semantic_query"}
