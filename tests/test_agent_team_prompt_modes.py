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
    # One run contract for every family: no phase hint may restore a mandatory
    # whole-answer verifier, including research mode.
    assert "dispatch final_verifier" not in text
    assert "final_verifier" not in text
    assert "registered checks" in text
    assert "verification=not_assessed" in text
    assert budget.research_deadline_s == now + 30


# --- W4 P1: generated prompt matrix -------------------------------------------

_CONFLICT_MARKERS = (
    "For each task-board item, create_subagent",
    "dispatch every task-board item",
    "cover each work item with agents",
    "Dispatch every executable item",
    "Create_subagent + assign_task for every",
    "spawn a `final_verifier` sub-agent to independently re-derive",
    "dispatch final_verifier with",
    "A bounded final_verifier assignment",
    "answered AND corroborated",
    "corroborated (>=2 independent reports",
    "then verify, and finalize",
)


@pytest.mark.parametrize("mode", ["standard", "research"])
@pytest.mark.parametrize("phase", ["combined", "planning", "execution"])
@pytest.mark.parametrize("planning_mode", [True, False])
def test_generated_main_prompts_share_one_run_contract(mode, phase, planning_mode):
    """P1: assert on the assembled prompt, not on a source constant."""
    prompt = get_main_system_prompt(
        "2026-11-15", prompt_mode=mode, phase=phase, planning_mode=planning_mode,
    )
    assert prompt.strip()
    for marker in _CONFLICT_MARKERS:
        assert marker not in prompt, f"{mode}/{phase}/planning={planning_mode}: {marker}"
    assert EVIDENCE_LIMITS_NOTE in prompt
    assert "fetch only what could change the answer" in prompt
    assert "Keep provenance IDs" in prompt
    assert "state the trigger reason" in prompt
    assert "not by upgrading itself into a mandatory" in prompt


def test_reporter_prompts_share_the_run_contract():
    from workflows.agent_team.prompts_fast_reporter_v1 import (
        REVIEW_SYSTEM_PROMPT,
        WRITER_ADDENDUM,
    )
    from workflows.agent_team.prompts_report_fast import REPORT_FAST_SYSTEM_PROMPT

    for text in (REPORT_FAST_SYSTEM_PROMPT, REVIEW_SYSTEM_PROMPT, WRITER_ADDENDUM):
        for marker in _CONFLICT_MARKERS:
            assert marker not in text


def test_recovery_prompt_keeps_internal_bookkeeping_out_of_the_answer():
    from workflows.agent_team.subagent_runtime import _build_recovery_messages

    prompt = _build_recovery_messages(
        [], task_description="Explain the evidence", structured_report=False,
    )[0]["content"]
    assert "call ids, hashes" in prompt
    assert "do not fetch the same source again" in prompt
    for marker in _CONFLICT_MARKERS:
        assert marker not in prompt
