"""Archiving a read body is allowed only after its replacement is durable.

These tests are organised around the two ways this mechanism can hurt: it can
retire a body and then fail to keep the record (evidence gone, nothing to show),
or it can churn the history every turn (prefix cache destroyed, cost up, nothing
gained). The first is tested by making every failure point fail and asserting the
history is byte-identical; the second by running the stage twice.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import BaseObserver, LoopConfig
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.runtime.reading.contract import (
    Coverage,
    Finding,
    FindingKind,
    ReadingCheckpoint,
    SourceRange,
)
from frontier_agent.core.runtime.reading.stage import (
    RETIRED_MARKER,
    ReadingCheckpointEvent,
    ReadingStage,
    ReadingStageConfig,
    is_retired_body,
)
from frontier_agent.core.tool import tool

BODY = "verbatim page text " * 900  # ~18k characters


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


def _history(bodies: int = 2, filler: int = 0, unconsumed: int = 0) -> list[dict]:
    """A history at a turn boundary.

    It ends with an assistant message, because that is what makes the preceding
    tool results *consumed*: the stage decides eligibility by position, so a
    fixture that ends on a tool result would describe a turn in flight.
    ``unconsumed`` appends results that arrive after that assistant message.
    """
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
    for index in range(filler):
        messages.append({"role": "user", "content": f"filler {index}"})
    for index in range(unconsumed):
        call_id = f"u{index}"
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
    return messages


def _checkpoint(*, statement_chars: int = 20, findings: int = 2) -> ReadingCheckpoint:
    return ReadingCheckpoint(
        checkpoint_id="",
        task_id="",
        question="研究该公司 2025 年营收口径",
        findings=tuple(
            Finding(
                finding_id=f"f{index}",
                kind=FindingKind.NUMBER,
                statement="x" * statement_chars,
                evidence_refs=(f"ce:{index}",),
                source_id="doc-1",
                value="123",
                unit="million USD",
                period="FY2025",
            )
            for index in range(findings)
        ),
        sources=(SourceRange("doc-1", "build-3", 0, 100),),
        coverage=Coverage(
            read_ranges=(SourceRange("doc-1", "build-3", 0, 100),),
            unread_ranges=(SourceRange("doc-1", "build-3", 100, 400),),
        ),
    )


def _stage(
    extractor,
    *,
    store=None,
    resolve=None,
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
    )


async def _ok_extractor(bodies, question, bounds):
    return _checkpoint()


def test_a_disabled_stage_touches_nothing() -> None:
    messages = _history()
    before = json.dumps(messages, ensure_ascii=False)
    stage = _stage(_ok_extractor, enabled=False)

    event = asyncio.run(stage.maybe_checkpoint(messages))

    assert event.triggered is False
    assert event.reason == "disabled"
    assert json.dumps(messages, ensure_ascii=False) == before


def test_below_the_working_set_limit_nothing_is_archived() -> None:
    messages = _history(bodies=1)
    stage = _stage(_ok_extractor, working_set_limit=10_000_000)

    event = asyncio.run(stage.maybe_checkpoint(messages))

    assert event.reason == "under_working_set_limit"
    assert not any(is_retired_body(m["content"]) for m in messages if m["role"] == "tool")


def test_an_installed_checkpoint_retires_bodies_and_appends_the_archive() -> None:
    messages = _history(bodies=2)
    store = _Store()
    stage = _stage(_ok_extractor, store=store)

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=4))

    assert event.installed is True
    assert event.reason == "checkpoint_installed"
    assert len(event.retired_calls) == 2
    assert event.working_set_after < event.working_set_before
    assert store.saved, "the record must be durable before bodies retire"

    tools = [m for m in messages if m["role"] == "tool"]
    assert all(is_retired_body(m["content"]) for m in tools)
    assert all(RETIRED_MARKER in m["content"] for m in tools)
    # Tool pairing survives: each retired message keeps its call id.
    assert [m["tool_call_id"] for m in tools] == ["c0", "c1"]
    archive = messages[-1]
    assert archive["role"] == "user"
    assert "研究归档" in archive["content"]
    assert "ce:0" in archive["content"]
    assert "未读" in archive["content"]


def test_an_empty_record_carries_the_extractor_reason() -> None:
    """The 2026-11-18 attempt 1 recorded ``empty_record`` with no reason at all.

    Without one, "the model was cut off" and "the citations all missed" are
    indistinguishable, and only the first is a budget question.
    """

    class _Diagnosed:
        def __init__(self) -> None:
            self.last_diagnostics = {
                "end_reason": "parse_failed",
                "finish_reason": "stop",
                "content_chars": 812,
                "reasoning_chars": 0,
                "parse": "json_error@204",
                "raw_findings": 0,
                "kept": 0,
                "drops": {},
                "usage": {"completion_tokens": 1024, "prompt_tokens": 27_610},
            }

        async def __call__(self, bodies, question, bounds):
            del bodies, question, bounds
            return _checkpoint(findings=0)

    messages = _history()
    stage = _stage(_Diagnosed())

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=1))

    assert event.failure == "empty_record"
    detail = event.attempts[0].detail
    assert "end=parse_failed" in detail
    assert "finish=stop" in detail
    assert "content=812" in detail
    assert "parse=json_error@204" in detail
    assert "tokens=1024/27610" in detail
    assert len(detail) <= 200


def test_an_extractor_without_diagnostics_leaves_the_cause_unknown() -> None:
    """Silence is the honest record when the extractor cannot say why."""

    async def _empty_extractor(bodies, question, bounds):
        del bodies, question, bounds
        return _checkpoint(findings=0)

    messages = _history()
    stage = _stage(_empty_extractor)

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=1))

    assert event.failure == "empty_record"
    assert event.attempts[0].detail == ""


def test_an_incomplete_checkpoint_without_ranges_still_says_so() -> None:
    """The 2026-11-18 record: ``complete=false`` with no range and no limitation.

    That combination used to render nothing, so the archive read exactly like full
    coverage. The line below is derived from the field itself — it costs no model
    output and cannot be forgotten.
    """
    from dataclasses import replace

    incomplete = replace(
        _checkpoint(), coverage=Coverage(read_ranges=(SourceRange("doc-1", "build-3", 0, 100),))
    )

    async def extractor(bodies, question, bounds):
        del bodies, question, bounds
        return incomplete

    messages = _history()
    stage = _stage(extractor)

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=1))
    archive = messages[-1]["content"]

    assert event.installed is True
    assert "本检查点覆盖不完整：未读范围未明确" in archive
    assert "本检查点未读" not in archive, "there is no range to name"
    assert "限制：" not in archive


def test_a_named_unread_range_is_preferred_over_the_generic_warning() -> None:
    """A range is better information than "unknown", so it replaces the warning."""
    messages = _history()
    stage = _stage(_ok_extractor)

    asyncio.run(stage.maybe_checkpoint(messages, turn=1))
    archive = messages[-1]["content"]

    assert "本检查点未读：doc-1[100-400]@vbuild-3" in archive
    assert "未读范围未明确" not in archive


def test_a_complete_checkpoint_makes_no_coverage_claim() -> None:
    """Nothing is said when there is nothing to disclose — no noise per archive."""
    from dataclasses import replace

    complete = replace(
        _checkpoint(),
        coverage=Coverage(
            read_ranges=(SourceRange("doc-1", "build-3", 0, 100),),
            complete=True,
        ),
    )

    async def extractor(bodies, question, bounds):
        del bodies, question, bounds
        return complete

    messages = _history()
    stage = _stage(extractor)

    asyncio.run(stage.maybe_checkpoint(messages, turn=1))
    archive = messages[-1]["content"]

    assert "本检查点覆盖不完整" not in archive
    assert "本检查点未读" not in archive


def test_an_earlier_checkpoint_is_never_rewritten_by_a_later_one() -> None:
    """Prefix stability under a *second* checkpoint.

    Appending is fine; rewriting is not. A later checkpoint must leave the first
    one's marker and rollup byte-identical, or every turn invalidates the cache
    from the first archived page onward.
    """
    messages = _history(bodies=2)
    stage = _stage(_ok_extractor)

    asyncio.run(stage.maybe_checkpoint(messages, turn=1))
    first_markers = [m["content"] for m in messages if m["role"] == "tool"]
    first_archive = messages[-1]["content"]

    # A new turn arrives and its body is consumed by a following assistant turn.
    messages.append(
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "c9",
                    "type": "function",
                    "function": {"name": "corpus_fetch", "arguments": "{}"},
                }
            ],
        }
    )
    messages.append({"role": "tool", "tool_call_id": "c9", "content": BODY})
    messages.append({"role": "assistant", "content": "继续"})

    second = asyncio.run(stage.maybe_checkpoint(messages, turn=2))

    assert second.installed is True
    assert second.checkpoint_id != "ck:run-1/001", "each checkpoint needs its own id"
    retired = [m["content"] for m in messages if m["role"] == "tool"][:2]
    assert retired == first_markers, "a later checkpoint rewrote an earlier marker"
    archives = [
        m["content"] for m in messages if m["role"] == "user" and "研究归档" in m["content"]
    ]
    assert archives[0] == first_archive
    assert len(archives) == 2, "each checkpoint appends exactly one rollup"


def test_a_second_run_retires_nothing_and_appends_no_second_archive() -> None:
    """The prefix-cache requirement: a checkpoint is applied once. Re-running the
    stage must not rewrite a retired body or add another rollup."""
    messages = _history(bodies=2)
    stage = _stage(_ok_extractor)

    asyncio.run(stage.maybe_checkpoint(messages, turn=1))
    snapshot = json.dumps(messages, ensure_ascii=False)
    second = asyncio.run(stage.maybe_checkpoint(messages, turn=2))

    assert second.installed is False
    assert second.reason == "no_retirable_bodies"
    assert json.dumps(messages, ensure_ascii=False) == snapshot


def test_a_result_the_model_has_not_seen_is_never_retired() -> None:
    """Results appended after the last assistant message arrive in the turn being
    ended: nothing has read them, so nothing may archive them."""
    messages = _history(bodies=2, unconsumed=1)
    stage = _stage(_ok_extractor, keep_recent_messages=0)

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=3))

    assert event.installed is True
    tools = [m for m in messages if m["role"] == "tool"]
    assert is_retired_body(tools[0]["content"])
    assert is_retired_body(tools[1]["content"])
    assert not is_retired_body(tools[2]["content"])
    assert event.retired_calls == ("c0", "c1")


def test_the_keep_recent_margin_leaves_the_tail_alone() -> None:
    """An extra margin for callers that want more history untouched. The last
    tool message here IS consumed, so only the margin protects it."""
    messages = _history(bodies=3)
    stage = _stage(_ok_extractor, keep_recent_messages=3)

    asyncio.run(stage.maybe_checkpoint(messages, turn=3))

    tools = [m for m in messages if m["role"] == "tool"]
    assert not is_retired_body(tools[-1]["content"])


@pytest.mark.parametrize(
    "failure",
    ["raises", "timeout", "empty", "unresolvable_ref", "write_fails"],
)
def test_every_failure_leaves_the_history_byte_identical(failure: str) -> None:
    """The one outcome that must never happen: bodies gone, archive unusable."""
    messages = _history(bodies=2)
    before = json.dumps(messages, ensure_ascii=False)

    async def raising(bodies, question, bounds):
        raise RuntimeError("provider exploded")

    async def hanging(bodies, question, bounds):
        await asyncio.sleep(30)
        return _checkpoint()

    async def empty(bodies, question, bounds):
        return ReadingCheckpoint(
            checkpoint_id="",
            task_id="",
            question="q",
            findings=(),
            sources=(),
        )

    extractor = {
        "raises": raising,
        "timeout": hanging,
        "empty": empty,
        "unresolvable_ref": _ok_extractor,
        "write_fails": _ok_extractor,
    }[failure]
    kwargs: dict = {}
    if failure == "unresolvable_ref":
        kwargs["resolve"] = lambda ref: None
    if failure == "write_fails":
        kwargs["store"] = _Store(fail=True)
    stage = _stage(extractor, total_timeout_s=0.15, max_attempts=2, **kwargs)

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=5))

    assert event.installed is False
    assert event.failure
    assert json.dumps(messages, ensure_ascii=False) == before


def test_an_unresolvable_reference_names_the_reason() -> None:
    stage = _stage(_ok_extractor, resolve=lambda ref: None)

    event = asyncio.run(stage.maybe_checkpoint(_history(), turn=1))

    assert event.failure == "evidence_pointer_unresolved"


def test_an_over_budget_record_is_retried_narrower_rather_than_trimmed() -> None:
    """Trimming findings is how a fact disappears with nobody deciding to drop it.
    The stage narrows the bound and lets the extractor produce a smaller record."""
    seen: list[int] = []

    async def too_big(bodies, question, bounds):
        seen.append(bounds.record_limit)
        return _checkpoint(statement_chars=6_000)

    stage = _stage(too_big, record_limit=1_000)

    event = asyncio.run(stage.maybe_checkpoint(_history(), turn=1))

    assert event.installed is False
    assert event.failure == "record_over_budget"
    assert seen[0] == 1_000
    assert seen[1] < seen[0], "the retry must be bounded tighter, not looser"


def test_an_oversized_archive_falls_back_to_an_index_and_says_so() -> None:
    """220 sits between this fixture's index floor (201) and full render (244)."""
    messages = _history()
    stage = _stage(_ok_extractor, archive_max_chars=220)

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=1))

    assert event.installed is True
    assert event.index_only is True
    assert "仅保留索引" in messages[-1]["content"]


