from __future__ import annotations

import os
from pathlib import Path

import pytest

from apodex.semantic_access import require_readonly_semantic_store
from server.profile import build_profile_overrides


def test_web_profile_exposes_semantic_query_with_manifest_companion() -> None:
    from plugins.tools import get_builtin_tools
    from plugins.tools.corpus_manifest import with_manifest_tool

    names = build_profile_overrides()["agent"]["agent_tools"]
    assert "corpus_semantic_query" in names

    registry = get_builtin_tools()
    tools = [registry[name] for name in names]
    bound = with_manifest_tool(tools, role_id="web-agent")
    assert "corpus_submit_manifest" in {tool.name for tool in bound}


def test_strict_web_gate_rejects_missing_store(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CORPUS_STRUCTURED_ROOT", raising=False)
    with pytest.raises(ValueError, match="read-only publication-store mount"):
        require_readonly_semantic_store(required=True)


def test_strict_web_gate_rejects_missing_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(tmp_path / "absent"))
    with pytest.raises(ValueError, match="read-only publication-store mount"):
        require_readonly_semantic_store(required=True)


@pytest.mark.skipif(not hasattr(os, "statvfs"), reason="POSIX mount check")
def test_strict_web_gate_rejects_writable_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(tmp_path))
    with pytest.raises(ValueError, match="read-only publication-store mount"):
        require_readonly_semantic_store(required=True)


def test_web_worker_routes_semantic_audit_artifacts_to_run_dir(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from server.worker import apply_env

    for key in (
        "SANDBOX_BACKEND",
        "FRONTIER_AGENT_WORKSPACE_DIR",
        "FRONTIER_AGENT_OUTPUTS_DIR",
        "FRONTIER_AGENT_INPUTS_DIR",
        "CODING_WORKSPACE_ROOT",
        "APODEX_SPILL_DIR",
        "APODEX_RUN_DIR",
        "FRONTIER_AGENT_TASK_WALL_TIME_S",
        "FRONTIER_AGENT_MAX_TURNS",
        "BASH_ALLOWLIST_MODE",
        "FRONTIER_AGENT_TOOL_USER",
        "OPENAI_MODEL",
        "OPENAI_BASE_URL",
        "OPENAI_API_KEY",
    ):
        monkeypatch.setenv(key, os.environ.get(key, ""))

    paths = {
        "workspace": tmp_path / "ws",
        "outputs": tmp_path / "outputs",
        "inputs": tmp_path / "inputs",
        "spill": tmp_path / "spill",
        "run": tmp_path / "run",
    }
    apply_env(
        paths,
        backend="native",
        wall_time_s=60,
        max_turns=4,
        model="model",
        base_url="https://example.test/v1",
        api_key="key",
    )
    assert os.environ["APODEX_RUN_DIR"] == str(paths["run"])
