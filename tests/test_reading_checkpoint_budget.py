"""What a reading checkpoint must be able to prove about itself.

The 2026-11-17 run showed the limit of the previous contract: a checkpoint could
be attempted, could burn its whole stage budget, and leave no record that it ever
started. Every assertion here is about a fact that had to be *inferred* from a
time gap instead of read from the trace — outcome codes, attempt timing, budget
headroom, and whether the extraction call was paid for at all.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from frontier_agent.core.runtime.reading.contract import (
    Coverage,
    Finding,
    FindingKind,
    ReadingCheckpoint,
    SourceRange,
)
from frontier_agent.core.runtime.reading.stage import (
    ExtractionScope,
    ReadingBudget,
    ReadingCheckpointEvent,
    ReadingStage,
    ReadingStageConfig,
)

BODY = "verbatim page text " * 900  # ~18k characters

#: An extraction that parsed but produced nothing: a failed archive, not a victory.
_EMPTY = ReadingCheckpoint(checkpoint_id="", task_id="", question="q", findings=())


class _Store:
    def __init__(self, *, fail: bool = False) -> None:
        self.saved: dict[str, ReadingCheckpoint] = {}
        self.fail = fail

    def put(self, checkpoint: ReadingCheckpoint) -> None:
        if self.fail:
            raise OSError("disk full")
        self.saved[checkpoint.checkpoint_id] = checkpoint

    def get(self, checkpoint_id: str) -> ReadingCheckpoint | None:
        return self.saved.get(checkpoint_id)


def _history(bodies: int = 2) -> list[dict]:
    messages: list[dict] = [
        {"role": "system", "content": "system prompt"},
        {"role": "user", "content": "研究该公司 2025 年营收口径"},
    ]
    for index in range(bodies):
        call_id = f"c{index}"
        messages.append(
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {"name": "corpus_fetch", "arguments": "{}"},
                    }
                ],
            }
        )
        messages.append({"role": "tool", "tool_call_id": call_id, "content": BODY})
    messages.append({"role": "assistant", "content": "继续"})
    return messages


def _checkpoint(ref: str = "ce:0") -> ReadingCheckpoint:
    return ReadingCheckpoint(
        checkpoint_id="",
        task_id="",
        question="研究该公司 2025 年营收口径",
        findings=(
            Finding(
                finding_id="f1",
                kind=FindingKind.NUMBER,
                statement="营收 123 百万美元",
                evidence_refs=(ref,),
                source_id="doc-1",
                value="123",
                unit="million USD",
                period="FY2025",
            ),
        ),
        sources=(SourceRange("doc-1", "build-3", 0, 100),),
        coverage=Coverage(read_ranges=(SourceRange("doc-1", "build-3", 0, 100),)),
    )


class _Extractor:
    """A configurable extractor: what it returns, how slow, and what it reports."""

    def __init__(
        self,
        *,
        result: ReadingCheckpoint | None = None,
        exc: Exception | None = None,
        delay: float = 0.0,
        scope: ExtractionScope | None = None,
        usage: dict | None = None,
    ) -> None:
        self.calls = 0
        self.last_usage: dict | None = None
        self._result = result
        self._exc = exc
        self._delay = delay
        self._usage = usage
        if scope is not None:
            # Plain (unbound) attribute: the stage probes with getattr, so an
            # extractor without a scope attribute looks like an old extractor.
            self.scope = lambda bodies, question: scope  # type: ignore[method-assign]

    async def __call__(self, bodies, question, bounds):
        del bodies, question, bounds
        self.calls += 1
        if self._delay:
            await asyncio.sleep(self._delay)
        self.last_usage = dict(self._usage) if self._usage is not None else None
        if self._exc is not None:
            raise self._exc
        return _checkpoint() if self._result is None else self._result


def _stage(
    extractor,
    *,
    store=None,
    resolve=None,
    budget: ReadingBudget | None = None,
    **config,
) -> ReadingStage:
    options: dict = {
        "enabled": True,
        "min_body_chars": 1_000,
        "working_set_limit": 8_000,
        "keep_recent_messages": 0,
        "record_limit": 4_000,
        "max_attempts": 2,
        "total_timeout_s": 5.0,
    }
    options.update(config)
    return ReadingStage(
        extractor=extractor,
        store=store or _Store(),
        config=ReadingStageConfig(**options),
        task_id="run-1",
        resolve=resolve if resolve is not None else (lambda ref: {"ref": ref}),
        budget=budget,
    )


async def _run(stage: ReadingStage, messages=None, *, emit=None):
    return await stage.maybe_checkpoint(messages or _history(), turn=1, emit=emit)


# ── outcomes are codes, not silences ──────────────────────────────────────


@pytest.mark.asyncio
async def test_every_outcome_is_a_distinct_code() -> None:
    """Six states the operator must be able to tell apart from the trace alone."""
    seen: dict[str, tuple[str, str, bool]] = {}

    not_triggered = _stage(_Extractor(), working_set_limit=10**9)
    seen["not_triggered"] = await _code(not_triggered)

    seen["inapplicable"] = await _code(
        _stage(
            _Extractor(
                scope=ExtractionScope(
                    applicable=False,
                    reason="no_evidence_refs",
                    digest_chars=90,
                    ref_count=0,
                    body_count=2,
                )
            )
        )
    )
    seen["timeout"] = await _code(
        _stage(_Extractor(delay=5.0), total_timeout_s=0.1, max_attempts=1),
    )
    seen["validation"] = await _code(_stage(_Extractor(), resolve=lambda ref: None))
    seen["write"] = await _code(_stage(_Extractor(), store=_Store(fail=True)))
    seen["installed"] = await _code(_stage(_Extractor()))

    assert len(set(seen.values())) == len(seen), seen
    assert seen["inapplicable"][1] == "no_evidence_refs"
    assert seen["timeout"][1] == "extraction_timeout"
    assert seen["validation"][1] == "evidence_pointer_unresolved"
    assert seen["write"][1] == "archive_write_failed"
    assert seen["installed"][2] is True


async def _code(stage: ReadingStage) -> tuple[str, str, bool]:
    event = await _run(stage)
    return (event.reason, event.failure, event.installed)


@pytest.mark.asyncio
async def test_an_attempt_reports_its_start_before_the_extractor_runs() -> None:
    """A run that never returns must still leave a record behind."""
    events: list[ReadingCheckpointEvent] = []

    async def emit(event: ReadingCheckpointEvent) -> None:
        events.append(event)

    extractor = _Extractor(delay=0.05)
    await _run(_stage(extractor), emit=emit)

    assert [event.phase for event in events] == ["start", "end"]
    started = events[0]
    assert started.triggered is True
    assert started.body_count == 2
    assert started.attempts == ()
    ended = events[1]
    assert ended.installed is True
    assert ended.attempts[0].outcome == "installed"
    assert ended.attempts[0].duration_s >= 0.0


@pytest.mark.asyncio
async def test_a_decline_reports_nothing_as_started() -> None:
    events: list[ReadingCheckpointEvent] = []

    async def emit(event: ReadingCheckpointEvent) -> None:
        events.append(event)

    await _run(_stage(_Extractor(), working_set_limit=10**9), emit=emit)

    assert [event.phase for event in events] == ["end"]
    assert events[0].triggered is False


# ── cost is measured, and unknown is not zero ─────────────────────────────


@pytest.mark.asyncio
async def test_usage_is_recorded_when_the_extractor_reports_it() -> None:
    extractor = _Extractor(usage={"prompt_tokens": 900, "completion_tokens": 100})

    event = await _run(_stage(extractor))

    assert event.usage_known is True
    assert event.usage == {
        "prompt_tokens": 900,
        "completion_tokens": 100,
        "total_tokens": 1_000,
        "cache_read_tokens": 0,
    }


@pytest.mark.asyncio
async def test_missing_usage_is_unknown_not_zero() -> None:
    event = await _run(_stage(_Extractor()))

    assert event.installed is True
    assert event.usage is None
    assert event.usage_known is False


# ── budget: optional work never buys the answer ───────────────────────────


@pytest.mark.asyncio
async def test_a_nearly_exhausted_turn_skips_optional_archiving() -> None:
    extractor = _Extractor()

    event = await _run(
        _stage(extractor, budget=ReadingBudget(remaining_s=lambda: 44.0)),
    )

    assert extractor.calls == 0
    assert event.triggered is False
    assert event.reason == "skipped_insufficient_budget"
    assert event.installed is False
    assert event.remaining_budget_s == 44.0


@pytest.mark.asyncio
async def test_the_delivery_reserve_is_subtracted_before_pricing() -> None:
    """200s left minus a 180s delivery reserve is not a 200s budget."""
    extractor = _Extractor()

    event = await _run(
        _stage(
            extractor,
            budget=ReadingBudget(
                remaining_s=lambda: 200.0,
                delivery_reserve_s=lambda: 180.0,
            ),
        ),
    )

    assert extractor.calls == 0
    assert event.reason == "skipped_insufficient_budget"
    assert event.delivery_reserve_s == 180.0


@pytest.mark.asyncio
async def test_a_checkpoint_cannot_spend_past_the_reserve() -> None:
    """With 120s usable and a 60s stage budget the attempt is capped at 120s.

    The cap is asserted through the deadline the stage hands the extractor: a slow
    extractor must be cancelled before the reserve is touched.
    """
    extractor = _Extractor(delay=5.0)

    event = await _run(
        _stage(
            extractor,
            total_timeout_s=60.0,
            max_attempts=1,
            budget=ReadingBudget(
                remaining_s=lambda: 300.0,
                delivery_reserve_s=lambda: 180.0,
            ),
        ),
    )

    assert extractor.calls == 1
    # 5s extractor against a 60s cap: it succeeded, so the cap was not the binding
    # constraint here — what matters is that the reserve never became spendable.
    assert event.remaining_budget_s == 300.0
    assert event.delivery_reserve_s == 180.0


@pytest.mark.asyncio
async def test_a_second_attempt_is_recorded_as_not_started_without_budget() -> None:
    """"Two attempts configured" is not "two attempts afforded".

    ``total_timeout_s`` prices one attempt, so the stage ceiling is twice that; the
    caller's *usable* budget is what decides. 0.12s in total buys one attempt and
    leaves less than the retry floor.
    """
    extractor = _Extractor(delay=0.05, result=_EMPTY)

    event = await _run(
        _stage(
            extractor,
            total_timeout_s=0.25,
            max_attempts=2,
            min_attempt_s=5.0,
            min_remaining_budget_s=0.0,
            budget=ReadingBudget(remaining_s=lambda: 0.12),
        ),
    )

    outcomes = [attempt.outcome for attempt in event.attempts]
    assert "not_started" in outcomes
    assert extractor.calls == 1, "a retry must not be started it cannot afford"
    assert event.failure == "insufficient_attempt_budget"
    assert event.installed is False


@pytest.mark.asyncio
async def test_the_stage_budget_prices_one_attempt_not_all_of_them() -> None:
    """Two attempts each fit the per-attempt budget.

    The old arithmetic made this impossible by construction: a 0.25s window shared
    by two attempts left 0.05s for the retry, so a configured second attempt could
    never run after a call that used most of the window. That is the shape of a
    180s window against a ~120s extraction.
    """
    extractor = _Extractor(delay=0.2, result=_EMPTY)

    event = await _run(
        _stage(extractor, total_timeout_s=0.25, max_attempts=2, min_attempt_s=0.01),
    )

    assert extractor.calls == 2
    assert [attempt.outcome for attempt in event.attempts] == ["empty_record", "empty_record"]


@pytest.mark.asyncio
async def test_a_retry_is_not_started_when_it_cannot_cover_the_measured_cost() -> None:
    """The 2026-11-18 finance member, replayed with an exact clock.

    Attempt 1 spent 151.8s; 28.2s of the ceiling were left. Starting the retry
    would pay for a timeout that was visible in advance, so it is recorded as not
    started instead.
    """
    now = 0.0

    class _SlowEmpty:
        calls = 0

        async def __call__(self, bodies, question, bounds):
            del bodies, question, bounds
            nonlocal now
            self.calls += 1
            now += 151.8
            return _EMPTY

    extractor = _SlowEmpty()
    stage = ReadingStage(
        extractor=extractor,
        store=_Store(),
        config=ReadingStageConfig(
            enabled=True,
            min_body_chars=1_000,
            working_set_limit=8_000,
            keep_recent_messages=0,
            max_attempts=2,
            total_timeout_s=180.0,
        ),
        task_id="run-1",
        resolve=lambda ref: {"ref": ref},
        clock=lambda: now,
        budget=ReadingBudget(remaining_s=lambda: 208.2),
    )

    event = await _run(stage)

    assert extractor.calls == 1, "a retry that cannot finish must not be paid for"
    assert event.attempts[0].outcome == "empty_record"
    assert event.attempts[1].outcome == "not_started"
    assert event.attempts[1].detail == "56.40s left < attempt floor 75.90s"
    assert event.failure == "insufficient_attempt_budget"
    assert event.installed is False


@pytest.mark.asyncio
async def test_the_same_unchanged_input_is_not_paid_for_twice() -> None:
    """A timeout on unchanged bodies must not repeat every later turn."""
    extractor = _Extractor(delay=5.0)
    stage = _stage(extractor, total_timeout_s=0.1, max_attempts=1)
    messages = _history()

    first = await _run(stage, messages)
    second = await _run(stage, messages)

    assert first.failure == "extraction_timeout"
    assert extractor.calls == 1
    assert second.reason == "unchanged_input_after_failure"
    assert second.failure == "extraction_timeout"
    assert second.triggered is False


@pytest.mark.asyncio
async def test_new_bodies_clear_the_unchanged_input_memo() -> None:
    extractor = _Extractor(delay=5.0)
    stage = _stage(extractor, total_timeout_s=0.1, max_attempts=1)
    messages = _history()

    await _run(stage, messages)
    assert extractor.calls == 1

    # One more page, consumed by a following assistant message.
    call_id = "c9"
    messages.insert(
        -1,
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {"name": "corpus_fetch", "arguments": "{}"},
                }
            ],
        },
    )
    messages.insert(
        -1, {"role": "tool", "tool_call_id": call_id, "content": BODY},
    )

    second = await _run(stage, messages)

    assert extractor.calls == 2
    assert second.reason == "checkpoint_failed"


# ── the trace and the meter ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_trajectory_records_start_and_end_without_bodies(tmp_path) -> None:
    from frontier_agent.components.observers.trajectory import TrajectoryFileObserver
    from frontier_agent.core.loop_types import LoopConfig

    events: list[ReadingCheckpointEvent] = []

    async def emit(event: ReadingCheckpointEvent) -> None:
        events.append(event)

    await _run(_stage(_Extractor(usage={"prompt_tokens": 7, "completion_tokens": 3})), emit=emit)

    observer = TrajectoryFileObserver(
        tmp_path, filename="agent", formats=["jsonl"],
    )
    await observer.on_loop_start(LoopConfig(task_id="t", role_id="r"))
    for event in events:
        await observer.on_reading_checkpoint(event)
    await observer.on_loop_end(
        type(
            "Result",
            (),
            {"turns_used": 1, "tool_calls_count": 0, "stopped_by": "final_answer"},
        )(),
    )

    rows = [
        json.loads(line)
        for line in (tmp_path / "agent.jsonl").read_text().splitlines()
        if line.strip()
    ]
    reading = [row for row in rows if row["t"] == "reading_checkpoint"]
    assert [row["phase"] for row in reading] == ["start", "end"]
    assert reading[0]["digest_chars"] is None
    assert reading[1]["installed"] is True
    assert reading[1]["usage"] == {
        "prompt_tokens": 7,
        "completion_tokens": 3,
        "total_tokens": 10,
        "cache_read_tokens": 0,
    }
    blob = json.dumps(rows, ensure_ascii=False)
    assert "verbatim page text" not in blob, "the trace must not copy the bodies"


def test_the_run_meter_reports_extraction_cost_separately() -> None:
    from server.usage import reading_checkpoint_stats

    stats = reading_checkpoint_stats(
        [
            {"t": "reading_checkpoint", "phase": "start", "triggered": True},
            {
                "t": "reading_checkpoint",
                "phase": "end",
                "triggered": True,
                "installed": False,
                "reason": "checkpoint_failed",
                "failure": "extraction_timeout",
                "attempts": [{"outcome": "extractor_timeout"}],
                "usage": None,
                "usage_known": False,
            },
            {
                "t": "reading_checkpoint",
                "phase": "end",
                "triggered": True,
                "installed": True,
                "reason": "checkpoint_installed",
                "attempts": [{"outcome": "installed"}],
                "usage": {"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
                "usage_known": True,
            },
            {
                "t": "reading_checkpoint",
                "phase": "end",
                "triggered": False,
                "reason": "skipped_insufficient_budget",
            },
        ]
    )

    assert stats["events"] == 3
    assert stats["triggered"] == 2
    assert stats["installed"] == 1
    assert stats["extractor_timeouts"] == 1
    assert stats["skipped"] == 1
    assert stats["prompt_tokens"] == 100
    assert stats["unknown_usage_events"] == 1
    assert stats["included_in_run_totals"] is False
