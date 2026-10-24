"""Stable Web run-mode contract and its concrete workflow mapping."""

from __future__ import annotations

from enum import StrEnum


class RunMode(StrEnum):
    SINGLE = "single"
    TEAM = "team"


_PIPELINE_BY_MODE = {
    RunMode.SINGLE: "stateful-react-agent",
    RunMode.TEAM: "agent_team",
}


def pipeline_for_mode(mode: RunMode | str) -> str:
    """Resolve a validated product mode to its frozen workflow identity."""

    return _PIPELINE_BY_MODE[RunMode(mode)]


def mode_for_pipeline(pipeline_id: str) -> RunMode:
    """Resolve persisted workflow identity to a product mode."""

    for mode, candidate in _PIPELINE_BY_MODE.items():
        if candidate == pipeline_id:
            return mode
    raise ValueError(f"pipeline {pipeline_id!r} has no Web run mode")


__all__ = ["RunMode", "mode_for_pipeline", "pipeline_for_mode"]
