from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from apodex.semantic_access import require_readonly_semantic_store
from server.profile import build_profile_overrides


def test_web_profile_bounds_zero_chunk_wait_without_overriding_other_timeouts() -> None:
    agent = build_profile_overrides()["agent"]

    assert agent["first_chunk_s"] == 45
    assert "llm_timeout_s" not in agent
    assert "tool_timeout_s" not in agent


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


@pytest.mark.skipif(
    sys.platform != "linux" or shutil.which("bwrap") is None,
    reason="bubblewrap mount namespace requires Linux",
)
def test_web_worker_wrapper_exposes_only_readonly_store(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from server.orchestrator import _readonly_semantic_worker_command

    store = tmp_path / "store"
    run_dir = tmp_path / "run"
    store.mkdir()
    run_dir.mkdir()
    prepared: list[Path] = []
    monkeypatch.setattr(
        "plugins.corpus.structured.store.prepare_readonly_access",
        lambda *, store_root: prepared.append(Path(store_root)),
    )
    probe = (
        "import os; "
        "from pathlib import Path; "
        "from apodex.semantic_access import require_readonly_semantic_store; "
        "require_readonly_semantic_store(required=True); "
        "assert not os.access(os.environ['CORPUS_STRUCTURED_ROOT'], os.W_OK); "
        "rel=Path(os.environ['CORPUS_STRUCTURED_ROOT']).relative_to('/'); "
        "assert all(not os.access(root / rel, os.W_OK) "
        "for root in Path('/proc').glob('[0-9]*/root')); "
        "(Path(os.environ['RUN_DIR']) / 'worker-write').write_text('ok')"
    )
    command = _readonly_semantic_worker_command(
        [sys.executable, "-c", probe],
        run_dir=run_dir,
        store_root=store,
    )
    env = {
        **os.environ,
        "CORPUS_STRUCTURED_ROOT": str(store),
        "RUN_DIR": str(run_dir),
    }

    completed = subprocess.run(command, env=env, check=False, capture_output=True, text=True)

    assert completed.returncode == 0, completed.stderr
    assert prepared == [store.resolve()]
    assert (run_dir / "worker-write").read_text() == "ok"


def test_web_worker_wrapper_rejects_writable_store_alias(tmp_path: Path) -> None:
    from server.orchestrator import _readonly_semantic_worker_command

    store = tmp_path / "store"
    store.mkdir()
    with pytest.raises(RuntimeError, match="must not overlap"):
        _readonly_semantic_worker_command(
            [sys.executable, "-c", "pass"],
            run_dir=store / "runs" / "one",
            store_root=store,
        )


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