def _twin_checkpoint() -> ReadingCheckpoint:
    """Two findings whose discriminating clause is NOT at the start.

    A prefix-only cue would render both as ``- f1 fact 数据中心订单`` and leave a
    reader unable to choose; this fixture is what makes the cue test meaningful.
    """
    ref_a = "ce:" + "1" * 32
    ref_b = "ce:" + "2" * 32
    ref_c = "ce:" + "3" * 32
    # Long enough that the full rendering and the index-only rendering are far
    # apart; otherwise the budget window between them is too narrow to test.
    filler = "报告其余段落重复描述装机量、服务合同期限、订单转化节奏与交付排期，此处不重复叙述。"
    return ReadingCheckpoint(
        checkpoint_id="ck:test/twins",
        task_id="",
        question="数据中心订单的定价风险",
        findings=(
            Finding(
                finding_id="f1",
                kind=FindingKind.COUNTER_EVIDENCE,
                statement=(
                    "看空者认为需求被提前透支，订单可能回归常态，"
                    f"部分订单存在溢价但未套用于全部组合。{filler}"
                ),
                evidence_refs=(ref_a,),
            ),
            Finding(
                finding_id="f2",
                kind=FindingKind.COUNTER_EVIDENCE,
                statement=(
                    "看空者认为随着产能扩张利用率可能下降且定价趋弱，"
                    f"Liberty 同时向两家下单，供给落地节奏仍是关键变量。{filler}"
                ),
                evidence_refs=(ref_b, ref_c),
            ),
        ),
        sources=(SourceRange("doc-1", "build-3", 0, 100),),
        coverage=Coverage(read_ranges=(SourceRange("doc-1", "build-3", 0, 100),)),
    )


