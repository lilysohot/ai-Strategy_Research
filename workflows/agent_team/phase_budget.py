"""Absolute phase boundaries for one Agent Team workflow run."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.loop_types import (
    WALL_DEADLINE_MONOTONIC_KEY,
    Intervention,
    LoopConfig,
    TurnContext,
)


@dataclass(frozen=True)
class TeamPhaseBudget:
    """One immutable deadline plan shared by coordinator tools and members."""

    started_monotonic_s: float
    research_dispatch_deadline_s: float | None
    research_deadline_s: float | None
    publication_deadline_s: float | None
    finalization_deadline_s: float | None
    state: dict[str, Any]

    @staticmethod
    def _remaining(deadline: float | None, now: float | None = None) -> float | None:
        if deadline is None:
            return None
        current = time.monotonic() if now is None else float(now)
        return float(deadline) - current

    def sync_phase(self, now: float | None = None) -> str:
        """Advance time-driven phases without reversing publication."""
        current = time.monotonic() if now is None else float(now)
        phase = str(self.state.get("phase") or "research")
        if phase == "publishing":
            if (
                self.publication_deadline_s is not None
                and current >= self.publication_deadline_s
            ):
                self.state["phase"] = "finalizing"
                return "finalizing"
            return phase
        if phase == "finalizing":
            return phase
        if self.publication_deadline_s is not None and current >= self.publication_deadline_s:
            phase = "finalizing"
        elif self.research_deadline_s is not None and current >= self.research_deadline_s:
            phase = "consolidating"
        elif (
            self.research_dispatch_deadline_s is not None
            and current >= self.research_dispatch_deadline_s
        ):
            phase = "draining"
        else:
            phase = "research"
        self.state["phase"] = phase
        return phase

    def can_dispatch_research(self, now: float | None = None) -> bool:
        return self.sync_phase(now) == "research"

    def can_dispatch_publication(self, now: float | None = None) -> bool:
        return self.sync_phase(now) in {"research", "draining", "consolidating", "publishing"}

    def deadline_for_job(self, *, can_publish: bool) -> float | None:
        return self.publication_deadline_s if can_publish else self.research_deadline_s

    def remaining_for_job(self, *, can_publish: bool) -> float | None:
        return self._remaining(self.deadline_for_job(can_publish=can_publish))

    def wait_deadline(self, *, publication_pending: bool = False) -> tuple[str, float | None]:
        """Return the boundary a report wait must not cross."""
        phase = self.sync_phase()
        if phase == "publishing" or (
            publication_pending and phase in {"draining", "consolidating", "finalizing"}
        ):
            return phase, self.publication_deadline_s
        if phase == "research" and self.research_dispatch_deadline_s is not None:
            # Wake the coordinator when admission closes, even if every member
            # is still gathering distinct (non-repetitive) evidence.
            return phase, self.research_dispatch_deadline_s
        return phase, self.research_deadline_s

    def as_dict(self, now: float | None = None) -> dict[str, Any]:
        current = time.monotonic() if now is None else float(now)

        def elapsed(deadline: float | None) -> float | None:
            if deadline is None:
                return None
            return max(0.0, deadline - self.started_monotonic_s)

        return {
            "phase": self.sync_phase(current),
            "research_dispatch_s": elapsed(self.research_dispatch_deadline_s),
            "research_deadline_s": elapsed(self.research_deadline_s),
            "publication_deadline_s": elapsed(self.publication_deadline_s),
            "finalization_deadline_s": elapsed(self.finalization_deadline_s),
            "research_remaining_s": self._remaining(self.research_deadline_s, current),
            "publication_remaining_s": self._remaining(self.publication_deadline_s, current),
            "finalization_remaining_s": self._remaining(self.finalization_deadline_s, current),
        }


class TeamPhaseBudgetObserver:
    """Publish the fixed coordinator deadline and announce phase transitions."""

    critical = True

    def __init__(self, budget: TeamPhaseBudget, *, prompt_mode: str = "research") -> None:
        self.budget = budget
        self.prompt_mode = prompt_mode
        self._last_phase = "research"

    async def on_loop_start(self, config: LoopConfig) -> None:
        del config
        scope = get_current_execution_scope()
        deadline = self.budget.publication_deadline_s
        if scope is not None and deadline is not None:
            existing = scope.metadata.get(WALL_DEADLINE_MONOTONIC_KEY)
            if not isinstance(existing, (int, float)) or deadline < float(existing):
                scope.metadata[WALL_DEADLINE_MONOTONIC_KEY] = deadline
        self._last_phase = self.budget.sync_phase()

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        phase = self.budget.sync_phase()
        ctx.metadata["team_phase"] = phase
        if phase == "finalizing":
            return Intervention(
                stop_reason="wall_deadline",
                inject_messages=[
                    "The Agent Team publication window is closed. Stop all team "
                    "work now; the workflow will perform bounded final synthesis."
                ],
            )
        if ctx.metadata.get("team_delivery_started") or phase == self._last_phase:
            return None
        self._last_phase = phase
        if self.prompt_mode == "standard" and phase in {"draining", "consolidating"}:
            return Intervention(inject_messages=[
                "The research admission window is closed. Collect the available "
                "findings and finish the requested answer. Do not add optional "
                "research or a whole-answer audit. Complete only outstanding "
                "required checks with attached evidence and bounded scope; preserve "
                "unchecked items honestly. If files were requested, use the sole "
                "authorized publisher. Keep the board truthful and prepare delivery."
            ])
        if phase == "draining":
            return Intervention(inject_messages=[
                "Research admission is now closed. Do not create or assign new "
                "exploratory research. Members are entering their report handoff "
                "window. Collect their reports and dispatch final_verifier with "
                "bounded verification_checks using the reserved verification / "
                "publication window, before selecting the sole publisher if "
                "files are required."
            ])
        if phase == "consolidating":
            return Intervention(inject_messages=[
                "The research execution window is closed. Do not wait for more "
                "exploratory research. Collect preserved reports and consolidate "
                "available evidence. A bounded final_verifier assignment and its "
                "collect_reports wait are still allowed in the reserved "
                "verification / publication window. Then dispatch the sole "
                "publisher or finalize the text answer; disclose unfinished checks."
            ])
        return None


__all__ = ["TeamPhaseBudget", "TeamPhaseBudgetObserver"]
