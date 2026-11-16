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
import json
import logging
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from frontier_agent.core.runtime.reading.contract import (
    CheckpointBudget,
    Finding,
    FindingKind,
    InstallOutcome,
    ReadingCheckpoint,
    ReadingCheckpointStore,
    install_checkpoint,
)

logger = logging.getLogger(__name__)

__all__ = [
    "ExtractionBounds",
    "ReadingCheckpointEvent",
    "ReadingStage",
    "ReadingStageConfig",
    "RetirableBody",
    "archive_marker",
    "is_retired_body",
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


class CheckpointExtractor(Protocol):
    """Turns verbatim bodies into a candidate record.

    Implemented by the workflow layer, which is the only layer that knows what an
    evidence ref is. Raising, timing out, or returning an empty record are all
    ordinary outcomes: the stage treats each as "not installed" and keeps the
    bodies.
    """

    async def __call__(
        self,
        bodies: Sequence[RetirableBody],
        question: str,
        bounds: ExtractionBounds,
    ) -> ReadingCheckpoint: ...


@dataclass(frozen=True)
class ReadingStageConfig:
    """The stage's own budget, deliberately independent of the global threshold.

    ``working_set_limit`` is what decides *when* to checkpoint, and it is a
    property of reading volume, not of window occupancy. ``keep_recent_messages``
    is the guard against retiring something the model has not consumed yet: the
    tail of the history belongs to the turn in flight.
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


@dataclass(frozen=True)
class ReadingCheckpointEvent:
    """What one stage run did, for the trace.

    ``reason`` is set on every run, including the runs that did nothing — "no
    checkpoint because the working set was small" is information, and its absence
    is what makes growth impossible to explain after the fact.
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

    # One line of instruction, not a banner: the refs above are only useful if the
    # reader knows they are the way back to the exact words. Naming no tool keeps
    # this layer domain-neutral. Counted against the same budget as the findings —
    # a hint that pushes the archive over its own cap is still over its cap.
    recovery_hint = "需要逐字原文时，用 evidence_ref 定点补读该片段，不要整篇重读。"
    text = "\n".join([header, *lines, *tail])
    if len(text) + len(recovery_hint) + 1 <= max_chars:
        return f"{text}\n{recovery_hint}", False

    index_lines = [header, f"（归档超出预算，仅保留索引：{len(checkpoint.findings)} 条发现）"]
    index_lines.extend(
        f"- {finding.finding_id} {finding.kind} refs: {len(finding.evidence_refs)}"
        for finding in checkpoint.findings
    )
    index_lines.extend(tail)
    index_lines.append("按 evidence_ref 定点恢复原文，不要整篇重读。")
    return "\n".join(index_lines), True


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
    ) -> None:
        self._extractor = extractor
        self._store = store
        self._config = config or ReadingStageConfig()
        self._task_id = task_id
        self._resolve = resolve
        self._source_versions = source_versions
        self._clock = clock
        self._sequence = 0
        self._checkpoint_ids: list[str] = []
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

    async def maybe_checkpoint(
        self,
        messages: list[Any],
        *,
        turn: int = 0,
        question: str = "",
        trigger: bool = False,
    ) -> ReadingCheckpointEvent:
        """Run one checkpoint attempt. Never raises on extraction or storage.

        ``trigger`` forces an attempt even below the working-set limit — used by
        tests and by a caller that knows the reader is about to move on.

        ``CancelledError`` is deliberately not caught: a cancelled run must
        unwind, and the only thing it can leave behind is a persisted-but-not-
        installed record, which is the safe side.
        """
        cfg = self._config
        started = self._clock()
        if not cfg.enabled:
            return self._record(
                ReadingCheckpointEvent(
                    triggered=False,
                    reason="disabled",
                    turn=turn,
                )
            )

        bodies = self._candidates(messages)
        working_set = sum(body.chars for body in bodies)
        if not bodies:
            return self._record(
                ReadingCheckpointEvent(
                    triggered=False,
                    reason="no_retirable_bodies",
                    turn=turn,
                    working_set_before=working_set,
                )
            )
        if not trigger and working_set < cfg.working_set_limit:
            return self._record(
                ReadingCheckpointEvent(
                    triggered=False,
                    reason="under_working_set_limit",
                    turn=turn,
                    working_set_before=working_set,
                )
            )

        resolved_question = question or _first_user_text(messages)
        bounds = ExtractionBounds(
            record_limit=cfg.record_limit,
            max_findings=cfg.max_findings,
        )
        deadline = started + cfg.total_timeout_s
        failure = ""
        for attempt in range(1, max(1, cfg.max_attempts) + 1):
            remaining = deadline - self._clock()
            if remaining <= 0:
                failure = "stage_timeout"
                break
            try:
                candidate = await asyncio.wait_for(
                    self._extractor(bodies, resolved_question, bounds),
                    timeout=remaining,
                )
            except TimeoutError:
                failure = "extraction_timeout"
                continue
            except Exception as exc:
                logger.warning("reading extractor failed at turn %d: %s", turn, exc)
                failure = "extraction_failed"
                continue

            if candidate is None or not getattr(candidate, "findings", None):
                # An empty record is a failed archive, not an empty victory.
                failure = "empty_record"
                # Retry narrower once: the extractor may simply have overreached.
                bounds = replace(bounds, max_findings=max(4, bounds.max_findings // 2))
                continue

            installed = install_checkpoint(
                self._attach_budget(candidate, bodies),
                self._store,
                resolve=self._resolve,
                task_id=self._task_id or None,
                source_versions=(
                    self._source_versions() if self._source_versions is not None else None
                ),
            )
            if installed.installed:
                return self._commit(
                    messages,
                    installed,
                    bodies,
                    turn=turn,
                    working_set_before=working_set,
                    started=started,
                    attempt=attempt,
                )
            failure = installed.reason or "not_installed"
            detail = installed.issues[0].detail if installed.issues else ""
            logger.info(
                "reading checkpoint rejected at turn %d: %s (%s)",
                turn,
                failure,
                detail,
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

        return self._record(
            ReadingCheckpointEvent(
                triggered=True,
                reason="checkpoint_failed",
                installed=False,
                failure=failure,
                turn=turn,
                working_set_before=working_set,
                retired_chars=0,
                duration_s=self._clock() - started,
            )
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
        turn: int,
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
            ReadingCheckpointEvent(
                triggered=True,
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
                turn=turn,
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
