"""The bwrap jail must preserve the host runtime paths tools are configured to use."""

from __future__ import annotations

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