def test_the_overflow_index_keeps_a_disambiguating_cue_and_every_address() -> None:
    from frontier_agent.core.runtime.reading.stage import _render_archive

    checkpoint = _twin_checkpoint()
    full, full_is_index = _render_archive(checkpoint, max_chars=10_000)
    assert full_is_index is False
    # Just under the full rendering: overflow is forced without starving the cues.
    cap = len(full) - 50
    text, index_only = _render_archive(checkpoint, max_chars=cap)

    assert index_only is True
    assert len(text) <= cap, "a hint that overflows its own cap is still over its cap"
    # Addresses are the only thing a tool can resolve, so every ref must survive.
    for finding in checkpoint.findings:
        for ref in finding.evidence_refs:
            assert ref in text
    # Cues must be verbatim excerpts and must differ between the findings.
    lines = [line for line in text.splitlines() if line.startswith("- f")]
    assert len(lines) == len(checkpoint.findings)
    cues = [line.split(" refs: ")[0] for line in lines]
    assert len(set(cues)) == len(cues)
    for cue in cues:
        assert cue[-1] in "。…" , "a truncated excerpt must show it was cut"
    assert any("套用于全部" in cue for cue in cues), "the distinguishing clause must survive the cut"


def _wide_checkpoint() -> ReadingCheckpoint:
    """24 findings x 3 refs: inside the record budget, outside the archive budget.

    Measured on the pre-guard code: the record is 2,640 chars (limit 4,000) but the
    supposedly minimal index renders at 3,291 (limit 3,000) — the renderer cannot
    shrink opaque addresses, so there is nothing left to degrade.
    """
    findings = tuple(
        Finding(
            finding_id=f"f{index}",
            kind=FindingKind.FACT,
            statement="一季度订单与交付排期的事实描述",
            evidence_refs=tuple(
                "ce:" + f"{index:02d}{slot}" + "a" * 28 for slot in range(3)
            ),
        )
        for index in range(24)
    )
    return ReadingCheckpoint(
        checkpoint_id="ck:test/wide",
        task_id="run-1",
        question="订单与交付排期",
        findings=findings,
        sources=(SourceRange("doc-1", "build-3", 0, 100),),
        coverage=Coverage(read_ranges=(SourceRange("doc-1", "build-3", 0, 100),)),
    )


