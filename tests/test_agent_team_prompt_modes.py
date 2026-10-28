"""A run chooses one prompt family for its coordinator and every member."""
from types import SimpleNamespace

import pytest

from plugins.tools.create_subagent import _resolve_specialist_prompt
from server.profile import PROFILE_NAME, build_profile_overrides
from workflows.agent_team import prompt_standard
from workflows.agent_team.phase_budget import TeamPhaseBudget, TeamPhaseBudgetObserver
from workflows.agent_team.profile import load_swarm_profile
from workflows.agent_team.prompts import (
    EVIDENCE_LIMITS_NOTE,
    FINAL_VERIFIER,
    LOCAL_VERIFIER,
    SEARCH_QUERY_LANGUAGE_NOTE,
    SUBAGENT_RESEARCH,
    TEAM_MANAGEMENT,
    get_main_system_prompt,
    resolve_prompt_mode,
)
from workflows.agent_team.subagent_runtime import SwarmSubagentRuntime


@pytest.mark.parametrize("mode", ["standard", "research"])
@pytest.mark.parametrize("phase", ["combined", "planning", "execution"])
def test_selected_family_reaches_each_coordinator_phase(mode, phase):
    prompt = get_main_system_prompt(
        "2026-10-28", prompt_mode=mode, phase=phase, planning_mode=True,
    )
    assert EVIDENCE_LIMITS_NOTE in prompt
    if mode == "standard":
        assert SEARCH_QUERY_LANGUAGE_NOTE not in prompt
        assert prompt_standard.SEARCH_LANGUAGE in prompt
        assert TEAM_MANAGEMENT not in prompt
        if phase != "planning":
            assert prompt_standard.COORDINATION in prompt
    else:
        assert SEARCH_QUERY_LANGUAGE_NOTE in prompt
        assert prompt_standard.COORDINATION not in prompt
        if phase != "planning":
            assert TEAM_MANAGEMENT in prompt


@pytest.mark.parametrize("mode", ["standard", "research"])
@pytest.mark.parametrize("name", ["source_reader", "final_verifier", "local_verifier"])
def test_runtime_selection_reaches_all_specialist_roles(mode, name):
    prompt = _resolve_specialist_prompt(
        name, "test role", fs_mode=False,
        runtime=SwarmSubagentRuntime(prompt_mode=mode),
    )
    originals = {
        "source_reader": SUBAGENT_RESEARCH,
        "final_verifier": FINAL_VERIFIER,
        "local_verifier": LOCAL_VERIFIER,
    }
    everyday = {
        "source_reader": prompt_standard.RESEARCHER,
        "final_verifier": prompt_standard.VERIFIER,
        "local_verifier": prompt_standard.CONFLICT_REVIEWER,
    }
    assert prompt.startswith((originals if mode == "research" else everyday)[name])
    assert EVIDENCE_LIMITS_NOTE in prompt
    assert (SEARCH_QUERY_LANGUAGE_NOTE in prompt) == (mode == "research")


def test_web_defaults_and_explicit_research_override_are_run_local():
    overrides = build_profile_overrides(pipeline_id="agent_team")
    baseline = load_swarm_profile(PROFILE_NAME, overrides=overrides)
    assert baseline["agent"]["prompt_mode"] == "standard"
    overrides["agent"]["prompt_mode"] = "research"
    selected = load_swarm_profile(PROFILE_NAME, overrides=overrides)
    assert selected["agent"]["prompt_mode"] == "research"
    assert load_swarm_profile(PROFILE_NAME)["agent"]["prompt_mode"] == "standard"
    assert baseline["agent"]["prompt_mode"] == "standard"
    assert resolve_prompt_mode(None) == "standard"
    with pytest.raises(ValueError, match="prompt_mode"):
        resolve_prompt_mode("typo")


@pytest.mark.parametrize("mode", ["standard", "research"])
async def test_phase_hint_does_not_restore_mandatory_review_for_everyday_tasks(mode):
    import time

    now = time.monotonic()
    budget = TeamPhaseBudget(now - 50, now - 1, now + 30, now + 60, now + 90, {})
    observer = TeamPhaseBudgetObserver(budget, prompt_mode=mode)
    intervention = await observer.on_turn_end(SimpleNamespace(metadata={}))
    assert intervention is not None
    text = " ".join(intervention.inject_messages)
    assert ("dispatch final_verifier" in text) == (mode == "research")
    assert budget.research_deadline_s == now + 30
