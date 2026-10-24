"""Web research budgets must survive the runtime's finalization reservation."""

from __future__ import annotations

import pytest

from frontier_agent.components.finalization.budget import resolve_research_wall
from frontier_agent.core.runtime.loop.tool_exec import max_tool_wall_time_s
from server.config import ServerConfig
from server.profile import PROFILE_NAME, build_profile_overrides
from workflows.stateful_react_agent.profile import load_react_profile


@pytest.mark.parametrize("hard_wall, expected", [(900, 450), (1400, 450), (120, 60), (6000, 450)])
def test_web_effective_research_budget(monkeypatch, hard_wall, expected):
    monkeypatch.setenv("FRONTIER_AGENT_TASK_WALL_TIME_S", str(hard_wall))
    agent = load_react_profile(PROFILE_NAME, overrides=build_profile_overrides())["agent"]
    reserve = max(
        float(agent.get("wall_deadline_reserve_s", 180)),
        max_tool_wall_time_s(float(agent["tool_timeout_s"]))
        + float(agent.get("finalization_timeout_s") or agent["llm_timeout_s"]),
    )
    wall = resolve_research_wall(agent, reserve_s=reserve, label_prefix="web-test")
    assert agent["research_wall_time_s"] == 450
    assert wall.research_deadline_s == expected
    assert wall.hard_total_s == hard_wall


def test_default_web_wall_allows_450_seconds_of_research(monkeypatch):
    monkeypatch.delenv("SERVER_WALL_TIMEOUT_S", raising=False)
    assert ServerConfig(_env_file=None).wall_timeout_s == 900