def test_an_index_that_cannot_fit_its_own_budget_blocks_retirement() -> None:
    """The floor is a refusal, not a wish: bodies stay when the index cannot fit."""
    from frontier_agent.core.runtime.reading.stage import minimal_recoverable_index_chars

    checkpoint = _wide_checkpoint()
    assert minimal_recoverable_index_chars(checkpoint) > 3_000

    async def wide(bodies, question, bounds):
        return checkpoint

    messages = _history()
    before = json.dumps(messages, ensure_ascii=False)
    store = _Store()
    stage = _stage(wide, store=store, archive_max_chars=3_000)

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=1))

    assert event.installed is False
    assert event.reason == "checkpoint_failed"
    assert event.failure == "archive_index_over_budget"
    assert event.retired_chars == 0
    assert json.dumps(messages, ensure_ascii=False) == before, "no body may retire"
    assert store.saved == {}, "an unusable record is not persisted either"


def test_a_widened_statement_blocks_retirement() -> None:
    """The install gate is what stops a claim outliving the text it came from."""
    from frontier_agent.core.runtime.reading.contract import ValidationIssue

    def check(finding, quoted):
        assert quoted, "the gate must have the cited text in hand"
        return [
            ValidationIssue(
                "statement_scope_expanded",
                f"{finding.finding_id} 丢失适用范围限定",
                finding.finding_id,
            )
        ]

    messages = _history()
    before = json.dumps(messages, ensure_ascii=False)
    stage = _stage(
        _ok_extractor,
        statement_check=check,
        resolve=lambda ref: {"quote": "部分订单存在溢价，但未套用于全部组合。"},
    )

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=1))

    assert event.installed is False
    assert event.failure == "statement_scope_expanded"
    assert json.dumps(messages, ensure_ascii=False) == before


