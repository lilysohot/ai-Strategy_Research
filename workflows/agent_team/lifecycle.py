"""Close member jobs before a stopped coordinator leaves its execution phase."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import Any, Literal

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.components.agent_bus.fan_in import (
    classify_completion,
    process_collected,
)
from frontier_agent.components.agent_bus.stop_signal import get_stop_registry
from frontier_agent.core.loop_types import AgentLoopResult
from frontier_agent.core.messages import assistant_msg, tool_msg
from plugins.tools._paths import mask_paths_in_output
from plugins.tools._verification import project_checks
from workflows.agent_team.final_report import is_user_report

logger = logging.getLogger(__name__)


TeamCompleteness = Literal["complete", "partial"]


@dataclass(frozen=True)
class TeamWindDown:
    """Durable result of the bounded fan-in before final synthesis."""

    status: TeamCompleteness
    checkpoint: str
    collected_count: int
    incomplete_count: int
    queued_aborted: int
    unresolved_count: int
    job_outcomes: list[dict[str, Any]] = field(default_factory=list)
    untracked_work: bool = True
    verification: dict[str, Any] = field(default_factory=dict)
    # Collected reports from jobs classified complete — the only arrivals that
    # can substantively change the answer body. Late failures, timeouts and
    # incomplete deliveries are status updates, not new evidence.
    new_evidence_count: int = 0

    @property
    def run_status(self) -> TeamCompleteness:
        """Whole-run execution coverage, distinct from the last fan-in batch."""
        if any(
            job["required"] and job.get("coverage_status", job["status"]) != "complete"
            for job in self.job_outcomes
        ):
            return "partial"
        if self.job_outcomes and not self.untracked_work:
            return "complete"
        # Legacy callers may supply counts without corresponding job records.
        return self.status

    @property
    def requires_resynthesis(self) -> bool:
        """Whether the coordinator's pre-fan-in draft is no longer final."""
        return self.new_evidence_count > 0 or self.run_status == "partial"

    def should_refresh_answer(self, result: AgentLoopResult) -> bool:
        """New evidence invalidates a draft; partial execution alone does not."""
        return self.new_evidence_count > 0 or (
            self.requires_resynthesis
            and not is_user_report(
                str(result.metadata.get("final_answer_candidate") or result.final_content)
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "collected_count": self.collected_count,
            "new_evidence_count": self.new_evidence_count,
            "incomplete_count": self.incomplete_count,
            "queued_aborted": self.queued_aborted,
            "unresolved_count": self.unresolved_count,
            "run_status": self.run_status,
            "job_outcomes": self.job_outcomes,
            "untracked_work": self.untracked_work,
            "verification": self.verification,
        }


#: The status summary is model-facing prompt text, not an audit record. The
#: complete ``job_outcomes`` / ``verification`` objects stay in wind-down
#: metadata and in the run artifacts; only a whitelist view is serialized here.
_STATUS_SUMMARY_CHAR_BUDGET = 8_000
_STATUS_REASON_CHAR_BUDGET = 160
_STATUS_MAX_JOB_GAPS = 20
_STATUS_MAX_CHECKS = 30

_KNOWN_STATUS_CODES = frozenset(
    {
        "complete",
        "completed",
        "incomplete",
        "failed",
        "aborted",
        "cancelled",
        "timed_out",
        "timeout",
        "running",
        "queued",
        "paused",
        "skipped",
    }
)
_FAILURE_CODES = (
    "llm_error",
    "wall_deadline",
    "synthesis_unavailable",
    "checkpoint_error",
    "wait_timeout",
    "budget_exhausted",
    "timed_out",
    "timeout",
    "aborted",
    "cancelled",
    "paused",
    "failed",
    "incomplete",
)

#: Internal handles the model never needs in status text. Mirrors the
#: whitelist principle in :mod:`plugins.corpus.projection`: a free-text note
#: can still carry a locator even when its enclosing field is allowlisted.
_INTERNAL_REF_RE = re.compile(
    r"\b(?:ce:[0-9a-f]{16,}|sref:[0-9a-f]{16,}|eref:[0-9a-f]{16,}:\d+|"
    r"(?:chunk|unit|cv2|cmeta|doc|build):[A-Za-z0-9_%.:/\-]{4,})",
    re.IGNORECASE,
)
_PHYSICAL_PATH_RE = re.compile(r"/(?:home|srv|tmp|var|root|Users)/[^\s\"'，。；)>\]]+")


def _safe_status_text(value: Any, limit: int = _STATUS_REASON_CHAR_BUDGET) -> str:
    """Shorten and scrub one note; never copy a locator or a host path through."""
    text = "" if value is None else str(value).strip()
    if not text:
        return ""
    text = _PHYSICAL_PATH_RE.sub("[path]", mask_paths_in_output(text))
    text = _INTERNAL_REF_RE.sub("[ref]", text)
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > limit:
        text = text[: max(limit - 1, 0)].rstrip() + "…"
    return text


def _status_code(value: Any) -> str:
    """Return a known execution status, or a short deterministic category."""
    text = str(value or "").strip().lower()
    if text in _KNOWN_STATUS_CODES:
        return text
    if "timed out" in text or "timeout" in text:
        return "timed_out"
    if "cancel" in text:
        return "cancelled"
    if "abort" in text:
        return "aborted"
    if "fail" in text or "error" in text:
        return "failed"
    return "incomplete"


def _failure_code(value: Any) -> str:
    """Map free-form failure prose to a short code; never replay the prose."""
    text = str(value or "").strip().lower()
    if not text:
        return "incomplete"
    for code in _FAILURE_CODES:
        if code in text:
            return code
    return "execution_error"


def _verdict_code(value: Any) -> str:
    text = str(value or "").strip().lower()
    return text if text in {"pass", "fail", "unchecked"} else "unchecked"


def _project_job_gap(job: dict[str, Any]) -> dict[str, Any]:
    """Whitelist one required job gap; checks are referenced by id only."""
    gap: dict[str, Any] = {
        "job_id": _safe_status_text(job.get("job_id"), 80),
        "agent": _safe_status_text(job.get("agent"), 80),
        "status": _status_code(job.get("status")),
        "reason": _failure_code(job.get("reason")),
    }
    check_ids = [
        _safe_status_text(check.get("check_id"), 80)
        for check in job.get("verification_checks") or []
        if isinstance(check, dict) and check.get("check_id")
    ]
    if check_ids:
        gap["check_ids"] = check_ids
    return gap


def _check_note(result: Any) -> str:
    """Keep the shortest existing failure note; fall back to no note at all."""
    if not isinstance(result, dict):
        return ""
    issues = result.get("unresolved_issues")
    if isinstance(issues, list):
        parts = [_safe_status_text(issue) for issue in issues[:2] if str(issue).strip()]
        if parts:
            return _safe_status_text("；".join(parts))
    return _safe_status_text(result.get("detail"))


def _project_check(check: dict[str, Any]) -> dict[str, Any]:
    """Whitelist one already-selected check version; verdict is not recomputed."""
    attempts = check.get("attempts") or []
    execution = attempts[-1].get("execution_status") if attempts else ""
    row: dict[str, Any] = {
        "check_id": _safe_status_text(check.get("check_id"), 80),
        "work_item_id": _safe_status_text(check.get("work_item_id"), 80),
        "binding_id": _safe_status_text(check.get("binding_id"), 64),
        "required": bool(check.get("required")),
        "verdict": _verdict_code(check.get("verdict")),
        "execution_status": _status_code(execution),
    }
    note = _check_note(check.get("result"))
    if note:
        row["note"] = note
    return row


def _job_gap_rank(job: dict[str, Any]) -> tuple[int, int, str]:
    return (
        0 if job.get("required") else 1,
        0
        if _status_code(job.get("status"))
        in {"failed", "timed_out", "timeout", "cancelled", "aborted"}
        else 1,
        str(job.get("job_id") or ""),
    )


def _check_rank(check: dict[str, Any]) -> tuple[int, int, str]:
    verdict = _verdict_code(check.get("verdict"))
    execution = _status_code(
        (check.get("attempts") or [{}])[-1].get("execution_status") if check.get("attempts") else ""
    )
    abnormal = verdict != "pass" or execution not in {"complete", "completed"}
    required = bool(check.get("required"))
    bucket = 0 if (required and abnormal) else (1 if required else 2)
    return (
        bucket,
        0 if verdict == "fail" else (1 if verdict == "unchecked" else 2),
        str(check.get("check_id") or ""),
    )


def _fit_rows(rows: list[dict[str, Any]], limit: int, budget: int) -> tuple[list[str], int]:
    """Fit whole JSON rows only; a serialized row is never cut in half."""
    shown: list[str] = []
    used = 0
    for row in rows[:limit]:
        line = json.dumps(row, ensure_ascii=False, separators=(",", ":"))
        cost = len(line) + 3  # "- " prefix and newline
        if used + cost > budget:
            break
        shown.append(f"- {line}")
        used += cost
    return shown, used


def render_team_status_summary(
    *,
    overall: str,
    status: str,
    guidance: str,
    collected_count: int,
    incomplete_count: int,
    queued_aborted: int,
    unresolved_count: int,
    verification_status: str,
    job_gaps: list[dict[str, Any]],
    checks: list[dict[str, Any]],
) -> str:
    """Render the bounded model-facing status block.

    Counts and ``overall`` come from the complete data before any projection.
    Only the displayed rows are capped; the full objects remain in wind-down
    metadata and the run artifacts.
    """
    ordered_gaps = sorted(job_gaps, key=_job_gap_rank)
    ordered_checks = sorted(checks, key=_check_rank)
    projected_gaps = [_project_job_gap(job) for job in ordered_gaps]
    projected_checks = [_project_check(check) for check in ordered_checks]

    head = [
        f'<report agent="orchestrator" status="{overall}" reason="team_wind_down_{status}">',
        guidance,
        f"collected={collected_count}; incomplete={incomplete_count}; "
        f"queued_aborted={queued_aborted}; unresolved={unresolved_count}.",
    ]
    tail = [
        "Do not upgrade raw tool observations or a resolved board item to a verification "
        "verdict. State precisely what was checked and what remains unchecked. "
        "Qualify each affected conclusion inline as observed fact, attributed claim, "
        "inference, or unknown. Missing evidence remains unknown. Keep claims within the "
        "conditions and coverage of their evidence, including in headings and summaries.",
        "</report>",
    ]
    fixed_cost = sum(len(line) + 1 for line in [*head, *tail])
    remaining = max(_STATUS_SUMMARY_CHAR_BUDGET - fixed_cost - 200, 0)
    # Reserve half the row budget for checks when both sections have content;
    # unused job-gap budget flows to checks rather than being wasted.
    job_budget = remaining if not projected_checks else remaining // 2
    shown_gaps, used_gaps = _fit_rows(projected_gaps, _STATUS_MAX_JOB_GAPS, job_budget)
    shown_checks, _ = _fit_rows(projected_checks, _STATUS_MAX_CHECKS, remaining - used_gaps)

    lines = [
        *head,
        f"Whole-run required job gaps: total={len(projected_gaps)}; "
        f"shown={len(shown_gaps)}; omitted={len(projected_gaps) - len(shown_gaps)}",
        *shown_gaps,
        f"Version-bound checks: total={len(projected_checks)}; "
        f"shown={len(shown_checks)}; omitted={len(projected_checks) - len(shown_checks)}; "
        f"status={verification_status}",
        *shown_checks,
        *tail,
    ]
    block = "\n".join(lines)
    while len(block) > _STATUS_SUMMARY_CHAR_BUDGET:
        # Defensive whole-row removal; never trim the serialized string.
        if shown_checks:
            shown_checks.pop()
        elif shown_gaps:
            shown_gaps.pop()
        else:
            break
        lines = [
            *head,
            f"Whole-run required job gaps: total={len(projected_gaps)}; "
            f"shown={len(shown_gaps)}; omitted={len(projected_gaps) - len(shown_gaps)}",
            *shown_gaps,
            f"Version-bound checks: total={len(projected_checks)}; "
            f"shown={len(shown_checks)}; omitted={len(projected_checks) - len(shown_checks)}; "
            f"status={verification_status}",
            *shown_checks,
            *tail,
        ]
        block = "\n".join(lines)
    return block


def _has_obtained_content(result: Any) -> bool:
    """Whether a collected result carries mechanically evidenced content.

    Substantive means obtained sources (content acquisition receipts) or
    delivered corpus unit positions — page-receipt derived, never a model's
    own coverage claim.
    """
    metadata = getattr(result, "metadata", None) or {}
    acquisition = metadata.get("content_acquisition")
    if isinstance(acquisition, list) and any(
        isinstance(entry, dict) and entry.get("obtained") for entry in acquisition
    ):
        return True
    coverage = metadata.get("observed_unit_coverage")
    return isinstance(coverage, list) and bool(coverage)


def snapshot_job_outcomes(bus: AgentBus, task_id: str) -> list[dict[str, Any]]:
    """Read execution and evidence status without draining or mutating jobs."""
    job_outcomes: list[dict[str, Any]] = []
    for entry in bus.list_task_jobs(task_id):
        info = classify_completion(entry.result) if entry.result is not None else None
        metadata = entry.result.metadata if entry.result is not None else {}
        source = str(metadata.get("final_answer_source") or "")
        completion = info.status if info is not None else "incomplete"
        reason = info.reason if info is not None else entry.status
        if completion == "complete" and source in {
            "tool_observations",
            "collected_reports",
            "collected_report_fallback",
            "deterministic_fallback",
        }:
            completion, reason = "incomplete", "synthesis_unavailable"
        job_outcomes.append(
            {
                "job_id": entry.job_id,
                "agent": entry.session_id.rsplit("::", 1)[-1],
                "required": entry.item.metadata.get("required_for_completion") is not False,
                "status": completion,
                "reason": reason,
                "source": source,
                "content_acquisition": list(metadata.get("content_acquisition") or []),
                "verification_checks": list(entry.item.metadata.get("verification_checks") or []),
                "verification_events": list(entry.item.metadata.get("verification_events") or []),
            }
        )

    return job_outcomes


_OBSERVATION_SOURCES = frozenset(
    {
        "tool_observations",
        "collected_reports",
        "collected_report_fallback",
        "deterministic_fallback",
    }
)


def _member_report_kind(
    item_metadata: dict[str, Any],
    result_metadata: dict[str, Any],
) -> str:
    """Classify from declared task metadata, never from the member's name."""
    source = str(result_metadata.get("final_answer_source") or "")
    if item_metadata.get("verification_checks") or item_metadata.get("uses_publication_budget"):
        return "verification"
    if source in _OBSERVATION_SOURCES:
        return "tool_receipt"
    if (
        item_metadata.get("bound_research")
        or item_metadata.get("work_item_ids")
        or item_metadata.get("work_item_contracts")
    ):
        return "research"
    return "unknown"


_BLOCK_JOB_RE = re.compile(r'\bjob="([^"]+)"')


def _verification_job_ids(bus: AgentBus, task_id: str) -> set[str]:
    """Jobs whose bodies are verification receipts, not member research."""
    return {
        entry.job_id
        for entry in bus.list_task_jobs(task_id)
        if entry.item.metadata.get("verification_checks")
        or entry.item.metadata.get("uses_publication_budget")
    }


def _without_verification_blocks(
    blocks: list[str],
    verification_job_ids: set[str],
) -> list[str]:
    """Drop full verification receipts; the status block keeps their verdicts."""
    kept: list[str] = []
    for block in blocks:
        match = _BLOCK_JOB_RE.search(block[:400])
        if match and match.group(1) in verification_job_ids:
            continue
        kept.append(block)
    return kept


def snapshot_member_reports(bus: AgentBus, task_id: str) -> list[dict[str, Any]]:
    """Read complete member reports from existing job results, without draining.

    The records are intentionally transient: they are passed straight to the
    terminal fallback and never re-injected into the coordinator context. A
    missing result still yields a job record so a message-only report can be
    classified and deduplicated by ``job_id``.
    """
    reports: list[dict[str, Any]] = []
    for entry in bus.list_task_jobs(task_id):
        try:
            result = entry.result
            metadata = result.metadata if result is not None else {}
            info = classify_completion(result) if result is not None else None
            item_metadata = entry.item.metadata or {}
            reports.append(
                {
                    "job_id": entry.job_id,
                    "agent": entry.session_id.rsplit("::", 1)[-1],
                    "status": info.status if info is not None else entry.status,
                    "reason": str(info.reason if info is not None else entry.status),
                    "kind": _member_report_kind(item_metadata, metadata),
                    "content": str(result.final_content) if result is not None else "",
                    "source": str(metadata.get("final_answer_source") or ""),
                    "work_item_ids": [
                        str(item) for item in item_metadata.get("work_item_ids") or []
                    ],
                    "verification_checks": list(item_metadata.get("verification_checks") or []),
                    "verification_events": list(item_metadata.get("verification_events") or []),
                }
            )
        except Exception:
            logger.warning(
                "Skipping unreadable member result %s for terminal fallback",
                getattr(entry, "job_id", "?"),
                exc_info=True,
            )
    return reports


async def wind_down_team(
    *,
    bus: AgentBus,
    task_id: str,
    wait_s: float,
) -> TeamWindDown:
    """Freeze dispatch and collect reports that land within a short grace.

    This runs after the coordinator research loop and before final synthesis.
    It never launches work: queued tasks are aborted, running tasks may only
    finish their current work, and every ready result is converted into the
    same report blocks used by ``collect_reports``.
    """
    sessions = bus.list_sessions_for_task(task_id)
    outstanding_at_freeze = sum(
        len(session.pending_results)
        + len(session.pending_tasks)
        + int(session.current_job_id is not None)
        for session in sessions
    )
    queued_aborted = bus.freeze_task_dispatch(task_id)
    for session in sessions:
        if session.current_job_id:
            get_stop_registry().request_stop(session.session_id, session.current_job_id)
    collected = []
    deadline = time.monotonic() + max(float(wait_s), 0.0)

    while True:
        # Always drain already-published results, including all reports that
        # became ready together. Only the first empty poll may block.
        outcome = await bus.wait_any_session_detailed(task_id, timeout=0)
        if outcome.result is not None:
            collected.append(outcome.result)
            continue

        remaining = deadline - time.monotonic()
        has_running = any(
            session.current_job_id is not None for session in bus.list_sessions_for_task(task_id)
        )
        if remaining <= 0 or not has_running:
            break
        outcome = await bus.wait_any_session_detailed(
            task_id,
            timeout=remaining,
        )
        if outcome.result is not None:
            collected.append(outcome.result)
            continue
        break

    # Stop and checkpoint unfinished loops BEFORE synthesis. Cleanup after final
    # publication is too late: completed tool observations would never reach it.
    running = [
        session.current_job_id
        for session in bus.list_sessions_for_task(task_id)
        if session.current_job_id
    ]
    if running:
        try:
            await asyncio.wait_for(
                asyncio.gather(*(bus.abort(job_id) for job_id in running)),
                timeout=5.0,
            )
        except TimeoutError:
            logger.warning("Team checkpoint cancellation exceeded grace (task=%s)", task_id)
        while True:
            outcome = await bus.wait_any_session_detailed(task_id, timeout=0)
            if outcome.result is None:
                break
            collected.append(outcome.result)

    batch = process_collected(bus, task_id, collected)
    infos = [classify_completion(result) for _, result in collected]
    unresolved_count = sum(
        len(session.pending_results)
        + len(session.pending_tasks)
        + int(session.current_job_id is not None)
        for session in bus.list_sessions_for_task(task_id)
    )
    accounted = len(collected) + queued_aborted + unresolved_count
    incomplete_count = sum(info.status != "complete" for info in infos)
    # Substantive arrivals: reports from completed jobs, plus salvaged content
    # from aborted members whose tool observations actually obtained sources
    # (cancellation salvage) or delivered corpus units. Failed or timed-out
    # deliveries that carry no obtained content are status updates only.
    new_evidence_count = sum(
        info.status == "complete" or _has_obtained_content(result)
        for info, result in zip(infos, (entry[1] for entry in collected), strict=True)
    )
    status: TeamCompleteness = (
        "partial"
        if (
            queued_aborted
            or unresolved_count
            or incomplete_count
            or accounted < outstanding_at_freeze
        )
        else "complete"
    )

    job_outcomes = snapshot_job_outcomes(bus, task_id)

    verification = project_checks(job_outcomes)
    required_gaps = [
        j
        for j in job_outcomes
        if j["required"] and j.get("coverage_status", j["status"]) != "complete"
    ]
    known_jobs = {job["job_id"] for job in job_outcomes}
    untracked_work = (
        accounted < outstanding_at_freeze
        or bool(outstanding_at_freeze and not job_outcomes)
        or any(result.job_id not in known_jobs for _, result in collected)
        or any(
            session.current_job_id and session.current_job_id not in known_jobs
            for session in bus.list_sessions_for_task(task_id)
        )
    )
    overall = (
        "partial"
        if required_gaps
        else ("complete" if job_outcomes and not untracked_work else status)
    )
    if overall == "complete":
        guidance = (
            "All member work outstanding at the synthesis boundary was "
            "collected. Execution completion is not proof of factual verification."
        )
    else:
        guidance = (
            "Team coverage is incomplete. Preserve verified findings, but do "
            "not claim exhaustive coverage or definitive aggregate totals "
            "unless a collected report directly verifies them."
        )
    status_block = render_team_status_summary(
        overall=overall,
        status=status,
        guidance=guidance,
        collected_count=len(collected),
        incomplete_count=incomplete_count,
        queued_aborted=queued_aborted,
        unresolved_count=unresolved_count,
        verification_status=str(verification.get("status") or "not_assessed"),
        job_gaps=required_gaps,
        checks=list(verification.get("checks") or []),
    )
    checkpoint = "\n\n".join(
        [
            *_without_verification_blocks(
                batch.blocks,
                _verification_job_ids(bus, task_id),
            ),
            status_block,
        ]
    )
    logger.info(
        "Team wind-down (task=%s): status=%s collected=%d incomplete=%d "
        "queued_aborted=%d unresolved=%d wait_s=%.3f",
        task_id,
        status,
        len(collected),
        incomplete_count,
        queued_aborted,
        unresolved_count,
        max(float(wait_s), 0.0),
    )
    return TeamWindDown(
        status=status,
        checkpoint=checkpoint,
        collected_count=len(collected),
        new_evidence_count=new_evidence_count,
        incomplete_count=incomplete_count,
        queued_aborted=queued_aborted,
        unresolved_count=unresolved_count,
        job_outcomes=job_outcomes,
        untracked_work=untracked_work,
        verification=verification,
    )


def append_team_wind_down_checkpoint(
    result: AgentLoopResult,
    wind_down: TeamWindDown,
) -> None:
    """Append a protocol-valid synthetic fan-in call/result to history."""
    result.metadata["team_wind_down"] = wind_down.as_dict()
    if not wind_down.requires_resynthesis:
        return
    call_id = "team_wind_down_checkpoint"
    result.messages.append(
        assistant_msg(
            "",
            tool_calls=[
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "collect_reports",
                        "arguments": json.dumps({"phase": "wind_down"}),
                    },
                }
            ],
        )
    )
    result.messages.append(tool_msg(wind_down.checkpoint, call_id))


async def run_with_member_cleanup(
    execution: Awaitable[AgentLoopResult],
    *,
    bus: AgentBus,
    task_id: str,
) -> AgentLoopResult:
    """Retain normal fan-in; cancel members on pause, failure or cancellation."""
    completed = False
    try:
        result = await execution
        completed = result.stopped_by != "paused"
        return result
    finally:
        if not completed:
            try:
                await asyncio.wait_for(bus.cleanup_task(task_id), timeout=15)
            except Exception:
                logger.exception("Team stop cleanup failed (task=%s)", task_id)
