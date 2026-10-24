"""Shared workflow parsing for Web/benchmark sandbox mount metadata."""

from __future__ import annotations

from pathlib import Path


def test_single_and_team_reject_mount_destinations_outside_inputs(tmp_path: Path) -> None:
    from workflows.agent_team.nodes.main_agent import _resolve_sandbox_binds as team_binds
    from workflows.stateful_react_agent.nodes.main_agent import (
        _resolve_sandbox_binds as single_binds,
    )

    source = tmp_path / "source"
    source.mkdir()
    state = {
        "metadata": {
            "_sandbox_mounts": [
                {"src": str(source), "dst": "/inputs", "mode": "ro"},
                {"src": str(source), "dst": "/inputs_evil", "mode": "ro"},
                {"src": str(source), "dst": "/inputs/../etc", "mode": "ro"},
            ],
        },
    }

    single, _single_outputs = single_binds(state, tmp_path / "single-workspace")
    team_main, team_members, _team_outputs = team_binds(state, tmp_path / "team-workspace")

    assert [bind[1] for bind in single[:-1]] == ["/inputs"]
    assert [bind[1] for bind in team_main[:-1]] == ["/inputs"]
    assert team_members == team_main


def test_single_and_team_expand_mount_source_home(
    tmp_path: Path, monkeypatch,
) -> None:
    from workflows.agent_team.nodes.main_agent import _resolve_sandbox_binds as team_binds
    from workflows.stateful_react_agent.nodes.main_agent import (
        _resolve_sandbox_binds as single_binds,
    )

    monkeypatch.setenv("HOME", str(tmp_path))
    source = tmp_path / "inputs"
    source.mkdir()
    state = {
        "metadata": {
            "_sandbox_mounts": [
                {"src": "~/inputs", "dst": "/inputs", "mode": "ro"},
            ],
        },
    }

    single, _single_outputs = single_binds(state, tmp_path / "single-workspace")
    team_main, _team_members, _team_outputs = team_binds(state, tmp_path / "team-workspace")

    assert single[0][0] == str(source)
    assert team_main[0][0] == str(source)


def test_declared_inputs_cannot_request_a_writable_bind(tmp_path: Path) -> None:
    from workflows._shared.sandbox_mounts import resolve_sandbox_mount_metadata

    source = tmp_path / "inputs"
    source.mkdir()
    mounts, _outputs = resolve_sandbox_mount_metadata(
        {"_sandbox_mounts": [
            {"src": str(source), "dst": "/inputs", "mode": "rw"},
        ]},
        tmp_path / "workspace",
    )

    assert mounts == ((str(source), "/inputs", True),)
