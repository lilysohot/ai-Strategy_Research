"""The evidence-boundary notice is two blocks, and they age independently.

The standing rules never change; the state JSON does. Re-sending both whenever the
state moves is what made this notice cost its full length on every change, so the
rules are abbreviated as soon as they are provably still readable — and re-sent in
full the moment they are not.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import workflows.agent_team.observers.evidence_boundary as eb
from frontier_agent.core.loop_types import TurnContext


def _context(messages: list[dict[str, Any]]) -> TurnContext:
    return TurnContext(
        turn=3,
        max_turns=20,
        task_id="run",
        role_id="main",
        ai_text="",
        thinking="",
        tool_calls=[],
        messages=messages,
        usage=None,
        metadata={},
    )


def _inject(monkeypatch: Any, *, status: str, messages: list[dict[str, Any]]) -> str | None:
    jobs = [{"job_id": "job-1", "status": "completed", "coverage_status": "complete"}]
    monkeypatch.setattr(eb, "registry", SimpleNamespace(get_optional=lambda _kind: object()))
    monkeypatch.setattr(eb, "snapshot_job_outcomes", lambda bus, task_id: jobs)
    monkeypatch.setattr(eb, "snapshot_tasks", lambda task_id: [])
    monkeypatch.setattr(eb, "project_checks", lambda outcomes: {"status": status})

    observer = eb.EvidenceBoundaryObserver()
    intervention = asyncio.run(observer.on_before_llm(_context(messages)))
    if intervention is None:
        return None
    return intervention.inject_messages[0]


def test_the_first_injection_carries_the_full_rules(monkeypatch: Any) -> None:
    notice = _inject(monkeypatch, status="unchecked", messages=[])

    assert notice is not None
    assert notice.startswith(eb._RULES)


def test_a_new_state_reuses_the_rules_by_reference(monkeypatch: Any) -> None:
    first = _inject(monkeypatch, status="unchecked", messages=[])
    assert first is not None

    second = _inject(
        monkeypatch,
        status="partial",
        messages=[{"role": "user", "content": first}],
    )

    assert second is not None
    assert second.startswith(eb._RULES_REF)
    assert eb._RULES not in second
    assert '"verification_status": "partial"' in second


def test_an_unchanged_state_is_not_reinjected(monkeypatch: Any) -> None:
    first = _inject(monkeypatch, status="unchecked", messages=[])
    assert first is not None
    referenced = _inject(
        monkeypatch, status="partial", messages=[{"role": "user", "content": first}]
    )
    assert referenced is not None

    again = _inject(
        monkeypatch,
        status="partial",
        messages=[
            {"role": "user", "content": first},
            {"role": "user", "content": referenced},
        ],
    )

    assert again is None


def test_rules_that_were_dropped_are_resent_in_full(monkeypatch: Any) -> None:
    """Only the previous state survived a rewrite: nothing licenses a reference."""
    first = _inject(monkeypatch, status="unchecked", messages=[])
    assert first is not None
    state_only = first.split("\n", 1)[1]

    notice = _inject(
        monkeypatch,
        status="partial",
        messages=[{"role": "user", "content": state_only}],
    )

    assert notice is not None
    assert notice.startswith(eb._RULES)


def test_the_same_state_without_any_rules_is_reinjected(monkeypatch: Any) -> None:
    first = _inject(monkeypatch, status="unchecked", messages=[])
    assert first is not None
    state_only = first.split("\n", 1)[1]

    notice = _inject(
        monkeypatch,
        status="unchecked",
        messages=[{"role": "user", "content": state_only}],
    )

    assert notice is not None
    assert notice.startswith(eb._RULES)


def test_a_reference_alone_never_proves_the_rules_survive(monkeypatch: Any) -> None:
    """The ref points at a block; it cannot stand in for it after a rewrite."""
    first = _inject(monkeypatch, status="unchecked", messages=[])
    assert first is not None
    state = first.split("\n", 1)[1]
    reference_only = eb._RULES_REF + "\n" + state

    notice = _inject(
        monkeypatch,
        status="unchecked",
        messages=[{"role": "user", "content": reference_only}],
    )

    assert notice is not None
    assert notice.startswith(eb._RULES)
    assert notice.endswith(state)


def test_state_a_b_a_is_not_swallowed(monkeypatch: Any) -> None:
    """The older A is still in the history; the latest notice says B."""
    a = _inject(monkeypatch, status="unchecked", messages=[])
    assert a is not None
    b = _inject(monkeypatch, status="partial", messages=[{"role": "user", "content": a}])
    assert b is not None

    back_to_a = _inject(
        monkeypatch,
        status="unchecked",
        messages=[
            {"role": "user", "content": a},
            {"role": "user", "content": b},
        ],
    )

    assert back_to_a is not None
    assert back_to_a.split("\n", 1)[1] == a.split("\n", 1)[1]
