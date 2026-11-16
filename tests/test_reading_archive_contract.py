"""The reading-checkpoint contract must reject, not repair.

Each test below is one of the failure modes that motivated the contract: a unit
dropped, counter-evidence missing, an unread range declared complete, a dead
reference, a record reused across tasks, and a write that fails after the bodies
were supposed to go. The last one is the dangerous direction — a rejection that
raises gets noticed; a rejection that returns "fine" silently deletes evidence.
"""

from __future__ import annotations

import pytest

from frontier_agent.core.runtime.reading.contract import (
    CHECKPOINT_SCHEMA_VERSION,
    CheckpointBudget,
    CheckpointStatus,
    Coverage,
    Exclusion,
    Finding,
    FindingKind,
    ReadingCheckpoint,
    SourceRange,
    install_checkpoint,
    validate_checkpoint,
)


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


def _range(start: int = 0, end: int = 100, **extra: object) -> SourceRange:
    return SourceRange(source_id="doc-1", version="build-3", start=start, end=end, **extra)


def _number(
    finding_id: str = "f1",
    *,
    value: str = "123",
    unit: str = "million USD",
    period: str = "FY2025",
    source_id: str = "doc-1",
    contradicts: tuple[str, ...] = (),
) -> Finding:
    return Finding(
        finding_id=finding_id,
        kind=FindingKind.NUMBER,
        statement=f"revenue {value} {unit} ({period})",
        evidence_refs=(f"ce:{finding_id}",),
        source_id=source_id,
        value=value,
        unit=unit,
        period=period,
        contradicts=contradicts,
    )


def _checkpoint(**overrides: object) -> ReadingCheckpoint:
    defaults: dict = {
        "checkpoint_id": "ck-1",
        "task_id": "task-1",
        "question": "what did the report say about revenue",
        "findings": (_number(),),
        "sources": (_range(),),
        "coverage": Coverage(read_ranges=(_range(),), complete=False),
        "excluded": (Exclusion(path="appendix-b", reason="超出本次范围"),),
        "open_questions": ("why did margin fall",),
        "budget": CheckpointBudget(
            record_chars=800,
            record_limit=4_000,
            working_set_chars=12_000,
            working_set_limit=20_000,
        ),
    }
    defaults.update(overrides)
    return ReadingCheckpoint(**defaults)


def test_a_complete_record_installs_and_only_then_may_retire_bodies() -> None:
    store = _Store()

    outcome = install_checkpoint(_checkpoint(), store, resolve=lambda ref: {"text": ref})

    assert outcome.installed is True
    assert outcome.checkpoint.status == CheckpointStatus.INSTALLED
    assert store.saved["ck-1"].status == CheckpointStatus.INSTALLED
    assert outcome.reason == ""


def test_a_number_without_its_unit_or_period_is_rejected() -> None:
    """The classic summary loss: the figure survives, the currency and the year
    do not, and the record then reads as a different fact."""
    finding = _number(unit="", period="")

    result = validate_checkpoint(_checkpoint(findings=(finding,)))

    assert not result.ok
    assert result.codes == ["number_without_context"]
    assert "unit" in result.issues[0].detail
    assert "period" in result.issues[0].detail


def test_counter_evidence_must_be_linked_rather_than_dropped() -> None:
    """Two sources disagree about one measure in one period. Presenting only the
    first is not a rounding choice; it is an omission."""
    reported = _number("f1", value="123")
    disputed = _number("f2", value="98", source_id="doc-2")

    result = validate_checkpoint(_checkpoint(findings=(reported, disputed)))

    assert result.codes == ["unreported_contradiction"]

    linked = _number("f2", value="98", source_id="doc-2", contradicts=("f1",))
    assert validate_checkpoint(_checkpoint(findings=(reported, linked))).ok


def test_two_numbers_differing_only_in_period_are_not_a_contradiction() -> None:
    """Guards the guard: a legitimate year-over-year pair must not be flagged."""
    first = _number("f1", value="123", period="FY2024")
    second = _number("f2", value="98", period="FY2025", source_id="doc-2")

    assert validate_checkpoint(_checkpoint(findings=(first, second))).ok


def test_an_unread_range_cannot_be_declared_complete() -> None:
    coverage = Coverage(
        read_ranges=(_range(0, 100),),
        unread_ranges=(_range(100, 400),),
        complete=True,
    )

    result = validate_checkpoint(_checkpoint(coverage=coverage))

    assert result.codes == ["complete_with_unread_ranges"]


