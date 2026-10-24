"""The bwrap jail must preserve the host runtime paths tools are configured to use."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest


def test_tool_env_uses_the_running_venv_without_outer_path_help(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Direct ``.venv/bin/python`` launches must not fall back to system Python."""
    from plugins.tools import _sandbox

    venv = tmp_path / ".venv"
    (venv / "bin").mkdir(parents=True)
    (venv / "bin" / "python3").write_text("interpreter")
    monkeypatch.setattr(_sandbox.sys, "prefix", str(venv))
    monkeypatch.setattr(_sandbox.sys, "base_prefix", "/usr")
    monkeypatch.setattr(_sandbox, "_tool_overlay_venv", lambda _env: None)

    projected = _sandbox._build_tool_env(
        {"PATH": "/usr/bin:/bin"}, home="/workspace", overlay_writable=False,
    )

    assert projected["PATH"].split(":")[0] == str(venv / "bin")
    assert projected["VIRTUAL_ENV"] == str(venv)


def test_external_symlink_targets_are_bound_at_the_visible_path(tmp_path: Path) -> None:
    """A bind of only the final target does not repair an absolute symlink.

    WSL uses this shape for ``/etc/resolv.conf``: the link is visible through
    the ``/etc`` bind, while its target under ``/mnt/wsl`` is outside the jail.
    """
    from plugins.tools import _sandbox

    target = tmp_path / "external" / "resolv.conf"
    target.parent.mkdir()
    target.write_text("nameserver 192.0.2.53\n")
    visible = tmp_path / "etc" / "resolv.conf"
    visible.parent.mkdir()
    visible.symlink_to(target)

    args = _sandbox._external_symlink_target_bind_args(
        (visible,), covered_roots=(visible.parent,),
    )

    assert args == ["--ro-bind", str(target), str(target)]


