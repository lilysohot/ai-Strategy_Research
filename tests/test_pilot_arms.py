"""Pre-flight lock for the paired pilot arms (registration §17.6).

The pair is only interpretable if the two arms differ in the archive switch and
nothing else: same wall, same request/token caps, same per-request output cap, same
``unknown_usage`` policy and the same cost accounting. This file fails fast if a
later edit moves one arm without the other — which is exactly how a paired
comparison stops being a comparison.
"""

from __future__ import annotations

from typing import Any

from server.profile import PILOT_ARMS, build_profile_overrides, pilot_experiment

CHECKPOINT_PREFIX = "reading_checkpoint"

#: Frozen candidate settings (registration §1 and §17.2). Changing them after the
#: freeze would silently change what the pair measures.
FROZEN_CANDIDATE: dict[str, Any] = {
    "reading_checkpoint": "on",
    "reading_checkpoint_timeout_s": 180,
    "reading_checkpoint_attempts": 2,
    "reading_checkpoint_record_limit": 4000,
    "reading_checkpoint_max_findings": 24,
    "reading_checkpoint_archive_chars": 3000,
    "reading_checkpoint_scope_gate": "on",
}


def test_both_arms_declare_the_same_budget_and_policy() -> None:
    off = PILOT_ARMS["off"]["_pilot_budget"]
    on = PILOT_ARMS["on"]["_pilot_budget"]
    assert off == on
    assert off["requests"] == 50  # §20: raised from 40, both arms together
    assert off["prompt_tokens"] == 1_500_000
    assert off["completion_tokens"] == 100_000
    assert off["wall_s"] == 1800
    assert off["max_completion_tokens"] == 16_384
    # Approved policy (registration §17.1): identical on both arms, never one-sided.
    assert off["unknown_usage"] == "estimate"


def test_arms_differ_only_in_reading_checkpoint_settings() -> None:
    off = PILOT_ARMS["off"]
    on = PILOT_ARMS["on"]
    only_off = {key for key in off if key not in on}
    only_on = {key for key in on if key not in off}
    differing = {key for key in set(off) & set(on) if off[key] != on[key]}
    assert only_off == set()
    assert only_on == set(FROZEN_CANDIDATE) - {"reading_checkpoint"}
    # The archive switch is the whole difference between the arms.
    assert differing == {"reading_checkpoint"}
    assert not {key for key in differing if not key.startswith(CHECKPOINT_PREFIX)}
    for key, value in FROZEN_CANDIDATE.items():
        assert on[key] == value, f"frozen candidate value moved: {key}"


def test_pilot_experiment_is_keyed_on_the_session_name() -> None:
    off = pilot_experiment("pilot-off-20261117c")
    on = pilot_experiment("pilot-on-20261117d")
    assert off is not None and on is not None
    assert off["_pilot_arm"] == "off"
    assert on["_pilot_arm"] == "on"
    assert off["_pilot_budget"]["unknown_usage"] == "estimate"
    assert on["_pilot_budget"]["unknown_usage"] == "estimate"
    # Any other session keeps production behaviour untouched.
    assert pilot_experiment("default-20261117") is None
    assert pilot_experiment(None) is None


def test_built_agent_block_differs_only_in_checkpoint_settings() -> None:
    """What the worker actually hands the workflow, not just the arm table."""
    off = build_profile_overrides(
        pipeline_id="agent_team", experiment=pilot_experiment("pilot-off-20261117d")
    )["agent"]
    on = build_profile_overrides(
        pipeline_id="agent_team", experiment=pilot_experiment("pilot-on-20261117d")
    )["agent"]

    differing = {key for key in set(off) & set(on) if off[key] != on[key]}
    assert differing == {"reading_checkpoint"}
    assert off["research_wall_time_s"] == 1800
    assert on["research_wall_time_s"] == 1800
    assert off["logical_call_timeout_s"] == on["logical_call_timeout_s"] == 180
    assert off["tool_timeout_s"] == on["tool_timeout_s"] == 135
    # §20: the candidate is dispatched with the frozen 180 s shared checkpoint budget.
    assert on["reading_checkpoint_timeout_s"] == 180
    assert {key: on[key] for key in FROZEN_CANDIDATE} == FROZEN_CANDIDATE