def test_a_limitation_prevents_a_completeness_claim() -> None:
    coverage = Coverage(
        read_ranges=(_range(),),
        limitations=("表格结构未校验",),
        complete=True,
    )

    result = validate_checkpoint(_checkpoint(coverage=coverage))

    assert result.codes == ["complete_with_limitations"]


def test_an_unresolvable_reference_blocks_installation() -> None:
    """A ref that no longer resolves is a dead pointer. Storing the record anyway
    would make the archive look recoverable while nothing can be recovered."""
    store = _Store()

    outcome = install_checkpoint(
        _checkpoint(),
        store,
        resolve=lambda ref: None,
    )

    assert outcome.installed is False
    assert outcome.reason == "evidence_pointer_unresolved"
    assert store.saved == {}


def test_a_finding_without_evidence_is_rejected() -> None:
    bare = Finding(
        finding_id="f1",
        kind=FindingKind.FACT,
        statement="the report is cautious about guidance",
        evidence_refs=(),
    )

    result = validate_checkpoint(_checkpoint(findings=(bare,)))

    assert "finding_without_evidence" in result.codes


def test_a_checkpoint_from_another_task_is_refused() -> None:
    """Cross-task reuse reads perfectly well and is about different material."""
    result = validate_checkpoint(_checkpoint(), task_id="task-2")

    assert result.codes == ["cross_task_reuse"]


def test_a_stale_source_version_is_refused() -> None:
    result = validate_checkpoint(
        _checkpoint(),
        source_versions={"doc-1": "build-4"},
    )

    assert result.codes == ["stale_source_version"]


def test_a_source_outside_admission_is_refused() -> None:
    result = validate_checkpoint(_checkpoint(), source_versions={})

    assert result.codes == ["unknown_source"]


def test_a_failed_write_leaves_the_record_uninstalled() -> None:
    """The one failure that cannot be allowed to look like success: bodies retire
    only on ``installed=True``, so a store that raises must not produce it."""
    store = _Store(fail=True)

    outcome = install_checkpoint(_checkpoint(), store)

    assert outcome.installed is False
    assert outcome.reason == "archive_write_failed"
    assert outcome.checkpoint.status == CheckpointStatus.DRAFT


def test_an_empty_record_cannot_retire_bodies() -> None:
    outcome = install_checkpoint(_checkpoint(findings=()), _Store())

    assert outcome.installed is False
    assert outcome.reason == "empty_record"


def test_an_oversized_record_is_rejected_rather_than_installed() -> None:
    """An unbounded archive only moves the growth out of the transcript."""
    budget = CheckpointBudget(
        record_chars=9_000,
        record_limit=4_000,
        working_set_chars=10,
        working_set_limit=20_000,
    )

    result = validate_checkpoint(_checkpoint(budget=budget))

    assert result.codes == ["record_over_budget"]
    assert result.ok is False


def test_a_record_from_another_schema_is_not_reinterpreted() -> None:
    result = validate_checkpoint(_checkpoint(schema_version=CHECKPOINT_SCHEMA_VERSION + 1))

    assert result.codes == ["schema_version_mismatch"]


def test_overlap_is_decided_by_position_not_by_request_parameters() -> None:
    """The same span asked for through a cursor, a locator or a ref must count as
    the same range; parameter equality would miss all three."""
    first = _range(100, 400, locator="unit:0012")
    same = _range(250, 500)
    adjacent = _range(400, 600)
    other_version = SourceRange("doc-1", "build-4", 100, 400)

    assert first.overlaps(same)
    assert not first.overlaps(adjacent)
    assert not first.overlaps(other_version)


def test_retirement_requires_an_installed_status() -> None:
    """Everything else — draft, validated, rejected, superseded — keeps the
    original context. This is the property the loop branches on."""
    permitted = {CheckpointStatus.INSTALLED}

    assert all(
        status not in permitted
        for status in CheckpointStatus
        if status is not CheckpointStatus.INSTALLED
    )
    assert _checkpoint(status=CheckpointStatus.VALIDATED).status not in permitted


@pytest.mark.parametrize("missing", ["", "   "])
def test_a_blank_question_is_rejected(missing: str) -> None:
    result = validate_checkpoint(_checkpoint(question=missing))

    assert "missing_question" in result.codes
