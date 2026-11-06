"""One isolated process, real production team node, real LLM, fixed external data."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from pathlib import Path
from typing import Any

from benchmarks.team_workflow.fixtures import COORDINATION, fixed_tools


def budget_layout(agent: dict[str, Any]) -> dict[str, Any]:
    """Expose the production budget calculation, including short-window risks."""
    from frontier_agent.core.runtime.loop.tool_exec import max_tool_wall_time_s
    from workflows.agent_team.nodes import main_agent as node

    timeouts = node._resolve_team_loop_timeouts(agent)
    finalization = node._resolve_finalization_timeout_s(agent, llm_timeout_s=timeouts.llm_timeout_s)
    wind_down = node._resolve_team_wind_down_timeout_s(agent)
    tool_wall = max_tool_wall_time_s(timeouts.tool_timeout_s)
    reserve = max(
        float(agent.get("wall_deadline_reserve_s", 180)), tool_wall + finalization + wind_down
    )
    wall = node._resolve_research_wall(agent, hard_wall_reserve_s=reserve)
    budget = node._build_team_phase_budget(
        started_monotonic_s=0,
        research_wall_s=wall.research_deadline_s,
        publication_phase_timeout_s=node._resolve_publication_phase_timeout_s(agent),
        hard_deadline_monotonic_s=wall.hard_total_s or None,
        finalization_timeout_s=finalization,
        wind_down_timeout_s=wind_down,
        worst_case_tool_s=tool_wall,
        publication_state={},
        verification_phase_timeout_s=node._resolve_verification_phase_timeout_s(agent),
    )
    return {
        "hard_wall_s": wall.hard_total_s,
        "research_dispatch_cutoff_s": budget.research_dispatch_deadline_s,
        "research_cutoff_s": budget.research_deadline_s,
        "publication_cutoff_s": budget.publication_deadline_s,
        "warning": "Budget includes all phases; wall budget is not research time.",
    }


async def execute(case: dict[str, Any], out: Path, profile: str) -> dict[str, Any]:
    from frontier_agent.components.agent_bus import AgentBus
    from frontier_agent.core.runtime.registries import AgentRegistry, services
    from frontier_agent.core.runtime.resources.manager import ResourceManager
    from frontier_agent.models.node_context import NodeContext
    from workflows.agent_team import MAIN_AGENT_DEF, SUB_AGENT_DEF
    from workflows.agent_team.nodes.main_agent import main_agent_node
    from workflows.agent_team.profile import create_swarm_llm, load_swarm_profile
    from workflows.agent_team.spec import SWARM_SPEC

    wall = case["budgets"]["wall_s"]
    overrides = {
        "llm": {"max_tokens": 8192},
        "agent": {
            "main_agent_tools": [n for n in COORDINATION if n != "submit_report"] + ["web_search"],
            "sub_agent_tools": ["web_search", "web_fetch", "submit_report"],
            "web_search_impl": "original",
            "web_fetch_impl": "original",
            "reporter": False,
            "main_max_turns": 40,
            "sub_max_turns": 16,
            "planning_mode": False,
            "tool_timeout_s": 15,
            "llm_timeout_s": 120,
            "logical_call_timeout_s": 120,
            "reasoning_only_timeout_s": 90,
            "reasoning_only_max_tokens": 6144,
            "finalization_timeout_s": 45,
            "wall_deadline_reserve_s": 90,
            "publication_phase_timeout_s": 90,
            "verification_phase_timeout_s": 90,
            "wall_deadline_s": wall,
            "research_wall_time_s": None,
        },
    }
    effective = load_swarm_profile(profile, overrides=overrides)
    public_settings = {
        "model_settings": {
            key: effective["llm"].get(key)
            for key in ("model", "provider", "temperature", "top_p", "max_tokens")
        },
        "effective_agent_settings": effective.get("agent", {}),
        "budget_layout": budget_layout(effective.get("agent", {})),
    }
    (out / "settings.json").write_text(json.dumps(public_settings, ensure_ascii=False, indent=2))
    dispatch_window = public_settings["budget_layout"]["research_dispatch_cutoff_s"]
    if dispatch_window is None or dispatch_window < 90:
        return {
            "ok": False,
            "error_type": "EvaluationBudgetError",
            "error": "Fixed-source semantic evaluation requires at least 90 seconds for dispatch.",
            "elapsed_s": 0,
            **public_settings,
        }
    llm = create_swarm_llm(effective)
    tools = fixed_tools(case["sources"])
    agents = AgentRegistry()
    agents.register(MAIN_AGENT_DEF)
    agents.register(SUB_AGENT_DEF)
    services.register(AgentRegistry, agents)
    services.register(AgentBus, AgentBus())
    services.register(ResourceManager, ResourceManager(llm, tools))
    task = f"team-eval-{case['id']}"
    # Only question and fixed source directory enter the model. No rubric, expected
    # outcome, split label, provenance or budget acceptance thresholds enter it.
    question = (
        case["question"]
        + "\n\n可检索的固定资料入口：\n"
        + "\n".join(f"{source['title']}: {source['url']}" for source in case["sources"])
    )
    metadata = {
        "profile": profile,
        "profile_overrides": overrides,
        "bus_task_id": task,
        "run_id": task,
        "_trial_dir": str(out),
        "pipeline_id": "agent_team",
    }
    start = time.monotonic()
    try:
        result = await asyncio.wait_for(
            main_agent_node(
                {
                    "original_question": question,
                    "metadata": metadata,
                    "continuity_enabled": False,
                    "continuity_write_enabled": False,
                },
                NodeContext(SWARM_SPEC.nodes[0], lambda: task),
            ),
            timeout=wall + 30,
        )
        return {
            "ok": True,
            "elapsed_s": time.monotonic() - start,
            "result": result,
            "profile_overrides": overrides,
            **public_settings,
        }
    except Exception as exc:
        return {
            "ok": False,
            "elapsed_s": time.monotonic() - start,
            "error_type": type(exc).__name__,
            "error": str(exc),
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profile", default="default")
    args = parser.parse_args()
    case = json.loads(args.input.read_text())
    result = asyncio.run(execute(case, args.out.resolve(), args.profile))
    (args.out / "worker.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str)
    )


if __name__ == "__main__":
    main()