def test_a_rejected_record_is_retried_with_that_rejection_as_feedback() -> None:
    """A gate rejection used to end the stage with half its budget unspent.

    That is how ``max_attempts=2`` produced one attempt in every observed failure.
    Two things are asserted here: the retry actually runs, and it is a correction
    rather than a reroll — the second call is handed the rejection code and the
    offending finding id, which is the only thing that can change the wording.
    """
    from frontier_agent.core.runtime.reading.contract import ValidationIssue

    verdicts: list[int] = []
    feedbacks: list[str] = []

    def check(finding, quoted):
        assert quoted, "the gate must have the cited text in hand"
        verdicts.append(1)
        if len(verdicts) == 1:
            return [
                ValidationIssue(
                    "statement_scope_expanded",
                    f"{finding.finding_id} 丢失适用范围限定（未将该、套用于全部）",
                    finding.finding_id,
                )
            ]
        return []

    async def extractor(bodies, question, bounds, *, feedback=""):
        del bodies, question, bounds
        feedbacks.append(feedback)
        return _checkpoint()

    store = _Store()
    messages = _history()
    stage = _stage(
        extractor,
        store=store,
        statement_check=check,
        resolve=lambda ref: {"quote": "部分订单存在溢价，但未套用于全部组合。"},
    )

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=1))

    assert event.installed is True
    assert [attempt.outcome for attempt in event.attempts] == ["validation_rejected", "installed"]
    assert feedbacks[0] == "", "the first attempt has nothing to correct"
    assert "statement_scope_expanded" in feedbacks[1]
    assert "[f0]" in feedbacks[1]
    assert len(store.saved) == 1
    assert is_retired_body(messages[3]["content"])


