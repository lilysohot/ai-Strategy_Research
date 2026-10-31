"""One coordinator submission for final prose and validated task dispositions."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.loop_types import (
    BaseObserver,
    Intervention,
    ToolCallIntervention,
    ToolResult,
    TurnContext,
)
from frontier_agent.core.runtime import registry
from frontier_agent.core.tool import tool
from plugins.tools._bus_scope import SWARM_SCOPE_KEY, resolve_bus_task_id
from plugins.tools._deliverable_policy import output_write_directives
from plugins.tools._verification import work_item_verification_progress
from plugins.tools.finalize_answer import finalize_gate
from plugins.tools.task_board import (
    board_transaction,
    complete_delivery_tasks,
    in_planning,
    snapshot_tasks,
    update_task,
)
from workflows.agent_team.final_report import is_user_report
from workflows.agent_team.lifecycle import TeamWindDown, snapshot_job_outcomes, wind_down_team
from workflows.agent_team.phase_budget import TeamPhaseBudget


class FinalDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: StrictStr = Field(min_length=1)
    resolution: Literal["resolved", "blocked"]
    notes: StrictStr = Field(min_length=1, max_length=2000)
    gap: StrictStr = Field(default="", max_length=2000)


@tool
async def deliver_answer(content: str, updates: list[FinalDisposition]) -> str:
    """Submit the complete final answer AND task dispositions in one call.

    Do not spend a separate generation updating the board first. Research with
    unmet done_when or unpassed required checks must be blocked, with notes and
    gap; never claim success from execution alone. Disclose gaps in the answer.
    Delivery tasks complete with acceptance. Call this tool alone.

    Args:
        content: Complete user-facing answer, with sources and explicit limitations.
        updates: Final dispositions for outstanding work. Use [] if none remain.
    """
    scope = get_current_execution_scope()
    if scope is None or SWARM_SCOPE_KEY not in scope.metadata or in_planning(scope.task_id):
        raise ValueError("Final delivery requires an executing team coordinator")
    if not is_user_report(content):
        raise ValueError("Provide the final answer body, not an empty/internal tool payload")
    items = [FinalDisposition.model_validate(u).model_dump() for u in updates]
    if len({u["id"] for u in items}) != len(items):
        raise ValueError("Each task may have only one final disposition")
    bus = registry.get_optional(AgentBus)
    bus_id = resolve_bus_task_id(scope)
    if bus and any(
        s.current_job_id or s.pending_tasks or s.pending_results
        for s in bus.list_sessions_for_task(bus_id)
    ):
        raise ValueError("Collect or stop outstanding members before final delivery")
    outcomes = {j["job_id"]: j for j in snapshot_job_outcomes(bus, bus_id)} if bus else {}
    tasks = {t["id"]: t for t in snapshot_tasks(scope.task_id)}
    for item in items:
        if item["resolution"] == "resolved":
            for job_id in tasks.get(item["id"], {}).get("execution_job_ids", []):
                if outcomes.get(job_id, {}).get("status") != "complete":
                    raise ValueError(
                        f"{item['id']}: member work incomplete; use blocked with a gap"
                    )
    # update_task performs no asynchronous I/O. Its existing verification checks
    # remain authoritative, and rejected partial mutations/receipts roll back.
    with board_transaction(scope.task_id):
        if items:
            receipt = await update_task.func(items)
            if receipt.startswith("Error:") or "\nerrors:" in receipt:
                raise ValueError(receipt)
        error = finalize_gate(scope.task_id, content, bus_task_id=bus_id)
        if error:
            raise ValueError(error)
        complete_delivery_tasks(scope.task_id)
    return "Final answer and task dispositions accepted."


deliver_answer.metadata["execution_barrier"] = True


class TeamDeliveryObserver(BaseObserver):
    """Move from gathered evidence to one final generation before time runs out."""

    critical = True

    def __init__(self, budget: TeamPhaseBudget) -> None:
        self.budget = budget
        self.active = False
        self.wind_down: TeamWindDown | None = None

    def _ready(self, bus: AgentBus, task_id: str, tasks: list[dict[str, Any]]) -> bool:
        if any(s.total_task_count == 0 for s in bus.list_sessions_for_task(task_id)):
            return False  # Respect explicitly created but not yet dispatched work.
        jobs = bus.list_task_jobs(task_id)
        if not jobs or any(j.status in {"queued", "submitted", "running"} for j in jobs):
            return False
        known = {j.job_id for j in jobs}
        for task in tasks:
            if task["resolution"] in {"resolved", "cancelled", "blocked"}:
                continue
            if task.get("kind") != "delivery" and (
                not task.get("execution_job_ids") or not set(task["execution_job_ids"]) <= known
            ):
                return False
            if (
                task.get("verification_required")
                and work_item_verification_progress(
                    bus,
                    task_id,
                    task["id"],
                    [c["check_id"] for c in task["verification_requirements"]],
                )["verification_execution_status"]
                != "complete"
            ):
                return False
        return True

    async def on_before_llm(self, ctx: TurnContext) -> Intervention | None:
        if self.active:
            return Intervention(
                inject_messages=[
                    "[team delivery] Correct the submission if needed. Use deliver_answer "
                    "alone with the final body and task dispositions; blocked work needs notes and gap."
                ],
                allowed_tool_names=("deliver_answer",),
            )
        if in_planning(ctx.task_id):
            return None
        scope = get_current_execution_scope()
        if scope is None:
            return None
        tasks = snapshot_tasks(ctx.task_id)
        if not tasks:
            return None
        now = time.monotonic()
        deadline = self.budget.publication_deadline_s
        remaining = deadline - now if deadline is not None else None
        reserve = (
            min(120.0, max(0.0, (deadline - self.budget.started_monotonic_s) * 0.2))
            if deadline is not None
            else 0.0
        )
        time_to_deliver = remaining is not None and 0 < remaining <= reserve
        turns_to_deliver = ctx.turn >= max(1, ctx.max_turns - 1)
        bus = registry.get_optional(AgentBus)
        bus_id = resolve_bus_task_id(scope)
        runtime = scope.metadata.get(SWARM_SCOPE_KEY)
        # Do not preempt an explicitly requested file publisher before time pressure.
        files_pending = (
            bool(output_write_directives(getattr(runtime, "original_question", "")))
            and not any(
                j.item.metadata.get("can_publish") and j.status == "completed"
                for j in bus.list_task_jobs(bus_id)
            )
            if bus
            else False
        )
        ready = bool(bus and not files_pending and self._ready(bus, bus_id, tasks))
        if not time_to_deliver and not turns_to_deliver and not ready:
            return None
        checkpoint = ""
        if bus:
            self.wind_down = await wind_down_team(bus=bus, task_id=bus_id, wait_s=0)
            checkpoint = self.wind_down.checkpoint
        self.active = True
        ctx.metadata["team_delivery_started"] = True
        ctx.metadata["team_delivery_reason"] = (
            "time_reserve"
            if time_to_deliver
            else "turn_reserve"
            if turns_to_deliver
            else "work_collected"
        )
        # This pre-request injection is recorded by the trajectory observer.
        prompt = (
            "[team delivery] Research and coordination are now closed. Submit the complete "
            "answer using deliver_answer(content, updates) in THIS generation. No separate "
            "board-update turn is needed. Judge each task against its done_when: resolved "
            "only if satisfied and required checks passed; otherwise blocked with notes and "
            "gap. Preserve those limits beside the affected conclusions. Do not equate a "
            "completed member job with verified findings. Missing files remain blocked. "
            "Keep the answer concise enough to finish within the remaining budget. "
            f"Publication time remaining: {max(0, deadline - time.monotonic()):.0f}s.\n"
            if deadline is not None
            else "[team delivery] Submit the answer and task dispositions together with deliver_answer. "
            "Use blocked with notes and gap for unfinished work.\n"
        )
        prompt += json.dumps(tasks, ensure_ascii=False)
        return Intervention(
            inject_messages=[checkpoint, prompt] if checkpoint else [prompt],
            allowed_tool_names=("deliver_answer",),
        )

    async def on_tool_call(
        self, ctx: TurnContext, tool_call: dict[str, Any]
    ) -> ToolCallIntervention | None:
        mixed = len(ctx.tool_calls) > 1 and any(
            c.get("name") == "deliver_answer" for c in ctx.tool_calls
        )
        if (
            mixed
            or ctx.metadata.get("team_delivery_accepted")
            or (self.active and tool_call.get("name") != "deliver_answer")
        ):
            return ToolCallIntervention(
                skip_with_result="Use deliver_answer alone, with the answer and all task dispositions.",
                skip_is_error=True,
            )
        return None

    async def on_tool_result(self, ctx: TurnContext, result: ToolResult) -> None:
        if result.name == "deliver_answer" and not result.is_error:
            ctx.metadata["final_answer"] = result.args["content"].strip()
            ctx.metadata["team_delivery_accepted"] = True

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        if ctx.metadata.get("team_delivery_accepted"):
            return Intervention(stop_reason="final_answer")
        return None
