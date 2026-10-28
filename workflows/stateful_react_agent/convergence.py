"""Bound exploration and retain tool-enabled citation repair before publication."""

from __future__ import annotations

import time
from typing import Any

from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.loop_types import (
    WALL_DEADLINE_MONOTONIC_KEY,
    BaseObserver,
    Intervention,
    LoopConfig,
    ToolCallIntervention,
    ToolResult,
    TurnContext,
    wall_deadline_remaining_s,
)
from frontier_agent.core.runtime.loop.llm_client import RUNAWAY_STATE_KEY
from frontier_agent.infra.wall_time_lease import (
    WALL_TIME_LEASE_SCOPE_KEY,
    RenewableWallTimeDeadline,
    RenewableWallTimeLease,
)
from plugins.tools.task_board import render_board, snapshot_tasks

DISCOVERY_TOOLS = frozenset(
    {
        "web_search",
        "corpus_search",
        "corpus_semantic_query",
        "corpus_inventory",
        "data_coverage",
    }
)
ACQUISITION_TOOLS = DISCOVERY_TOOLS | {"web_fetch", "corpus_fetch", "recover_result"}
FINALIZATION_MESSAGE = (
    "Enter finalization now. Do not expand the research scope or start new searches. "
    "Use acquired sources to answer the current user question. Only fetch exact evidence needed "
    "to repair citations; prefer evidence_ref over retyping quotes. Submit the evidence manifest, "
    "repair or remove unsupported claims, preserve required business validation, and write the "
    "answer. State unresolved limitations; do not invent facts or mark failed checks resolved. "
    "Do not wait for every optional task to succeed."
)

RESEARCH_BOARD_PROMPT = """

# Current research round
Begin with add_task for the current user request, or update_task to explicitly resume old work.
Create only tasks necessary to answer this user request. Historical tasks are archived;
update an old id only when explicitly continuing that work. Do not repeat completed research.
Each add_task item should include kind (research, verification, delivery), done_when (a finite
completion criterion), and gap (the exact unanswered question). Separate writing the answer
from gathering evidence. Do not add valuation, financial metrics or two-source checks unless
needed for the requested conclusion. Authoritative primary evidence can suffice.
After each acquisition batch, update the affected tasks before searching again: record notes,
evidence_refs and the remaining gap, or resolve with a completion basis. Source pointers on the
board are not verification verdicts. Cancel unnecessary work with an explicit reason.
Once necessary research is answered, repair essential citations and deliver. Partial delivery
with explicit limitations is allowed; do not keep searching just to make every row resolved.
Only mark delivery complete after the answer/artifact actually exists and publication checks pass.
"""