def test_a_write_failure_is_not_retried() -> None:
    """A store that refused the write will refuse the next one too.

    Retrying this would pay for a second extraction to reach the same exception,
    so the stage stops and leaves the history alone.
    """
    calls: list[int] = []

    async def extractor(bodies, question, bounds, *, feedback=""):
        del bodies, question, bounds, feedback
        calls.append(1)
        return _checkpoint()

    messages = _history()
    before = json.dumps(messages, ensure_ascii=False)
    stage = _stage(extractor, store=_Store(fail=True))

    event = asyncio.run(stage.maybe_checkpoint(messages, turn=1))

    assert len(calls) == 1
    assert event.failure == "archive_write_failed"
    assert json.dumps(messages, ensure_ascii=False) == before


def test_an_extractor_without_a_feedback_parameter_still_runs() -> None:
    """The correction channel is optional: a three-argument extractor keeps working.

    ``_ok_extractor`` is a plain function, the shape every extractor written before
    this hook has. Passing it a ``feedback`` keyword would turn the retry into a
    ``TypeError`` recorded as ``extraction_failed``.
    """
    seen: list[str] = []

    def check(finding, quoted):
        del finding, quoted
        seen.append("checked")
        return []

    stage = _stage(
        _ok_extractor,
        statement_check=check,
        resolve=lambda ref: {"quote": "部分订单存在溢价，但未套用于全部组合。"},
    )
    event = asyncio.run(stage.maybe_checkpoint(_history(), turn=1))

    assert event.installed is True
    assert seen
    assert event.failure == ""


def test_a_statement_check_is_skipped_when_the_cited_text_is_absent() -> None:
    """No source text, no verdict: the gate must not guess from the statement."""
    calls: list[str] = []

    def check(finding, quoted):
        calls.append(quoted)
        return []

    stage = _stage(_ok_extractor, statement_check=check)  # default resolve: no quote
    asyncio.run(stage.maybe_checkpoint(_history(), turn=1))

    assert calls == []


def test_the_index_pays_for_addresses_before_it_pays_for_cues() -> None:
    """Topic width degrades first: a budget that fits no cue still lists refs."""
    from frontier_agent.core.runtime.reading.stage import _render_archive

    checkpoint = _twin_checkpoint()
    tight, index_only = _render_archive(checkpoint, max_chars=len("x") + 200)

    assert index_only is True
    for finding in checkpoint.findings:
        for ref in finding.evidence_refs:
            assert ref in tight
    assert "套用于全部" not in tight, "cues are dropped before any address is"


def test_the_extractor_is_told_what_the_record_budget_is() -> None:
    captured: dict = {}

    async def capture(bodies, question, bounds):
        captured["bounds"] = bounds
        captured["question"] = question
        captured["chars"] = [body.chars for body in bodies]
        return _checkpoint()

    asyncio.run(_stage(capture, record_limit=2_000).maybe_checkpoint(_history(), turn=1))

    assert captured["bounds"].record_limit == 2_000
    assert captured["question"].startswith("研究该公司")
    assert captured["chars"] == [len(BODY), len(BODY)]


