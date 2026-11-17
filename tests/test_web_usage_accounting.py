"""Web usage accounting: a stopped run must not report zero cost.

Field evidence (run ``7efc0673…``): the guard settled a real request at 592/196, the
provider billed it, and the run row still said ``prompt_tokens=0 / llm_calls=0``.
Two independent causes, both fixed here:

* the 592/196 came from ``research_intake`` — a real billed call whose trajectory
  file sits beside the replay sources, so the aggregate never saw it;
* the only recorded attempt was the *next* request, refused before it was sent — it
  was then reported as an unmetered call.

Fixed responses only: no network, no model.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from frontier_agent.infra import pilot_budget
from server import usage as usage_module
from server.cache_metrics import cache_attempt_stats


def _write(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records),
        encoding="utf-8",
    )


def _run_dir(tmp_path: Path, main: list[dict[str, Any]], intake: list[dict[str, Any]] | None) -> Path:
    root = tmp_path / "run" / "agent" / "trajectories"
    _write(root / "react_agent.jsonl", main)
    if intake is not None:
        _write(root / "research_intake.jsonl", intake)
    return tmp_path


def _aggregate(monkeypatch: pytest.MonkeyPatch, run_dir: Path, main: list[dict[str, Any]]) -> dict:
    monkeypatch.setattr(usage_module, "run_dir_for", lambda _run_id: run_dir)
    monkeypatch.setattr(usage_module, "trajectory_records", lambda _run_id, after_line=0: list(main))
    return usage_module.usage_for_run("run-under-test")


INTAKE_LLM = {
    "t": "llm",
    "turn": 1,
    "content": '{"decision":"ready"}',
    "usage": {"prompt_tokens": 592, "completion_tokens": 196, "total_tokens": 788},
}
INTAKE_END = {"t": "end", "turns": 1, "stopped_by": "no_tool"}


def test_auxiliary_call_is_part_of_the_run_total(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    main = [
        {"t": "llm", "turn": 1, "content": "答", "usage": {"prompt_tokens": 100, "completion_tokens": 10}},
        {"t": "end", "turns": 1},
    ]
    run_dir = _run_dir(tmp_path, main, [{"t": "start"}, INTAKE_LLM, INTAKE_END])
    payload = _aggregate(monkeypatch, run_dir, main)

    assert payload["prompt_tokens"] == 692  # 100 + 592, counted once each
    assert payload["completion_tokens"] == 206
    assert payload["llm_calls"] == 2
    assert payload["auxiliary"]["sources"] == ["research_intake.jsonl"]
    assert payload["auxiliary"]["prompt_tokens"] == 592
    assert payload["auxiliary"]["included_in_run_totals"] is True
    assert payload["status"] == "complete"


def test_budget_stop_after_auxiliary_call_keeps_its_usage(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The exact failure shape: main turn interrupted, intake already billed."""
    main = [
        {"t": "start"},
        {"t": "attempt", "turn": 1, "attempt_index": 1, "phase": "started"},
        {
            "t": "attempt", "turn": 1, "attempt_index": 1, "phase": "finished",
            "outcome": "failed", "reason": "budget_stop", "sent": False, "duration_ms": 6,
        },
        {"t": "end"},
    ]
    run_dir = _run_dir(tmp_path, main, [{"t": "start"}, INTAKE_LLM, INTAKE_END])
    payload = _aggregate(monkeypatch, run_dir, main)

    assert payload["prompt_tokens"] == 592  # not erased by the stop
    assert payload["completion_tokens"] == 196
    assert payload["llm_calls"] == 1
    assert payload["unmetered_calls"] == 0
    assert payload["status"] == "complete"


def test_sent_call_without_usage_is_still_reported_as_unmetered(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    main = [{"t": "llm", "turn": 1, "content": "答"}, {"t": "end"}]
    run_dir = _run_dir(tmp_path, main, None)
    payload = _aggregate(monkeypatch, run_dir, main)

    assert payload["prompt_tokens"] == 0
    assert payload["unmetered_calls"] == 1
    assert payload["status"] == "partial"  # unknown, never silently "0 / complete"


def test_refused_attempt_is_not_an_unmetered_call(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    records = [
        {"t": "attempt", "attempt_id": "a1", "attempt_index": 1, "phase": "started"},
        {
            "t": "attempt", "attempt_id": "a1", "attempt_index": 1, "phase": "finished",
            "outcome": "failed", "reason": "budget_stop", "sent": False,
        },
        {
            "t": "attempt", "attempt_id": "a2", "attempt_index": 1, "phase": "finished",
            "outcome": "accepted", "sent": True,
            # A real attempt usage carries the normalized cache fields; without them
            # the bucketing cannot tell a hit rate from an unknown, so it says unknown.
            "usage": {"prompt_tokens": 10, "completion_tokens": 2, "cache_read_tokens": 0},
        },
    ]
    stats = cache_attempt_stats(records)

    assert stats["refused_before_send"] == 1
    assert stats["all_attempts"]["attempts"] == 1  # only the sent request is a call
    assert stats["all_attempts"]["unknown_usage_attempts"] == 0
    assert stats["all_attempts"]["known_prompt_tokens"] == 10


def _arm(monkeypatch: pytest.MonkeyPatch, **extra: Any) -> pilot_budget.PilotBudget:
    spec = {"requests": 6, "prompt_tokens": 120_000, "completion_tokens": 8_000, "wall_s": 180}
    spec.update(extra)
    monkeypatch.setattr(pilot_budget, "_BUDGET", None)
    budget = pilot_budget.arm(spec)
    return budget


async def test_per_request_cap_is_clamped_before_send(monkeypatch: pytest.MonkeyPatch) -> None:
    """The arm was approved for 4,096; the chain inherits 16,384."""
    budget = _arm(monkeypatch, max_completion_tokens=4_096)
    seen: dict[str, Any] = {}

    async def create(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        return SimpleNamespace(usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5))

    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    pilot_budget.install(client)
    await client.chat.completions.create(
        messages=[{"role": "user", "content": "hi"}], max_completion_tokens=16_384
    )

    assert seen["max_completion_tokens"] == 4_096
    assert budget.requests_sent == 1
    assert budget.completion_settled == 5
    assert budget.completion_reserved == 0


def test_legacy_budget_stop_row_counts_as_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Rows written before the ``sent`` flag: ``budget_stop`` already proves it."""
    records = [
        {
            "t": "attempt", "attempt_id": "old", "attempt_index": 1, "phase": "finished",
            "outcome": "failed", "reason": "budget_stop", "duration_ms": 6,
        },
        {
            "t": "attempt", "attempt_id": "ok", "attempt_index": 1, "phase": "finished",
            "outcome": "accepted",
            "usage": {"prompt_tokens": 592, "completion_tokens": 196, "cache_read_tokens": 512},
        },
    ]
    stats = cache_attempt_stats(records)

    assert stats["refused_before_send"] == 1
    assert stats["all_attempts"]["unknown_usage_attempts"] == 0
    assert stats["status"] == "complete"
