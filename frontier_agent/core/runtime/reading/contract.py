"""The minimum contract a reading checkpoint must satisfy before bodies retire.

Why a contract and not a convention
-----------------------------------
Compaction already had a rule — "summarize, then drop" — and it still lost
evidence, because nothing checked the product. A summary is prose; prose cannot
be asked whether it dropped a unit, a limitation or a contradiction. This module
makes the product *structured* and therefore checkable: findings point at
evidence refs, coverage distinguishes read from unread, and a checkpoint cannot
claim completeness it does not have.

The three states that must not be confused
------------------------------------------
*Delivered* is a fact about a message boundary. *Recorded* is a fact about this
archive. *Understood* is not a program-level property at all. A checkpoint
proves the first two and never the third, and the difference is why
:func:`validate_checkpoint` can return ``ok`` for a record whose semantic quality
is still unproven — see ``docs`` in the issue that owns this contract.

What is deliberately not here
-----------------------------
No storage, no IO, no tool names, no document vocabulary. ``source_id``,
``locator`` and evidence refs are opaque strings the embedding layer knows how to
resolve; the framework only requires that they resolve *somewhere* (via the
``resolve`` callable the caller supplies) and that they are stable. That keeps the
corpus policy in ``plugins/corpus`` and the mechanism here.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

__all__ = [
    "CHECKPOINT_SCHEMA_VERSION",
    "CheckpointBudget",
    "CheckpointStatus",
    "Coverage",
    "Exclusion",
    "Finding",
    "FindingKind",
    "InstallOutcome",
    "ReadingCheckpoint",
    "ReadingCheckpointStore",
    "SourceRange",
    "ValidationIssue",
    "ValidationResult",
    "install_checkpoint",
    "validate_checkpoint",
]

#: Bumped when a field changes meaning. A checkpoint written under another
#: version is not silently reinterpreted: :func:`validate_checkpoint` rejects it,
#: because a record that is half-understood is worse than a missing one.
CHECKPOINT_SCHEMA_VERSION = 1


class FindingKind(StrEnum):
    """What kind of statement a finding is.

    The kinds are not decoration: ``NUMBER`` is what forces a unit and a period,
    and ``COUNTER_EVIDENCE`` is what allows a record to hold two values that
    disagree. A free-text summary has no place to put either, which is how a
    unit gets dropped and a contradiction disappears.
    """

    FACT = "fact"
    NUMBER = "number"
    DATE = "date"
    CONDITION = "condition"
    COUNTER_EVIDENCE = "counter_evidence"


class CheckpointStatus(StrEnum):
    """Where a checkpoint is in its life.

    ``DRAFT`` is being assembled. ``VALIDATED`` passed the structural checks.
    ``INSTALLED`` is durable and may retire the bodies it replaces. ``SUPERSEDED``
    was replaced by a later checkpoint of the same task. ``REJECTED`` failed and
    must leave the original context in place.

    Only ``INSTALLED`` permits retirement. The transition is one-way and is owned
    by :func:`install_checkpoint`; a caller that flips the field by hand is
    bypassing the only guarantee this module makes.
    """

    DRAFT = "draft"
    VALIDATED = "validated"
    INSTALLED = "installed"
    SUPERSEDED = "superseded"
    REJECTED = "rejected"


@dataclass(frozen=True)
class SourceRange:
    """A span of one source version.

    ``version`` is part of the identity, not a label. Evidence quoted from
    ``build`` 3 cannot support a claim about ``build`` 4 — the text may have
    moved or been withdrawn — so a checkpoint that mixes versions for one source
    is rejected rather than reconciled.
    """

    source_id: str
    version: str
    start: int
    end: int
    locator: str = ""

    def overlaps(self, other: SourceRange) -> bool:
        """Whether two ranges of the same source version cover shared characters.

        Used to recognise a re-read of material already archived. Parameter
        equality is not a substitute: the same span requested through a cursor,
        a unit locator or a ref must still count as the same range.
        """
        return (
            self.source_id == other.source_id
            and self.version == other.version
            and self.start < other.end
            and other.start < self.end
        )


@dataclass(frozen=True)
class Finding:
    """One recorded statement, bound to the evidence that carries it.

    ``statement`` is the researcher's phrasing. It is NOT evidence and never
    replaces the quoted text: ``evidence_refs`` is what a later turn resolves when
    it needs the exact words. A finding with no ref is rejected, because a record
    that cannot be traced back is indistinguishable from a guess.

    ``kind=NUMBER`` requires ``value``, ``unit`` and ``period``. That triple is
    the guard against the classic summary error — "revenue was 123" with the
    currency, the scale and the year all gone. The record may leave the triple
    empty only by declaring a different kind, which is a visible choice rather
    than an omission.

    ``contradicts`` names findings this one disputes. It exists so that
    counter-evidence has somewhere to live: a checkpoint holding two values for
    the same measure and period must link them, or it is silently reporting one
    and dropping the other.
    """

    finding_id: str
    kind: FindingKind
    statement: str
    evidence_refs: tuple[str, ...]
    source_id: str = ""
    value: str = ""
    unit: str = ""
    period: str = ""
    condition: str = ""
    contradicts: tuple[str, ...] = ()


@dataclass(frozen=True)
class Exclusion:
    """A path that was considered and ruled out, with the reason.

    Kept because "we already tried that" is the most commonly lost piece of
    research state: without it the next turn repeats the attempt, and the
    repetition looks like new work in every metric that counts reads.
    """

    path: str
    reason: str


@dataclass(frozen=True)
class Coverage:
    """What the record covers, and what it does not.

    ``complete`` is a claim about *this checkpoint's own reading*, and it is
    checkable: it may only be true when ``unread_ranges`` and ``limitations``
    are both empty. Marking an unread range complete is the failure mode that
    makes a report confident and wrong, so it is a validation error rather than
    a warning.
    """

    read_ranges: tuple[SourceRange, ...] = ()
    unread_ranges: tuple[SourceRange, ...] = ()
    limitations: tuple[str, ...] = ()
    complete: bool = False


@dataclass(frozen=True)
class CheckpointBudget:
    """Two budgets, two owners.

    ``record_*`` bounds the archive itself — an unbounded record just moves the
    growth from the transcript into the checkpoint. ``working_set_*`` bounds the
    live context and belongs to the loop, not to the archive: a checkpoint may be
    well inside its own budget while the context is over, and the reverse.

    Neither number is enforced here; this module records what was measured so the
    decision can be replayed.
    """

    record_chars: int = 0
    record_limit: int = 0
    working_set_chars: int = 0
    working_set_limit: int = 0

    @property
    def record_over_budget(self) -> bool:
        return self.record_limit > 0 and self.record_chars > self.record_limit

    @property
    def working_set_over_budget(self) -> bool:
        return self.working_set_limit > 0 and self.working_set_chars > self.working_set_limit


@dataclass(frozen=True)
class ReadingCheckpoint:
    """One durable research record, published between model calls.

    Immutable by construction: installing a revision means creating a new
    checkpoint that names its predecessor in ``supersedes``. Rewriting parts of
    an installed record would make prefix-cache stability and replay both
    unverifiable.
    """

    checkpoint_id: str
    task_id: str
    question: str
    findings: tuple[Finding, ...] = ()
    sources: tuple[SourceRange, ...] = ()
    coverage: Coverage = field(default_factory=Coverage)
    excluded: tuple[Exclusion, ...] = ()
    open_questions: tuple[str, ...] = ()
    budget: CheckpointBudget = field(default_factory=CheckpointBudget)
    status: CheckpointStatus = CheckpointStatus.DRAFT
    supersedes: str = ""
    schema_version: int = CHECKPOINT_SCHEMA_VERSION

    def source_version(self, source_id: str) -> str | None:
        for source in self.sources:
            if source.source_id == source_id:
                return source.version
        return None

    def unread_chars(self) -> int:
        return sum(max(0, rng.end - rng.start) for rng in self.coverage.unread_ranges)


@dataclass(frozen=True)
class ValidationIssue:
    """A specific reason a checkpoint may not be installed.

    ``code`` is stable (tests and telemetry match on it); ``detail`` is for the
    human reading the trace. Every issue is a *rejection*, not a repair
    suggestion — this module never fixes a record, because silently correcting a
    unit is the same class of bug as dropping one.
    """

    code: str
    detail: str
    finding_id: str = ""


@dataclass(frozen=True)
class ValidationResult:
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.issues

    @property
    def codes(self) -> list[str]:
        return [issue.code for issue in self.issues]


class ReadingCheckpointStore(Protocol):
    """Durable home for installed checkpoints.

    Deliberately tiny and allowed to fail. The store is the reason a body may
    retire, so a write that raises must leave the caller with its original
    context intact — ``install_checkpoint`` converts the exception into an
    outcome rather than letting it escape.
    """

    def put(self, checkpoint: ReadingCheckpoint) -> None:
        """Persist *checkpoint*. Raise on failure."""

    def get(self, checkpoint_id: str) -> ReadingCheckpoint | None:
        """Return a stored checkpoint, or ``None``."""


@dataclass(frozen=True)
class InstallOutcome:
    """What happened, and therefore whether bodies may retire.

    ``installed=True`` is the only value that authorises retirement. Everything
    else — structural rejection, write failure, empty record — means the current
    context stays as it is. Callers must branch on this flag rather than on the
    absence of an exception, because the interesting failures are the ones that
    do not raise.
    """

    installed: bool
    checkpoint: ReadingCheckpoint
    issues: tuple[ValidationIssue, ...] = ()

    @property
    def reason(self) -> str:
        return self.issues[0].code if self.issues else ""


def _finding_issues(
    finding: Finding,
    resolve: Callable[[str], Any] | None,
    statement_check: Callable[[Finding, str], Sequence[ValidationIssue]] | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    quoted: list[str] = []
    if not finding.evidence_refs:
        # A statement with no ref cannot be told apart from a guess, and it is
        # exactly what a prose summary produces.
        issues.append(
            ValidationIssue(
                "finding_without_evidence",
                f"{finding.finding_id} 没有 evidence_ref，不能作为可恢复证据",
                finding.finding_id,
            )
        )
    if resolve is not None:
        for ref in finding.evidence_refs:
            try:
                resolved = resolve(ref)
            except Exception as exc:
                resolved = None
                issues.append(
                    ValidationIssue(
                        "evidence_pointer_failed",
                        f"{finding.finding_id} 的引用 {ref} 解析异常：{exc}",
                        finding.finding_id,
                    )
                )
                continue
            if resolved is None:
                issues.append(
                    ValidationIssue(
                        "evidence_pointer_unresolved",
                        f"{finding.finding_id} 的引用 {ref} 无法解析（已撤销或版本不符）",
                        finding.finding_id,
                    )
                )
                continue
            if isinstance(resolved, dict) and isinstance(resolved.get("quote"), str):
                quoted.append(resolved["quote"])
    if finding.kind == FindingKind.NUMBER:
        missing = [
            name
            for name, value in (
                ("value", finding.value),
                ("unit", finding.unit),
                ("period", finding.period),
            )
            if not value.strip()
        ]
        if missing:
            # The classic loss: a number survives, its unit or period does not.
            issues.append(
                ValidationIssue(
                    "number_without_context",
                    f"{finding.finding_id} 是数量类发现但缺少 {', '.join(missing)}",
                    finding.finding_id,
                )
            )
    if statement_check is not None and quoted:
        # Only when the evidence text is actually in hand: a check that cannot see
        # the source cannot tell a widened statement from a faithful one, and
        # guessing on missing input would reject records for being unreadable
        # rather than for being wrong.
        issues.extend(statement_check(finding, "\n".join(quoted)))
    return issues


def _contradiction_issues(findings: Sequence[Finding]) -> list[ValidationIssue]:
    """Two values for one measure in one period must be linked.

    Without this, a record can hold both the reported figure and the study that
    disputes it while presenting only the first as fact — the omission the
    issue's counter-example calls "遗漏反证".
    """
    issues: list[ValidationIssue] = []
    numbers = [f for f in findings if f.kind == FindingKind.NUMBER]
    for index, left in enumerate(numbers):
        for right in numbers[index + 1 :]:
            same_measure = (
                left.value.strip() != right.value.strip()
                and left.period.strip() == right.period.strip() != ""
                and left.unit.strip() == right.unit.strip()
                and left.source_id != right.source_id
            )
            if not same_measure:
                continue
            linked = left.finding_id in right.contradicts or right.finding_id in left.contradicts
            if not linked:
                issues.append(
                    ValidationIssue(
                        "unreported_contradiction",
                        f"{left.finding_id} 与 {right.finding_id} 对同一口径给出不同数值，"
                        "但两者都没有记入反证",
                        left.finding_id,
                    )
                )
    return issues


def validate_checkpoint(
    checkpoint: ReadingCheckpoint,
    *,
    resolve: Callable[[str], Any] | None = None,
    task_id: str | None = None,
    source_versions: dict[str, str] | None = None,
    statement_check: Callable[[Finding, str], Sequence[ValidationIssue]] | None = None,
) -> ValidationResult:
    """Check a checkpoint against the contract, without repairing it.

    ``resolve`` is how the embedding layer proves its refs still work — pass a
    callable that returns ``None`` for an unresolvable ref. ``task_id`` and
    ``source_versions`` catch cross-task reuse and stale-version reuse; both are
    silent corruption otherwise, because the record reads perfectly well and is
    simply about different material.

    ``statement_check`` is the embedding layer's per-finding fidelity rule, called
    with the resolved evidence text. It lives outside this module on purpose: the
    contract must not grow a Chinese limiter lexicon or any other language
    assumption. Absent, the record is judged on structure and pointers only.
    """
    issues: list[ValidationIssue] = []

    if checkpoint.schema_version != CHECKPOINT_SCHEMA_VERSION:
        issues.append(
            ValidationIssue(
                "schema_version_mismatch",
                f"期望 schema {CHECKPOINT_SCHEMA_VERSION}，实际 {checkpoint.schema_version}",
            )
        )
    if not checkpoint.checkpoint_id.strip():
        issues.append(ValidationIssue("missing_checkpoint_id", "检查点缺少稳定标识"))
    if not checkpoint.question.strip():
        issues.append(ValidationIssue("missing_question", "检查点没有记录它所回答的问题"))
    if checkpoint.status == CheckpointStatus.REJECTED:
        issues.append(ValidationIssue("already_rejected", "该检查点已被判为不通过"))

    if task_id is not None and checkpoint.task_id != task_id:
        issues.append(
            ValidationIssue(
                "cross_task_reuse",
                f"检查点属于任务 {checkpoint.task_id!r}，当前任务 {task_id!r}",
            )
        )

    for source in checkpoint.sources:
        if source_versions is None:
            continue
        current = source_versions.get(source.source_id)
        if current is None:
            issues.append(
                ValidationIssue(
                    "unknown_source",
                    f"来源 {source.source_id} 不在当前准入范围",
                )
            )
        elif current != source.version:
            issues.append(
                ValidationIssue(
                    "stale_source_version",
                    f"来源 {source.source_id} 记录版本 {source.version}，当前 {current}",
                )
            )

    if not checkpoint.findings:
        # An empty record is not "nothing to say": it is a failed archiving step.
        # Installing it would drop the bodies with nothing to show for them.
        issues.append(ValidationIssue("empty_record", "检查点没有任何发现，不能据此退场正文"))

    coverage = checkpoint.coverage
    if coverage.complete and coverage.unread_ranges:
        issues.append(
            ValidationIssue(
                "complete_with_unread_ranges",
                f"声明覆盖完整，但仍有 {len(coverage.unread_ranges)} 段未读范围",
            )
        )
    if coverage.complete and coverage.limitations:
        issues.append(
            ValidationIssue(
                "complete_with_limitations",
                f"声明覆盖完整，但记录中仍有 {len(coverage.limitations)} 条限制",
            )
        )

    seen: set[str] = set()
    for finding in checkpoint.findings:
        if finding.finding_id in seen:
            issues.append(
                ValidationIssue(
                    "duplicate_finding_id",
                    f"重复的 finding_id {finding.finding_id}",
                    finding.finding_id,
                )
            )
        seen.add(finding.finding_id)
        issues.extend(_finding_issues(finding, resolve, statement_check))
    issues.extend(_contradiction_issues(checkpoint.findings))

    if checkpoint.budget.record_over_budget:
        issues.append(
            ValidationIssue(
                "record_over_budget",
                f"归档自身 {checkpoint.budget.record_chars} 字符已超记录预算 "
                f"{checkpoint.budget.record_limit}",
            )
        )

    return ValidationResult(tuple(issues))


def install_checkpoint(
    checkpoint: ReadingCheckpoint,
    store: ReadingCheckpointStore,
    *,
    resolve: Callable[[str], Any] | None = None,
    task_id: str | None = None,
    source_versions: dict[str, str] | None = None,
    statement_check: Callable[[Finding, str], Sequence[ValidationIssue]] | None = None,
) -> InstallOutcome:
    """Validate, then persist. Bodies may retire only on ``installed=True``.

    The order is the contract: validate first (nothing is written for a record
    that would be wrong), persist second, and mark installed only after the
    write returned. A store that raises produces ``archive_write_failed`` and an
    untouched context — the failure mode the issue calls "正文已删除、归档却不可用"
    is exactly what this ordering prevents.
    """
    result = validate_checkpoint(
        checkpoint,
        resolve=resolve,
        task_id=task_id,
        source_versions=source_versions,
        statement_check=statement_check,
    )
    if not result.ok:
        return InstallOutcome(installed=False, checkpoint=checkpoint, issues=result.issues)

    installed = ReadingCheckpoint(
        **{
            **{
                name: getattr(checkpoint, name)
                for name in (
                    "checkpoint_id",
                    "task_id",
                    "question",
                    "findings",
                    "sources",
                    "coverage",
                    "excluded",
                    "open_questions",
                    "budget",
                    "supersedes",
                    "schema_version",
                )
            },
            "status": CheckpointStatus.INSTALLED,
        },
    )
    try:
        store.put(installed)
    except Exception as exc:
        return InstallOutcome(
            installed=False,
            checkpoint=checkpoint,
            issues=(
                ValidationIssue(
                    "archive_write_failed",
                    f"归档写入失败：{exc}",
                ),
            ),
        )
    return InstallOutcome(installed=True, checkpoint=installed)


def findings_by_kind(findings: Iterable[Finding]) -> dict[FindingKind, list[Finding]]:
    """Group findings by kind for rendering; order within a kind is preserved."""
    grouped: dict[FindingKind, list[Finding]] = {}
    for finding in findings:
        grouped.setdefault(finding.kind, []).append(finding)
    return grouped
