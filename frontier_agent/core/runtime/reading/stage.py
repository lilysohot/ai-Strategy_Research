"""Retire read bodies behind a validated checkpoint, between model calls.

The problem this solves is not "the window is full". A long reading task grows
steadily at 40% of the window and never trips the global threshold, so the
generic compactor never runs and every page of verbatim text stays in the
request forever. Lowering the global threshold would answer the wrong question —
it would also mangle tool definitions and recent results that nobody has finished
using.

So this stage has its own trigger and its own budget: when the *read bodies* held
in the working set exceed their own limit, they are extracted into a checkpoint,
the checkpoint is validated and persisted, and only then are those bodies replaced
by a pointer. Everything else in the history is untouched, and no body is retired
until the record that replaces it is durable.

Three properties worth stating, because they are the reason the code looks the way
it does:

*Append-only, therefore cache-stable.* A retired body is replaced once and never
rewritten; each checkpoint appends one message. Two consecutive turns therefore
share a byte-identical prefix, which is what makes prefix caching survive
checkpointing at all.

*Failure is the safe direction.* Every path that cannot prove the record is
durable returns without touching ``messages``. The failure the design must never
produce is "bodies gone, archive unusable".

*Reduction is checked, not assumed.* ``install_checkpoint`` refuses a record with
an unlinked contradiction, a number missing its unit, or a completeness claim
that contradicts its own unread ranges. A prose summary cannot be refused, which
is why the archive is structured.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from frontier_agent.core.loop_types import wall_deadline_remaining_s
from frontier_agent.core.runtime.reading.contract import (
    CheckpointBudget,
    Finding,
    FindingKind,
    InstallOutcome,
    ReadingCheckpoint,
    ReadingCheckpointStore,
    ValidationIssue,
    install_checkpoint,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractionBounds",
    "ExtractionScope",
    "ReadingBudget",
    "ReadingCheckpointEvent",
    "ReadingStage",
    "ReadingStageAttempt",
    "ReadingStageConfig",
    "RetirableBody",
    "archive_marker",
    "is_retired_body",
    "minimal_recoverable_index_chars",
]

#: Prefix of the short body that replaces a retired tool result. It doubles as
#: the idempotence check: a body already carrying it is never extracted again, so
#: re-running the stage on the same history cannot double-archive or rewrite what
#: a previous checkpoint already replaced (the prefix-cache requirement).
RETIRED_MARKER = "[archived]"


def archive_marker(checkpoint_id: str) -> str:
    return f"{RETIRED_MARKER} text retired into reading checkpoint {checkpoint_id}"


def is_retired_body(content: Any) -> bool:
    return isinstance(content, str) and RETIRED_MARKER in content


@dataclass(frozen=True)
class RetirableBody:
    """A tool result the stage is willing to replace, with where it lives.

    ``index`` is a position in the live ``messages`` list, not an identity: the
    list is the thing being edited, so a caller must not cache these across turns.
    """

    index: int
    call_id: str
    tool_name: str
    text: str

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass(frozen=True)
class ExtractionBounds:
    """What the extractor is allowed to produce.

    Passed in rather than discovered after the fact: an extractor that does not
    know the record budget will produce a record that gets rejected, and a
    rejection costs a model call and leaves the bodies in place. The stage
    halves the limit and retries once rather than trimming findings itself,
    because trimming is how a fact disappears without anyone deciding to drop it.
    """

    record_limit: int
    max_findings: int


@dataclass(frozen=True)
class ExtractionScope:
    """What an extractor can say about its input *before* spending a model call.

    The stage cannot know whether a body carries citable references — that
    vocabulary belongs to the extractor. Without this probe a page that cites
    nothing (a prose fallback, a report envelope with refs in free text) still
    buys a full extraction call whose every finding must be dropped, because no
    ref it could cite is in the input. That is the expensive no-op this probe
    exists to prevent.

    ``applicable=False`` is a *decline*, not a failure: nothing is rewritten, no
    model is called, and the reason is recorded so "why was this never archived"
    has an answer. Missing numbers are ``None`` (unknown), never 0 — a zero ref
    count means "we looked and found none", which is a different statement.
    """

    applicable: bool
    reason: str = ""
    digest_chars: int | None = None
    digest_budget: int | None = None
    ref_count: int | None = None
    omitted_bodies: int | None = None
    body_count: int = 0


class CheckpointExtractor(Protocol):
    """Turns verbatim bodies into a candidate record.

    Implemented by the workflow layer, which is the only layer that knows what an
    evidence ref is. Raising, timing out, or returning an empty record are all
    ordinary outcomes: the stage treats each as "not installed" and keeps the
    bodies.

    Two hooks are optional and discovered with ``getattr`` so existing extractors
    keep working unchanged:

    ``scope(bodies, question)`` returns an :class:`ExtractionScope` without IO or
    a model call. When it says ``applicable=False`` the stage never calls
    ``__call__``.

    ``last_usage`` is read after each attempt and reported on the event. Absent or
    empty means the extraction cost is *unknown*, which is recorded as unknown
    rather than as zero.
    """

    async def __call__(
        self,
        bodies: Sequence[RetirableBody],
        question: str,
        bounds: ExtractionBounds,
    ) -> ReadingCheckpoint: ...


@dataclass(frozen=True)
class ReadingBudget:
    """Where the stage's spending limit comes from.

    ``remaining_s`` is the execution budget the caller still has (the loop's wall
    deadline by default). ``delivery_reserve_s`` is the part of that budget the
    caller has already promised to delivery and synthesis: the stage must not
    spend it, so it is subtracted before any attempt is priced.

    Both are callables rather than numbers because the stage decides *during* the
    turn, and the answers change between turns. Either may return ``None``, which
    the event records as unknown — an unmeasured budget is not an unlimited one,
    but the stage cannot invent a number for it either.
    """

    remaining_s: Callable[[], float | None] = wall_deadline_remaining_s
    delivery_reserve_s: Callable[[], float | None] | None = None


@dataclass(frozen=True)
class ReadingStageConfig:
    """The stage's own budget, deliberately independent of the global threshold.

    ``working_set_limit`` is what decides *when* to checkpoint, and it is a
    property of reading volume, not of window occupancy. ``keep_recent_messages``
    is the guard against retiring something the model has not consumed yet: the
    tail of the history belongs to the turn in flight.

    ``min_remaining_budget_s`` is a *decline* threshold: below it the archive is
    optional work and is skipped, because a checkpoint that returns nothing must
    not eat the turn that was going to finish the job. ``min_attempt_s`` is what
    stops a second attempt from being configured but unaffordable under one shared
    deadline — an attempt is only started when this much time is actually left.
    """

    enabled: bool = False
    min_body_chars: int = 4_000
    working_set_limit: int = 40_000
    keep_recent_messages: int = 6
    record_limit: int = 4_000
    max_findings: int = 24
    archive_max_chars: int = 3_000
    max_attempts: int = 2
    total_timeout_s: float = 60.0
    #: Do not start when the usable budget (remaining minus delivery reserve) is
    #: below this. Optional archiving is never worth the answer.
    min_remaining_budget_s: float = 45.0
    #: A further attempt is only started when at least this much of the stage
    #: deadline is left; otherwise the retry is recorded as not started. Capped at
    #: half of ``total_timeout_s`` so a short stage can still afford its own retry.
    min_attempt_s: float = 5.0
    #: Skip a repeat attempt whose input is byte-identical to the one that just
    #: failed. Without it, every subsequent turn pays the same cost for the same
    #: unchanged bodies and the outcome cannot change.
    skip_unchanged_failed_input: bool = True
    #: Optional per-finding statement check supplied by the embedding layer, called
    #: with ``(finding, quoted_text)`` and returning issues that block installation.
    #: ``None`` keeps this layer free of language and domain rules; the corpus
    #: plugin passes one, because a statement that widens its evidence must not be
    #: what replaces the body.
    statement_check: Callable[[Finding, str], Sequence[ValidationIssue]] | None = None


@dataclass(frozen=True)
class ReadingStageAttempt:
    """One bounded attempt, including the ones that never got to run.

    ``outcome`` is the stable code tests and telemetry match on. ``not_started``
    is a real outcome: under a shared deadline, "configured two attempts" and
    "had budget for two attempts" are different facts.
    """

    index: int
    duration_s: float = 0.0
    outcome: str = ""
    detail: str = ""


@dataclass(frozen=True)
class ReadingCheckpointEvent:
    """What one stage run did, for the trace.

    ``reason`` is set on every run, including the runs that did nothing — "no
    checkpoint because the working set was small" is information, and its absence
    is what makes growth impossible to explain after the fact.

    ``phase`` separates the two records one attempt leaves behind: ``start`` is
    written before the extractor is called (so a run that never returns is still
    visible), ``end`` carries the outcome. Every other field is a measurement; a
    field that could not be measured is ``None`` and is *not* an implicit zero.

    ``triggered`` means "the stage decided an extraction was worth attempting".
    A decline for budget or applicability reasons is ``triggered=False`` with its
    own ``reason``: skipping optional work is budget protection, not compression,
    and must not be counted as an archive.
    """

    triggered: bool = False
    reason: str = ""
    installed: bool = False
    failure: str = ""
    checkpoint_id: str = ""
    attempt: int = 0
    retired_calls: tuple[str, ...] = ()
    retired_chars: int = 0
    working_set_before: int = 0
    working_set_after: int = 0
    archive_chars: int = 0
    index_only: bool = False
    duration_s: float = 0.0
    turn: int = 0
    #: ``start`` or ``end``.
    phase: str = "end"
    body_count: int = 0
    #: Size of the text the extractor actually renders from the bodies. This is
    #: NOT ``working_set_before``: the working set counts the visible tool
    #: envelope, the digest counts what the model would read.
    digest_chars: int | None = None
    digest_budget: int | None = None
    ref_count: int | None = None
    omitted_bodies: int | None = None
    remaining_budget_s: float | None = None
    delivery_reserve_s: float | None = None
    attempts: tuple[ReadingStageAttempt, ...] = ()
    #: Extraction call usage, summed over attempts. ``None`` = unknown.
    usage: dict[str, int] | None = None
    usage_known: bool = False


def _tool_message_indices(messages: Sequence[Any], keep_recent: int) -> list[int]:
    """Positions of tool results that are both consumed and still verbatim.

    "Consumed" is decided by position, not by a count of turns: a tool result has
    been sent to the model exactly when an assistant message follows it. The
    results appended after the last assistant message are the ones the model has
    not seen yet — retiring those would replace a page with a summary before
    anyone read it.

    ``keep_recent`` adds a margin on top for callers that want more history left
    alone; it is a safety margin, not the rule.
    """
    last_assistant = -1
    for index, message in enumerate(messages):
        if isinstance(message, dict) and message.get("role") == "assistant":
            last_assistant = index
    cutoff = min(last_assistant, len(messages) - max(0, keep_recent))
    found: list[int] = []
    for index in range(max(0, cutoff)):
        message = messages[index]
        if not isinstance(message, dict) or message.get("role") != "tool":
            continue
        content = message.get("content")
        if is_retired_body(content):
            continue
        found.append(index)
    return found


def _call_id_of(message: dict[str, Any]) -> str:
    return str(message.get("tool_call_id") or message.get("call_id") or "")


def _tool_name_for(messages: Sequence[Any], index: int) -> str:
    """Name the tool that produced the result at *index*, best effort.

    Used only for the record and for excluding structured results from
    retirement; getting it wrong costs a better log line, never correctness.
    """
    message = messages[index]
    if not isinstance(message, dict):
        return ""
    explicit = message.get("name")
    if isinstance(explicit, str) and explicit:
        return explicit
    call_id = _call_id_of(message)
    for earlier in reversed(messages[:index]):
        if not isinstance(earlier, dict) or earlier.get("role") != "assistant":
            continue
        for call in earlier.get("tool_calls") or []:
            if not isinstance(call, dict):
                continue
            if str(call.get("id") or "") == call_id:
                function = call.get("function")
                if isinstance(function, dict) and isinstance(function.get("name"), str):
                    return function["name"]
    return ""


#: Index budget policy, in priority order: addresses first, topics second.
#: ``evidence_refs`` is the only address an existing tool can resolve, so refs are
#: paid for before any topic gets a character; a topic that does not fit is
#: dropped, whereas a ref that does not fit is never dropped. The cue is a
#: verbatim slice of the statement — the index may not invent a topic the record
#: does not contain, and it may not spend a model call to shorten text.
#:
#: 44 is measured, not chosen. On the 2026-11-17 180s record (22 findings, 34
#: refs) the rendered index is 2,934 of 3,000 chars, and 6/6 probe questions rank
#: their finding first; at 40 chars the same record leaves 2,866 chars and only
#: 4/6 rank first, because the discriminating clause usually is not at the start.
_TOPIC_MAX_CHARS = 44
_TOPIC_STEP_CHARS = 4
_INDEX_RECOVERY_HINT = (
    "恢复：每行的 refs 就是该发现的精确地址，逐条取回即得对应片段原文"
    "（一条发现的完整证据＝其列出的全部 refs），不要整篇重读。"
)


def _topic_of(finding: Finding, others: Sequence[Finding], width: int) -> str:
    """A short, discriminating cue from the statement, or "" when it does not fit.

    The cue is a verbatim window, never a paraphrase: the index may not invent a
    topic the record does not contain, and it may not spend a model call to
    shorten text. A plain prefix is not enough — the clause that distinguishes
    two findings ("部分…并未套用于全部" vs "需求被提前透支") is usually not at
    the start — so the window is chosen where this statement stops looking like
    its siblings, then padded with ``…`` to show it is an excerpt.
    """
    if width <= 1:
        return ""
    text = " ".join(finding.statement.split())
    if len(text) <= width:
        return text
    inner = width - 2
    if inner < 4:
        return text[: width - 1].rstrip() + "…"
    sibling_bigrams: set[str] = set()
    for other in others:
        if other.finding_id == finding.finding_id:
            continue
        other_text = " ".join(other.statement.split())
        sibling_bigrams.update(other_text[i : i + 2] for i in range(len(other_text) - 1))
    best_start, best_score = 0, -1.0
    for start in range(len(text) - inner + 1):
        window = text[start : start + inner]
        unique = sum(
            1.0
            for token in {window[i : i + 2] for i in range(len(window) - 1)}
            if token not in sibling_bigrams
        )
        if unique > best_score:  # earliest window wins ties: stable output
            best_start, best_score = start, unique
    prefix = "…" if best_start > 0 else ""
    suffix = "…" if best_start + inner < len(text) else ""
    return f"{prefix}{text[best_start : best_start + inner]}{suffix}"


def _index_body(findings: Sequence[Finding], width: int) -> list[str]:
    lines: list[str] = []
    for finding in findings:
        head = f"- {finding.finding_id} {finding.kind}"
        topic = _topic_of(finding, findings, width)
        if topic:
            head = f"{head} {topic}"
        lines.append(f"{head} refs: {', '.join(finding.evidence_refs)}")
    return lines


def _topics_collide(findings: Sequence[Finding], width: int) -> bool:
    topics = [_topic_of(finding, findings, width) for finding in findings]
    return len(set(topics)) != len(topics)


def _render_archive(
    checkpoint: ReadingCheckpoint,
    *,
    max_chars: int,
) -> tuple[str, bool]:
    """Render the record compactly. Returns ``(text, index_only)``.

    Index-only is the archive's own overflow mode: when the findings do not fit,
    the archive keeps the question, the addresses and the unread ranges, and says
    so. It never truncates mid-finding, because a half-rendered number reads as a
    whole one.
    """
    header = f"[研究归档 {checkpoint.checkpoint_id}] 问题：{checkpoint.question}"
    grouped: dict[FindingKind, list[Finding]] = {}
    for finding in checkpoint.findings:
        grouped.setdefault(finding.kind, []).append(finding)

    lines: list[str] = []
    for kind in (
        FindingKind.NUMBER,
        FindingKind.FACT,
        FindingKind.DATE,
        FindingKind.CONDITION,
        FindingKind.COUNTER_EVIDENCE,
    ):
        for finding in grouped.get(kind, []):
            parts = [f"- {kind}: {finding.statement}"]
            attributes = [
                label
                for label, value in (
                    ("value", finding.value),
                    ("unit", finding.unit),
                    ("period", finding.period),
                    ("condition", finding.condition),
                )
                if value
            ]
            if attributes:
                parts.append(f"({', '.join(attributes)})")
            if finding.contradicts:
                parts.append(f"↔ {', '.join(finding.contradicts)}")
            parts.append(f"refs: {', '.join(finding.evidence_refs)}")
            lines.append(" ".join(parts) + f" [{finding.finding_id}]")

    tail = _archive_tail(checkpoint)

    # One line of instruction, not a banner: the refs above are only useful if the
    # reader knows they are the way back to the exact words. Naming no tool keeps
    # this layer domain-neutral. Counted against the same budget as the findings —
    # a hint that pushes the archive over its own cap is still over its cap.
    recovery_hint = "需要逐字原文时，用 evidence_ref 定点补读该片段，不要整篇重读。"
    text = "\n".join([header, *lines, *tail])
    if len(text) + len(recovery_hint) + 1 <= max_chars:
        return f"{text}\n{recovery_hint}", False

    return _index_text(checkpoint, tail, max_chars=max_chars), True


def _archive_tail(checkpoint: ReadingCheckpoint) -> list[str]:
    """Non-finding lines both renderings carry: unread ranges, limits, questions."""
    tail: list[str] = []
    if checkpoint.coverage.unread_ranges:
        tail.append(
            "未读："
            + ", ".join(
                f"{rng.source_id}[{rng.start}-{rng.end}]@v{rng.version}"
                for rng in checkpoint.coverage.unread_ranges
            ),
        )
    if checkpoint.coverage.limitations:
        tail.append("限制：" + "；".join(checkpoint.coverage.limitations))
    if checkpoint.excluded:
        tail.append(
            "已排除：" + "；".join(f"{item.path}（{item.reason}）" for item in checkpoint.excluded),
        )
    if checkpoint.open_questions:
        tail.append("未决：" + "；".join(checkpoint.open_questions))
    return tail


def _index_text(
    checkpoint: ReadingCheckpoint,
    tail: Sequence[str],
    *,
    max_chars: int,
) -> str:
    """The index-only rendering, down to the smallest form that still recovers.

    ``max_chars=0`` yields that smallest form: header, one line of addresses per
    finding, the tail, the recovery hint — and no cue. Its length is the floor a
    record must fit before it is allowed to retire anything.
    """
    lead = [
        f"[研究归档 {checkpoint.checkpoint_id}] 问题：{checkpoint.question}",
        f"（归档超出预算，仅保留索引：{len(checkpoint.findings)} 条发现）",
    ]
    index_tail = [*tail, _INDEX_RECOVERY_HINT]
    room = max_chars - (len("\n".join([*lead, *index_tail])) + 1)

    chosen = _index_body(checkpoint.findings, 0)
    width = _TOPIC_MAX_CHARS
    while width >= _TOPIC_STEP_CHARS:
        lines = _index_body(checkpoint.findings, width)
        if len("\n".join(lines)) + 1 <= room:
            chosen = lines
            break
        width -= _TOPIC_STEP_CHARS

    # A duplicate cue is the failure mode topics exist to prevent, so widen while
    # the budget allows it; stop widening the moment it stops fitting. Topics are
    # still secondary: if even the narrowest cue overflows, refs alone are kept.
    while width < _TOPIC_MAX_CHARS and _topics_collide(checkpoint.findings, width):
        wider = width + _TOPIC_STEP_CHARS
        lines = _index_body(checkpoint.findings, wider)
        if len("\n".join(lines)) + 1 > room:
            break
        width, chosen = wider, lines

    return "\n".join([*lead, *chosen, *index_tail])


def minimal_recoverable_index_chars(checkpoint: ReadingCheckpoint) -> int:
    """Characters of the smallest index that still names every address.

    Addresses are opaque ids: they cannot be shortened, and dropping one turns a
    finding into an unbacked claim. So this is a floor, not an estimate — when the
    floor exceeds the archive budget, rendering cannot rescue the record and the
    bodies must not retire.
    """
    return len(_index_text(checkpoint, _archive_tail(checkpoint), max_chars=0))


class ReadingStage:
    """Runs between model calls: extract, validate, persist, then retire.

    The stage owns no policy about *what* a document is. It is handed an
    extractor; it decides when the reading volume justifies a checkpoint, and it
    owns the one guarantee that matters — a body is replaced only after the record
    replacing it is on disk.
    """

    def __init__(
        self,
        *,
        extractor: CheckpointExtractor,
        store: ReadingCheckpointStore,
        config: ReadingStageConfig | None = None,
        task_id: str = "",
        resolve: Callable[[str], Any] | None = None,
        source_versions: Callable[[], dict[str, str]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        budget: ReadingBudget | None = None,
    ) -> None:
        self._extractor = extractor
        self._store = store
        self._config = config or ReadingStageConfig()
        self._task_id = task_id
        self._resolve = resolve
        self._source_versions = source_versions
        self._clock = clock
        self._budget = budget if budget is not None else ReadingBudget()
        self._sequence = 0
        self._checkpoint_ids: list[str] = []
        #: Inputs that already failed, so the same unchanged bodies are not paid
        #: for twice. Keyed by a content fingerprint, bounded (the loop is long and
        #: this is a memo, not a history).
        self._failed_inputs: dict[str, str] = {}
        self._failed_order: list[str] = []
        self.last_event: ReadingCheckpointEvent | None = None

    @property
    def config(self) -> ReadingStageConfig:
        return self._config

    def _next_id(self) -> str:
        self._sequence += 1
        scope = self._task_id or "run"
        return f"ck:{scope}/{self._sequence:03d}"

    def _candidates(self, messages: Sequence[Any]) -> list[RetirableBody]:
        cfg = self._config
        bodies: list[RetirableBody] = []
        for index in _tool_message_indices(messages, cfg.keep_recent_messages):
            message = messages[index]
            content = message.get("content")
            if not isinstance(content, str) or len(content) < cfg.min_body_chars:
                continue
            bodies.append(
                RetirableBody(
                    index=index,
                    call_id=_call_id_of(message),
                    tool_name=_tool_name_for(messages, index),
                    text=content,
                )
            )
        return bodies

    @staticmethod
    def _fingerprint(bodies: Sequence[RetirableBody]) -> str:
        hasher = hashlib.sha256()
        for body in bodies:
            hasher.update(body.call_id.encode("utf-8", "replace"))
            hasher.update(b"\x00")
            hasher.update(body.text.encode("utf-8", "replace"))
            hasher.update(b"\x00")
        return hasher.hexdigest()[:16]

    def _remember_failure(self, fingerprint: str, failure: str) -> None:
        if not self._config.skip_unchanged_failed_input:
            return
        if fingerprint not in self._failed_inputs:
            self._failed_order.append(fingerprint)
        self._failed_inputs[fingerprint] = failure
        while len(self._failed_order) > 8:
            self._failed_inputs.pop(self._failed_order.pop(0), None)

    def _scope(
        self,
        bodies: Sequence[RetirableBody],
        question: str,
    ) -> ExtractionScope | None:
        """Ask the extractor whether this input can produce a citable record.

        A missing or raising probe yields ``None``, which means "unknown" and
        leaves the decision to the attempt itself: a broken probe must not become
        a silent reason never to archive.
        """
        probe = getattr(self._extractor, "scope", None)
        if not callable(probe):
            return None
        try:
            scope = probe(bodies, question)
        except Exception as exc:
            logger.warning("reading extractor scope probe failed: %s", exc)
            return None
        return scope if isinstance(scope, ExtractionScope) else None

    def _budget_snapshot(self) -> tuple[float | None, float | None, float | None]:
        """Return ``(remaining, reserve, usable)``; any element may be unknown."""
        remaining: float | None = None
        try:
            raw = self._budget.remaining_s()
        except Exception:
            raw = None
        if raw is not None:
            try:
                remaining = max(0.0, float(raw))
            except (TypeError, ValueError):
                remaining = None
        reserve: float | None = None
        provider = self._budget.delivery_reserve_s
        if provider is not None:
            try:
                value = provider()
            except Exception:
                value = None
            if value is not None:
                try:
                    reserve = max(0.0, float(value))
                except (TypeError, ValueError):
                    reserve = None
        usable = None if remaining is None else remaining - (reserve or 0.0)
        return remaining, reserve, usable

    def _collect_usage(self, totals: dict[str, int]) -> bool:
        """Fold one attempt's extraction usage into *totals*; False when unknown."""
        usage = getattr(self._extractor, "last_usage", None)
        if not isinstance(usage, dict) or not usage:
            return False
        for name, keys in (
            ("prompt_tokens", ("prompt_tokens", "input_tokens")),
            ("completion_tokens", ("completion_tokens", "output_tokens")),
            ("total_tokens", ("total_tokens",)),
            ("cache_read_tokens", ("cache_read_tokens", "cached_tokens")),
        ):
            for key in keys:
                value = usage.get(key)
                if value is None:
                    continue
                try:
                    totals[name] += int(value)
                except (TypeError, ValueError):
                    continue
                break
        if not totals.get("total_tokens"):
            totals["total_tokens"] = totals["prompt_tokens"] + totals["completion_tokens"]
        return True

    async def _finish(
        self,
        event: ReadingCheckpointEvent,
        emit: Callable[[ReadingCheckpointEvent], Awaitable[None]] | None,
    ) -> ReadingCheckpointEvent:
        self._record(event)
        if emit is not None:
            await emit(event)
        return event

    async def maybe_checkpoint(
        self,
        messages: list[Any],
        *,
        turn: int = 0,
        question: str = "",
        trigger: bool = False,
        emit: Callable[[ReadingCheckpointEvent], Awaitable[None]] | None = None,
    ) -> ReadingCheckpointEvent:
        """Run one checkpoint attempt. Never raises on extraction or storage.

        ``trigger`` forces an attempt even below the working-set limit — used by
        tests and by a caller that knows the reader is about to move on.

        ``emit`` receives the ``start`` event before the extractor is called and
        the ``end`` event after. A run that never returns therefore leaves a start
        record behind, instead of only an unexplained gap between two turns.

        ``CancelledError`` is deliberately not caught: a cancelled run must
        unwind, and the only thing it can leave behind is a persisted-but-not-
        installed record, which is the safe side.
        """
        cfg = self._config
        started = self._clock()
        if not cfg.enabled:
            return await self._finish(
                ReadingCheckpointEvent(triggered=False, reason="disabled", turn=turn),
                emit,
            )

        bodies = self._candidates(messages)
        working_set = sum(body.chars for body in bodies)
        if not bodies:
            return await self._finish(
                ReadingCheckpointEvent(
                    triggered=False,
                    reason="no_retirable_bodies",
                    turn=turn,
                    working_set_before=working_set,
                ),
                emit,
            )
        if not trigger and working_set < cfg.working_set_limit:
            return await self._finish(
                ReadingCheckpointEvent(
                    triggered=False,
                    reason="under_working_set_limit",
                    turn=turn,
                    working_set_before=working_set,
                ),
                emit,
            )

        resolved_question = question or _first_user_text(messages)
        scope = self._scope(bodies, resolved_question)
        remaining, reserve, usable = self._budget_snapshot()
        base = ReadingCheckpointEvent(
            triggered=True,
            turn=turn,
            working_set_before=working_set,
            body_count=len(bodies),
            digest_chars=None if scope is None else scope.digest_chars,
            digest_budget=None if scope is None else scope.digest_budget,
            ref_count=None if scope is None else scope.ref_count,
            omitted_bodies=None if scope is None else scope.omitted_bodies,
            remaining_budget_s=remaining,
            delivery_reserve_s=reserve,
        )

        # Declines that cost nothing. Each has its own reason so "never archived"
        # can be answered from the trace rather than inferred from silence.
        if scope is not None and not scope.applicable:
            return await self._finish(
                replace(
                    base,
                    triggered=False,
                    reason="input_not_applicable",
                    failure=scope.reason or "input_not_applicable",
                ),
                emit,
            )

        fingerprint = self._fingerprint(bodies)
        prior = self._failed_inputs.get(fingerprint)
        if prior:
            return await self._finish(
                replace(
                    base,
                    triggered=False,
                    reason="unchanged_input_after_failure",
                    failure=prior,
                ),
                emit,
            )

        if usable is not None and usable < cfg.min_remaining_budget_s:
            return await self._finish(
                replace(base, triggered=False, reason="skipped_insufficient_budget"),
                emit,
            )

        if emit is not None:
            await emit(replace(base, phase="start"))

        bounds = ExtractionBounds(
            record_limit=cfg.record_limit,
            max_findings=cfg.max_findings,
        )
        deadline = started + cfg.total_timeout_s
        if usable is not None:
            # Never spend past what the caller can afford after its delivery
            # reserve, even when total_timeout_s is larger.
            deadline = min(deadline, started + usable)
        failure = ""
        attempts: list[ReadingStageAttempt] = []
        usage_totals = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "cache_read_tokens": 0,
        }
        usage_reports = 0
        extractor_calls = 0
        for attempt in range(1, max(1, cfg.max_attempts) + 1):
            left = deadline - self._clock()
            if left <= 0:
                failure = "stage_timeout"
                if attempt > 1:
                    attempts.append(
                        ReadingStageAttempt(
                            index=attempt,
                            outcome="not_started",
                            detail=f"stage deadline exhausted ({left:.2f}s left)",
                        )
                    )
                break
            # A retry needs enough time to be worth starting, but never more than
            # half the stage's own budget: otherwise a stage configured with a
            # short total timeout can never afford its own single retry, and the
            # "two attempts" in the config is a number with no effect.
            attempt_floor = min(cfg.min_attempt_s, max(0.0, cfg.total_timeout_s * 0.5))
            if attempt > 1 and left < attempt_floor:
                # "Configured two attempts" is not "afforded two attempts".
                failure = "insufficient_attempt_budget"
                attempts.append(
                    ReadingStageAttempt(
                        index=attempt,
                        outcome="not_started",
                        detail=f"{left:.2f}s left < attempt floor {attempt_floor:.2f}s",
                    )
                )
                break

            attempt_started = self._clock()
            extractor_calls += 1
            try:
                candidate = await asyncio.wait_for(
                    self._extractor(bodies, resolved_question, bounds),
                    timeout=left,
                )
            except TimeoutError:
                failure = "extraction_timeout"
                attempts.append(
                    ReadingStageAttempt(
                        index=attempt,
                        duration_s=self._clock() - attempt_started,
                        outcome="extractor_timeout",
                        detail=f"no result within {left:.1f}s",
                    )
                )
                if self._collect_usage(usage_totals):
                    usage_reports += 1
                continue
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("reading extractor failed at turn %d: %s", turn, exc)
                failure = "extraction_failed"
                attempts.append(
                    ReadingStageAttempt(
                        index=attempt,
                        duration_s=self._clock() - attempt_started,
                        outcome="extractor_error",
                        detail=str(exc)[:200],
                    )
                )
                if self._collect_usage(usage_totals):
                    usage_reports += 1
                continue
            if self._collect_usage(usage_totals):
                usage_reports += 1

            if candidate is None or not getattr(candidate, "findings", None):
                # An empty record is a failed archive, not an empty victory.
                failure = "empty_record"
                attempts.append(
                    ReadingStageAttempt(
                        index=attempt,
                        duration_s=self._clock() - attempt_started,
                        outcome="empty_record",
                    )
                )
                # Retry narrower once: the extractor may simply have overreached.
                bounds = replace(bounds, max_findings=max(4, bounds.max_findings // 2))
                continue

            attached = self._attach_budget(candidate, bodies)
            index_floor = minimal_recoverable_index_chars(attached)
            if index_floor > self._config.archive_max_chars:
                # The index is the only thing the reader will have. If even the
                # addresses-only form cannot fit the budget the archive is enforced
                # against, installing would retire bodies behind an over-budget
                # message; nothing retires and the reason is recorded instead.
                installed = InstallOutcome(
                    installed=False,
                    checkpoint=attached,
                    issues=(
                        ValidationIssue(
                            "archive_index_over_budget",
                            f"{len(attached.findings)} 条发现的最小可恢复索引 "
                            f"{index_floor} 字符，超过归档预算 "
                            f"{self._config.archive_max_chars}；正文保留",
                        ),
                    ),
                )
            else:
                installed = install_checkpoint(
                    attached,
                    self._store,
                    resolve=self._resolve,
                    task_id=self._task_id or None,
                    source_versions=(
                        self._source_versions() if self._source_versions is not None else None
                    ),
                    statement_check=self._config.statement_check,
                )
            if installed.installed:
                attempts.append(
                    ReadingStageAttempt(
                        index=attempt,
                        duration_s=self._clock() - attempt_started,
                        outcome="installed",
                    )
                )
                end_base = replace(
                    base,
                    attempts=tuple(attempts),
                    usage=(usage_totals if usage_reports else None),
                    usage_known=usage_reports == extractor_calls,
                    duration_s=self._clock() - started,
                )
                return await self._finish(
                    self._commit(
                        messages,
                        installed,
                        bodies,
                        base=end_base,
                        working_set_before=working_set,
                        started=started,
                        attempt=attempt,
                    ),
                    emit,
                )
            failure = installed.reason or "not_installed"
            detail = installed.issues[0].detail if installed.issues else ""
            logger.info(
                "reading checkpoint rejected at turn %d: %s (%s)",
                turn,
                failure,
                detail,
            )
            attempts.append(
                ReadingStageAttempt(
                    index=attempt,
                    duration_s=self._clock() - attempt_started,
                    outcome=(
                        "write_failed" if failure == "archive_write_failed" else "validation_rejected"
                    ),
                    detail=f"{failure}: {detail}"[:200],
                )
            )
            if failure == "record_over_budget":
                # Retry with half the record budget instead of trimming findings
                # silently. If it still does not fit, the bodies stay.
                bounds = replace(
                    bounds,
                    record_limit=max(500, bounds.record_limit // 2),
                    max_findings=max(4, bounds.max_findings // 2),
                )
                continue
            break

        if failure:
            self._remember_failure(fingerprint, failure)
        return await self._finish(
            replace(
                base,
                reason="checkpoint_failed",
                installed=False,
                failure=failure,
                attempts=tuple(attempts),
                usage=(usage_totals if usage_reports else None),
                usage_known=usage_reports == extractor_calls,
                retired_chars=0,
                duration_s=self._clock() - started,
            ),
            emit,
        )

    def _attach_budget(
        self,
        candidate: ReadingCheckpoint,
        bodies: Sequence[RetirableBody],
    ) -> ReadingCheckpoint:
        """Record what was measured, without overwriting what the extractor knew.

        The record budget is the stage's to enforce (it decides whether the
        archive is allowed to exist); the working-set numbers are context for the
        trace. Neither is a threshold the extractor gets to relax.
        """
        if not candidate.checkpoint_id:
            candidate = replace(candidate, checkpoint_id=self._next_id())
        record_chars = sum(len(f.statement) for f in candidate.findings) + sum(
            len(ref) for f in candidate.findings for ref in f.evidence_refs
        )
        return replace(
            candidate,
            task_id=candidate.task_id or self._task_id,
            budget=CheckpointBudget(
                record_chars=record_chars,
                record_limit=max(1, self._config.record_limit),
                working_set_chars=sum(body.chars for body in bodies),
                working_set_limit=self._config.working_set_limit,
            ),
        )

    def _commit(
        self,
        messages: list[Any],
        outcome: InstallOutcome,
        bodies: Sequence[RetirableBody],
        *,
        base: ReadingCheckpointEvent,
        working_set_before: int,
        started: float,
        attempt: int,
    ) -> ReadingCheckpointEvent:
        """Replace the retired bodies and append the archive, once.

        Bodies are replaced by a short marker rather than deleted: a tool message
        without its pair breaks provider validation, and the marker is also what
        makes a second pass a no-op.
        """
        checkpoint = outcome.checkpoint
        marker = archive_marker(checkpoint.checkpoint_id)
        for body in bodies:
            source = messages[body.index]
            if not isinstance(source, dict):
                continue
            messages[body.index] = {
                **source,
                "content": json.dumps(
                    {"retired": True, "checkpoint": checkpoint.checkpoint_id, "note": marker},
                    ensure_ascii=False,
                ),
            }
        text, index_only = _render_archive(checkpoint, max_chars=self._config.archive_max_chars)
        messages.append({"role": "user", "content": text})

        self._checkpoint_ids.append(checkpoint.checkpoint_id)
        working_set_after = sum(
            len(message.get("content") or "")
            for message in messages
            if isinstance(message, dict) and message.get("role") == "tool"
        )
        return self._record(
            replace(
                base,
                reason="checkpoint_installed",
                installed=True,
                checkpoint_id=checkpoint.checkpoint_id,
                attempt=attempt,
                retired_calls=tuple(body.call_id for body in bodies),
                retired_chars=sum(body.chars for body in bodies),
                working_set_before=working_set_before,
                working_set_after=working_set_after,
                archive_chars=len(text),
                index_only=index_only,
                duration_s=self._clock() - started,
            )
        )

    def _record(self, event: ReadingCheckpointEvent) -> ReadingCheckpointEvent:
        self.last_event = event
        return event


def _first_user_text(messages: Sequence[Any]) -> str:
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()[:400]
    return ""


def build_index(checkpoint: ReadingCheckpoint) -> dict[str, Any]:
    """The persistent index an over-budget archive keeps.

    Small enough to stay resident, and sufficient to decide *whether* to fetch:
    finding ids, their refs, and which ranges are still unread. It contains no
    statement text, so it cannot be mistaken for the findings themselves.
    """
    return {
        "checkpoint_id": checkpoint.checkpoint_id,
        "question": checkpoint.question,
        "findings": [
            {"finding_id": f.finding_id, "kind": f.kind, "refs": list(f.evidence_refs)}
            for f in checkpoint.findings
        ],
        "unread": [
            {"source_id": r.source_id, "version": r.version, "start": r.start, "end": r.end}
            for r in checkpoint.coverage.unread_ranges
        ],
        "status": checkpoint.status,
        "schema_version": checkpoint.schema_version,
    }
