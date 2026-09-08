"""ApprovalGate: the web-layer human-approval primitive (P3.2, §6.1).

The observer half (:class:`ApprovalObserver`) classifies each tool call with
apodex's own ``assess_with_rules`` (the single source of approval semantics —
no new parsing points) and, for ``confirm``-level calls, parks an asyncio
Future here and emits ``approval_requested``. The agent loop suspends on that
future (the LLM cannot advance) until the user's decision arrives over the
stdin JSONL channel::

    POST /api/runs/{id}/approve → orchestrator → stdin
      {"action":"approve","approval_id":...,"decision":...,
       "replacement_command"?} → worker._stdin_watch → gate.resolve

Safety contract (§6.1): a pending approval **times out fail-closed** — the
waiter receives ``reject`` and any late resolve for the same id is refused —
and a hard deny never reaches this gate at all (the observer blocks it before
any event is emitted), so no decision can bypass it.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apodex.agent_tools import RISK_DENY, RISK_SAFE, assess_with_rules
from frontier_agent.core.loop_types import ToolCallIntervention
from server.bridge import redact_deep
from server.events import make_event

# §6.1: a suspended approval must never hang the run forever; on timeout the
# gate fails closed (reject) and forgets the pending id.
DEFAULT_TIMEOUT_S = 300.0


@dataclass
class ApprovalDecision:
    """The user's verdict for one ``approval_id`` (§6.1 decision enum).

    ``replacement_command`` is the redirect instruction: when set together with
    ``reject`` it becomes the declined call's result so the model adapts on the
    next turn instead of retrying blindly (CLI ``[e] redirect`` semantics).
    """

    decision: str  # once | reject | session_bash | session_all | persist
    replacement_command: str | None = None


class ApprovalGate:
    """Maps ``approval_id → Future[ApprovalDecision]`` across threads.

    ``open``/``wait`` run on the loop; ``resolve`` may be called from the stdin
    reader thread, in which case the wakeup goes through
    ``loop.call_soon_threadsafe``.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[ApprovalDecision]] = {}
        # In-memory per-run allowlist (§6.1 session_bash / session_all; the
        # persist decision also lands here — this distribution owns no
        # cross-run rule store, so it grants for the rest of the run).
        self._session: set[str] = set()

    @staticmethod
    def _key(name: str, args: dict, scope: str) -> str:
        # session_bash remembers the EXACT command: prefix matching would let a
        # remembered "pytest -q" silently allow "pytest -q -x".
        if scope == "session_bash":
            return f"bash:{str(args.get('command', '')).strip()}"
        return f"tool:{name}"

    def remember(self, name: str, args: dict, scope: str) -> None:
        """Record a session-scoped allow for the rest of this run."""
        self._session.add(self._key(name, args, scope))

    def is_allowed(self, name: str, args: dict) -> bool:
        """True if this call was already allowed for the rest of the run."""
        return (
            f"tool:{name}" in self._session
            or f"bash:{str(args.get('command', '')).strip()}" in self._session
        )

    def open(self) -> str:
        """Register a pending approval and return its id."""
        aid = uuid.uuid4().hex
        self._pending[aid] = asyncio.get_running_loop().create_future()
        return aid

    async def wait(
        self,
        approval_id: str,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> ApprovalDecision:
        """Await the decision; on timeout fail closed to ``reject``."""
        fut = self._pending.get(approval_id)
        if fut is None:
            return ApprovalDecision(decision="reject")
        try:
            return await asyncio.wait_for(fut, timeout=timeout)
        except TimeoutError:
            return ApprovalDecision(decision="reject")
        finally:
            self._pending.pop(approval_id, None)

    def resolve(self, approval_id: str, decision: ApprovalDecision) -> bool:
        """Deliver a decision from any thread; ``False`` for unknown/spent ids."""
        fut = self._pending.get(approval_id)
        if fut is None or fut.done():
            return False
        loop = fut.get_loop()

        def _set() -> None:
            if not fut.done():
                fut.set_result(decision)

        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is loop:
            _set()
        else:
            loop.call_soon_threadsafe(_set)
        return True

    def reject_pending(self) -> None:
        """Fail-closed every pending approval (used when the run is stopping).

        Direction matters: a stop must never *approve* anything in flight — it
        rejects, the declined call is skipped, and the loop reaches the next
        turn boundary where ``pause_check`` lands the cooperative stop instead
        of suspending on the gate until its 300s timeout.
        """
        for aid in list(self._pending):
            self.resolve(aid, ApprovalDecision(decision="reject"))


class ApprovalObserver:
    """In-loop approval gate mirroring apodex's TerminalObserver semantics.

    Classification is delegated to apodex's own ``assess_with_rules`` — the
    single source of approval semantics, so no new deny/confirm parsing point
    is introduced (§6.1). A hard ``deny`` is blocked *before* any event is
    emitted, which is what makes it structurally unbypassable; a ``confirm``
    parks a future in the gate, emits ``approval_requested`` (redacted, like
    every SSE egress), and suspends the agent loop on it — the LLM cannot
    advance while the human decides. The synthetic skip texts intentionally
    match ``server.bridge._SYNTHETIC_RESULT_MARKERS`` so the terminal renders
    declined calls as skipped instead of clean successes.
    """

    critical: bool = True

    def __init__(
        self,
        gate: ApprovalGate,
        emit: Callable[[dict[str, Any]], None],
        cwd: str,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> None:
        self.gate = gate
        self._emit = emit
        self.cwd = cwd
        self.timeout = timeout

    async def on_tool_call(
        self,
        ctx: Any,
        tool_call: dict,
    ) -> ToolCallIntervention | None:
        del ctx  # unused; signature fixed by notify_tool_call
        name = str(tool_call.get("name", ""))
        args = tool_call.get("args", {}) or {}
        risk = assess_with_rules(name, args, self.cwd, rules=None)

        # Hard deny: never reaches the user prompt — no decision can bypass it.
        if risk.level == RISK_DENY:
            return ToolCallIntervention(
                skip_with_result=f"[blocked by safety policy: {risk.reason}]",
            )
        # Read-only, or already allowed for the rest of this run → no gate.
        if risk.level == RISK_SAFE or self.gate.is_allowed(name, args):
            return None

        # confirm: show the human exactly what will run, then suspend.
        preview = ""
        if name == "bash":
            preview = str(args.get("command", "")).strip()
        approval_id = self.gate.open()
        self._publish(
            "approval_requested",
            approval_id=approval_id,
            tool_name=name,
            target=risk.target,
            reason=risk.reason,
            preview=preview,
            risk="high" if risk.danger else "normal",
        )
        decision = await self.gate.wait(approval_id, timeout=self.timeout)
        self._publish(
            "approval_resolved",
            approval_id=approval_id,
            decision=decision.decision,
        )

        if decision.decision == "reject":
            # Redirect feedback becomes the declined call's result so the model
            # adapts next turn instead of retrying blindly (CLI ``[e]``).
            if decision.replacement_command:
                return ToolCallIntervention(
                    skip_with_result=(
                        f"[The user declined to run this {name} call. "
                        f"Follow their instruction instead: "
                        f"{decision.replacement_command}]"
                    ),
                )
            return ToolCallIntervention(
                skip_with_result=f"[user rejected this {name} call — task stopped]",
            )

        # once | session_bash | session_all | persist → the call executes.
        if decision.decision != "once":
            self.gate.remember(name, args, scope=decision.decision)
        return None

    def _publish(self, type_: str, **data: Any) -> None:
        # §7 出口统一脱敏: every string crossing to the SSE layer is masked,
        # same as BridgeObserver / the replay path.
        self._emit(redact_deep(make_event(type_, **data)))