class ResearchConvergenceObserver(BaseObserver):
    """Workflow policy, independent of the generic kernel and model turn limit."""

    critical = True

    def __init__(self, *, research_s: float, reserve_s: float = 180) -> None:
        self._research_s = max(0.0, research_s)
        self._reserve_s = max(1.0, reserve_s)
        self._start = 0.0
        self._research_deadline: RenewableWallTimeDeadline | None = None
        self._lease: RenewableWallTimeLease | None = None
        self._lease_sequence = 0
        self._outer_deadline: float | RenewableWallTimeDeadline | None = None
        self._awaiting_plan = False
        self._phase_deadline: float | None = None
        self._phase_notice_pending = False
        self._checkpoint = False
        self._acquired = False
        self._recovered = False

    async def on_loop_start(self, config: LoopConfig) -> None:
        self._start = time.monotonic()
        scope = get_current_execution_scope()
        lease = (scope.metadata if scope else {}).get(WALL_TIME_LEASE_SCOPE_KEY)
        if isinstance(lease, RenewableWallTimeLease):
            self._lease = lease
            self._lease_sequence = lease.sequence
            self._research_deadline = lease.bind_duration(self._research_s)

    def _research_remaining(self) -> float:
        if self._research_deadline is not None:
            return self._research_deadline.remaining_s()
        return self._research_s - (time.monotonic() - self._start)

    def _enter(self, ctx: TurnContext, reason: str) -> Intervention | None:
        if self._phase_deadline is not None:
            return None
        available = wall_deadline_remaining_s()
        # Reserve marks the latest exploration boundary, not a second timer
        # that throws away already-budgeted repair/delivery time. The outer
        # loop deadline remains the hard bound, including on early completion.
        budget = available if available is not None else self._reserve_s
        self._phase_deadline = time.monotonic() + max(0.0, budget)
        scope = get_current_execution_scope()
        if scope is not None:
            # This only shortens the outer deadline; it never extends the hard wall.
            outer = scope.metadata.get(WALL_DEADLINE_MONOTONIC_KEY)
            if isinstance(outer, (int, float, RenewableWallTimeDeadline)):
                self._outer_deadline = outer
            scope.metadata[WALL_DEADLINE_MONOTONIC_KEY] = self._phase_deadline
        ctx.metadata["finalization_phase"] = True
        ctx.metadata["finalization_reason"] = reason
        return Intervention(inject_messages=[FINALIZATION_MESSAGE])

    async def on_before_llm(self, ctx: TurnContext) -> Intervention | None:
        if self._lease is not None and self._lease.sequence != self._lease_sequence:
            # Only an accepted live user addition may renew exploration. Restore
            # the same outer lease, never manufacture a new hard time allowance.
            self._lease_sequence = self._lease.sequence
            scope = get_current_execution_scope()
            if scope is not None and self._outer_deadline is not None:
                scope.metadata[WALL_DEADLINE_MONOTONIC_KEY] = self._outer_deadline
            self._phase_deadline = None
            self._phase_notice_pending = False
            self._checkpoint = False
            self._recovered = False
            self._awaiting_plan = True
            ctx.metadata.pop("finalization_phase", None)
            ctx.metadata.pop("finalization_reason", None)
        if self._phase_deadline is not None:
            if time.monotonic() >= self._phase_deadline:
                return Intervention(stop_reason="wall_deadline")
            if self._phase_notice_pending:
                self._phase_notice_pending = False
                return Intervention(inject_messages=[FINALIZATION_MESSAGE])
            return None
        if self._research_s and self._research_remaining() <= self._reserve_s:
            return self._enter(ctx, "time_reserve")
        tasks = snapshot_tasks(ctx.task_id)
        research = [t for t in tasks if t.get("kind", "research") == "research"]
        if (
            not self._awaiting_plan
            and research
            and all(t["resolution"] in ("resolved", "cancelled") for t in research)
        ):
            return self._enter(ctx, "research_complete")
        return None

    async def on_llm_response(self, ctx: TurnContext) -> Intervention | None:
        runaway = ctx.metadata.get(RUNAWAY_STATE_KEY) or {}
        if (
            self._acquired
            and not self._recovered
            and not ctx.tool_calls
            and not ctx.ai_text.strip()
            and runaway.get("last_call_reason") in {"reasoning_runaway", "reasoning_runaway_early"}
            and not runaway.get("last_call_recovered")
        ):
            # One continuation through the SAME tools and authorization observers.
            # Unlike tool-free rescue, this can repair a manifest and still must
            # satisfy the ordinary publication/business validation boundary.
            available = wall_deadline_remaining_s()
            if available is not None and available < 65:
                return None
            self._recovered = True
            entered = self._enter(ctx, "reasoning_recovery")
            return Intervention(
                inject_messages=(entered.inject_messages if entered else [FINALIZATION_MESSAGE]),
                continue_to_next_turn=True,
            )
        return None

    async def on_tool_call(
        self,
        ctx: TurnContext,
        tool_call: dict[str, Any],
    ) -> ToolCallIntervention | None:
        # A slow model request can cross the research boundary before tools start.
        # Check again here so that late searches cannot spend the delivery reserve.
        transition = await self.on_before_llm(ctx)
        if transition and transition.stop_reason:
            return ToolCallIntervention(
                skip_with_result="Finalization budget exhausted; preserve the existing result.",
                skip_is_error=True,
            )
        if transition and transition.inject_messages:
            self._phase_notice_pending = True
        name = tool_call.get("name", "")
        if name in DISCOVERY_TOOLS:
            if self._phase_deadline is not None:
                return ToolCallIntervention(
                    skip_with_result=FINALIZATION_MESSAGE, skip_is_error=True
                )
            if self._checkpoint:
                return ToolCallIntervention(
                    skip_with_result=(
                        "Before another search, use update_task to record what the acquired evidence "
                        "answered (notes/evidence_refs), resolve completed work, and name the specific "
                        "remaining gap. If no necessary gap remains, write the answer."
                    ),
                    skip_is_error=True,
                )
        return None

    async def on_tool_result(self, ctx: TurnContext, result: ToolResult) -> None:
        if result.name in {"add_task", "update_task"} and not result.is_error:
            self._awaiting_plan = False
        if result.name in ACQUISITION_TOOLS and not result.is_error:
            self._acquired = True
        if result.name == "update_task" and not result.is_error:
            updates = result.args.get("updates") or []
            if isinstance(updates, list) and any(
                isinstance(item, dict) and (item.get("notes") or item.get("gap"))
                for item in updates
            ):
                self._checkpoint = False

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        transition = await self.on_before_llm(ctx)
        if transition is not None:
            return transition
        if self._phase_deadline is None and any(
            call.get("name") in ACQUISITION_TOOLS for call in ctx.tool_calls
        ):
            self._checkpoint = True
            return Intervention(
                inject_messages=[
                    "Evidence checkpoint: update affected tasks now with completion basis and remaining "
                    "gap before further searches. Use evidence_refs; do not copy source quotes by hand.\n"
                    + render_board(ctx.task_id),
                ]
            )
        return None