def test_interpreter_bind_keeps_uv_alias_directory_visible(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """uv's venv python points through an unversioned directory symlink.

    Binding the venv and resolved ``sys.base_prefix`` still leaves the absolute
    target written into ``venv/bin/python`` dangling unless its alias path is
    mounted too.
    """
    from plugins.tools import _sandbox

    versioned = tmp_path / "python" / "cpython-3.12.14-linux-x86_64-gnu"
    (versioned / "bin").mkdir(parents=True)
    (versioned / "bin" / "python3.12").write_text("interpreter")
    alias = tmp_path / "python" / "cpython-3.12-linux-x86_64-gnu"
    alias.symlink_to(versioned, target_is_directory=True)
    venv = tmp_path / "project" / ".venv"
    (venv / "bin").mkdir(parents=True)
    executable = venv / "bin" / "python"
    executable.symlink_to(alias / "bin" / "python3.12")

    monkeypatch.setattr(_sandbox, "_BWRAP_SYSTEM_PATHS", ())
    monkeypatch.setattr(_sandbox.sys, "prefix", str(venv))
    monkeypatch.setattr(_sandbox.sys, "base_prefix", str(versioned))
    monkeypatch.setattr(_sandbox.sys, "executable", str(executable))

    args = _sandbox._interpreter_bind_args()
    triples = list(zip(args[::3], args[1::3], args[2::3], strict=True))

    assert ("--ro-bind", str(versioned), str(alias)) in triples


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
def test_bwrap_can_read_resolver_and_run_the_configured_venv(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration gate for the exact WSL + uv failures found in the Web run."""
    from plugins.tools import _sandbox

    if not _sandbox.bwrap_available():
        pytest.skip("bubblewrap unavailable")
    monkeypatch.setenv(
        "PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ.get("PATH", ""),
    )
    sandbox = _sandbox.BwrapSandbox(workspace=tmp_path / "workspace")
    try:
        resolver = sandbox.commands.run("test -r /etc/resolv.conf", timeout=5)
        interpreter = sandbox.commands.run(
            "python3 -c 'import openpyxl, pypdf, sys; print(sys.prefix)'", timeout=5,
        )
    finally:
        sandbox.kill()

    assert resolver.exit_code == 0, resolver.stderr
    assert interpreter.exit_code == 0, interpreter.stderr
    assert interpreter.stdout.strip() == sys.prefix


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
def test_sandbox_grep_preserves_errors_and_limits_context_matches(tmp_path: Path) -> None:
    """The sandbox branch must count matches and retain grep's own failures."""
    from plugins.tools import _sandbox
    from plugins.tools._sandbox import (
        BwrapSandbox,
        clear_task_sandbox,
        set_task_sandbox,
    )
    from plugins.tools.grep_search import grep_search

    if not _sandbox.bwrap_available():
        pytest.skip("bubblewrap unavailable")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "dense.txt").write_text(
        "\n".join(f"match {index}" for index in range(1, 21)),
        encoding="utf-8",
    )
    sandbox = BwrapSandbox(workspace=workspace)
    token = set_task_sandbox(sandbox)
    try:
        output = asyncio.run(grep_search.ainvoke({
            "pattern": "match",
            "path": "/workspace/dense.txt",
            "max_results": 3,
            "context_lines": 1,
        }))
        invalid = asyncio.run(grep_search.ainvoke({
            "pattern": "[",
            "path": "/workspace/dense.txt",
        }))
        missing = asyncio.run(grep_search.ainvoke({
            "pattern": "match",
            "path": "/workspace/missing.txt",
        }))
    finally:
        clear_task_sandbox(token)
        sandbox.kill()

    match_rows = [line for line in output.splitlines() if line.startswith(">")]
    assert len(match_rows) == 3, output
    assert "Results truncated" in output
    assert invalid.startswith("Error: grep failed:"), invalid
    assert missing.startswith("Error: grep failed:"), missing


@pytest.mark.skipif(sys.platform != "linux", reason="bubblewrap is Linux-only")
def test_read_file_recovers_a_spilled_result_through_the_bwrap_mount(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A model-visible ``/spill`` path must stay in the bwrap namespace.

    The harness writes the body to a host directory and BwrapSandbox mounts that
    directory read-only at ``/spill``. Rewriting the visible path back to the
    host directory before invoking the sandbox makes read_file target a path the
    jail cannot see, even though ``cat /spill/...`` succeeds in the same jail.
    """
    from frontier_agent.core.execution_context import (
        ExecutionScope,
        reset_current_execution_scope,
        set_current_execution_scope,
    )
    from plugins.tools import _overflow, _sandbox
    from plugins.tools._sandbox import (
        BwrapSandbox,
        clear_task_sandbox,
        set_task_sandbox,
    )
    from plugins.tools.glob_search import glob_search
    from plugins.tools.grep_search import grep_search
    from plugins.tools.read_file import read_file

    if not _sandbox.bwrap_available():
        pytest.skip("bubblewrap unavailable")

    monkeypatch.setenv("SANDBOX_BACKEND", "bwrap")
    monkeypatch.setenv("APODEX_SPILL_DIR", str(tmp_path / "spill-store"))
    scope_token = set_current_execution_scope(
        ExecutionScope(task_id="spill-read", metadata={"llm_session_id": "session"}),
    )
    saved_stores = set(_overflow._created_stores)
    sandbox: BwrapSandbox | None = None
    sandbox_token = None
    try:
        visible = _overflow.spill_compacted_body(
            "bash", "RECOVERED THROUGH BWRAP\n" + "detail " * 400,
        )
        assert visible and visible.startswith("/spill/")

        sandbox = BwrapSandbox(workspace=tmp_path / "workspace")
        sandbox_token = set_task_sandbox(sandbox)
        shell_read = sandbox.commands.run(f"grep -q 'RECOVERED THROUGH BWRAP' {visible}")
        readout = asyncio.run(
            read_file.ainvoke({"path": visible, "max_chars": 8_000}),
        )
        grep_out = asyncio.run(
            grep_search.ainvoke({
                "pattern": "RECOVERED THROUGH BWRAP",
                "path": visible,
            }),
        )
        glob_out = asyncio.run(
            glob_search.ainvoke({
                "pattern": "*.md",
                "path": visible.rsplit("/", 1)[0],
            }),
        )
    finally:
        if sandbox_token is not None:
            clear_task_sandbox(sandbox_token)
        if sandbox is not None:
            sandbox.kill()
        reset_current_execution_scope(scope_token)
        _overflow._created_stores.clear()
        _overflow._created_stores.update(saved_stores)

    assert shell_read.exit_code == 0, shell_read.stderr
    assert "RECOVERED THROUGH BWRAP" in readout, readout
    assert "RECOVERED THROUGH BWRAP" in grep_out, grep_out
    assert visible.rsplit("/", 1)[1] in glob_out, glob_out


def test_current_namespace_still_resolves_canonical_paths_to_physical_roots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Native/ordinary-container commands share the harness filesystem."""
    from types import SimpleNamespace

    from plugins.tools._sandbox import (
        clear_task_sandbox,
        resolve_runtime_path,
        set_task_sandbox,
    )

    workspace = tmp_path / "workspace"
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    spill = tmp_path / "spill"
    for directory in (workspace, outputs, inputs, spill):
        directory.mkdir()
    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", str(outputs))
    monkeypatch.setenv("FRONTIER_AGENT_INPUTS_DIR", str(inputs))
    monkeypatch.setenv("APODEX_SPILL_DIR", str(spill))

    token = set_task_sandbox(SimpleNamespace(uses_canonical_mount_paths=False))
    try:
        assert resolve_runtime_path("/workspace/a.txt") == str(workspace / "a.txt")
        assert resolve_runtime_path("/outputs/a.txt") == str(outputs / "a.txt")
        assert resolve_runtime_path("/inputs/a.txt") == str(inputs / "a.txt")
        assert resolve_runtime_path("/spill/a.txt") == str(spill / "a.txt")
    finally:
        clear_task_sandbox(token)
