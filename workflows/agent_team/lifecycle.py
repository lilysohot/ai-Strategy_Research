"""Close member jobs before a stopped coordinator leaves its execution phase."""

from __future__ import annotations

import asyncio
import json
import logging
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
        return self.collected_count > 0 or self.run_status == "partial"

    def should_refresh_answer(self, result: AgentLoopResult) -> bool:
        """New evidence invalidates a draft; partial execution alone does not."""
        return self.collected_count > 0 or (
            self.requires_resynthesis
            and not is_user_report(
                str(result.metadata.get("final_answer_candidate") or result.final_content)
            )
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "collected_count": self.collected_count,
            "incomplete_count": self.incomplete_count,
            "queued_aborted": self.queued_aborted,
            "unresolved_count": self.unresolved_count,
            "run_status": self.run_status,
            "job_outcomes": self.job_outcomes,
            "untracked_work": self.untracked_work,
            "verification": self.verification,
        }


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
    status_block = (
        f'<report agent="orchestrator" status="{overall}" '
        f'reason="team_wind_down_{status}">\n'
        f"{guidance}\n"
        f"collected={len(collected)}; incomplete={incomplete_count}; "
        f"queued_aborted={queued_aborted}; unresolved={unresolved_count}.\n"
        f"Whole-run required job gaps: {json.dumps(required_gaps, ensure_ascii=False)}\n"
        f"Version-bound checks: {json.dumps(verification, ensure_ascii=False)}\n"
        "Do not upgrade raw tool observations or a resolved board item to a verification "
        "verdict. State precisely what was checked and what remains unchecked. "
        "Qualify each affected conclusion inline as observed fact, attributed claim, "
        "inference, or unknown. A failed fetch is not evidence of absence or equality. "
        "Do not assert a lowest price, identical cost or overall winner without matched "
        "versions, dates, units, conditions and coverage. A footer alone is insufficient.\n"
        "</report>"
    )
    checkpoint = "\n\n".join([*batch.blocks, status_block])
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