def test_cancellation_is_not_swallowed() -> None:
    """A cancelled run must unwind; only ``Exception`` is treated as a soft
    failure."""

    async def cancelled(bodies, question, bounds):
        raise asyncio.CancelledError

    stage = _stage(cancelled)

    with pytest.raises(asyncio.CancelledError):
        asyncio.run(stage.maybe_checkpoint(_history(), turn=1))


class _EventSpy(BaseObserver):
    critical = True

    def __init__(self) -> None:
        self.events: list[ReadingCheckpointEvent] = []

    async def on_reading_checkpoint(self, event: ReadingCheckpointEvent) -> None:
        self.events.append(event)
        return None


@tool
async def read_document(doc_id: str) -> str:
    """Return a long page of verbatim text.

    Args:
        doc_id: Document to read.
    """
    return BODY


class _ReadingModel:
    model = "stub"

    def __init__(self, reads: int = 1) -> None:
        self.calls = 0
        self.reads = reads
        self.seen: list[list] = []

    async def chat(self, messages, **kwargs):
        del kwargs
        self.calls += 1
        self.seen.append([dict(m) for m in messages])
        if self.calls <= self.reads:
            return LLMResponse(
                content="reading",
                tool_calls=[
                    {
                        "id": f"r{self.calls}",
                        "type": "function",
                        "function": {"name": "read_document", "arguments": '{"doc_id":"d1"}'},
                    }
                ],
                finish_reason="tool_calls",
            )
        return LLMResponse(content="done", tool_calls=[], finish_reason="stop")


@pytest.mark.asyncio
async def test_the_loop_runs_the_stage_and_reports_it() -> None:
    """Wiring, not mechanism: the stage is reachable from the loop, runs between
    model calls, and its outcome is reported even when it declines."""
    spy = _EventSpy()
    model = _ReadingModel(reads=1)
    stage = _stage(_ok_extractor, working_set_limit=1_000, keep_recent_messages=0)

    await run_agent_loop(
        system_prompt="system prompt",
        user_message="读一篇长文",
        llm=model,
        tools=[read_document],
        config=LoopConfig(
            max_turns=3,
            task_id="run-1",
            keep_recent=64,
            reading_stage=stage,
        ),
        observers=[spy],
    )

    assert spy.events, "the loop reported no reading-stage run"
    first = spy.events[0]
    # Turn 1 ends with a result the model has not read yet, so the stage declines.
    # That decline is reported too — otherwise "nothing was archived" has no trail.
    assert first.triggered is False
    assert first.reason == "no_retirable_bodies"


@pytest.mark.asyncio
async def test_a_retired_body_reaches_the_next_request_as_a_short_marker() -> None:
    """End to end: what the model sees on the next call is the marker plus the
    archive, not the page it already read."""
    model = _ReadingModel(reads=2)
    stage = _stage(_ok_extractor, working_set_limit=1_000, keep_recent_messages=0)

    await run_agent_loop(
        system_prompt="system prompt",
        user_message="读一篇长文",
        llm=model,
        tools=[read_document],
        config=LoopConfig(
            max_turns=4,
            task_id="run-1",
            keep_recent=64,
            reading_stage=stage,
        ),
        observers=[],
    )

    last_request = model.seen[-1]
    blob = json.dumps(last_request, ensure_ascii=False)
    assert RETIRED_MARKER in blob, "the retired body never reached a later request"
    assert "研究归档" in blob
    # Exactly the page the model had already read is gone. The second one is the
    # result of the turn that is still in flight, so it stays verbatim — retiring
    # it would summarise a page before anyone read it.
    assert blob.count(RETIRED_MARKER) == 1
    assert blob.count("verbatim page text") > 100, "the unread page must stay verbatim"
    assert len(blob) < 2 * len(BODY)
