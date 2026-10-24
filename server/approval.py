"""ApprovalGate: the web-layer human-approval primitive (P3.2, §6.1).

The observer half (:class:`ApprovalObserver`) starts with apodex's
``assess_with_rules`` classification, then applies the Web worker's
sandbox-aware promotion for reversible writes and non-destructive computation.
For remaining ``confirm``-level calls, it parks an asyncio
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
import threading
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apodex.agent_tools import (
    RISK_CONFIRM,
    RISK_DENY,
    RISK_SAFE,
    ToolRisk,
    assess_with_rules,
)
from frontier_agent.core.loop_types import ToolCallIntervention
from server.bridge import redact_deep
from server.events import make_event

# §6.1: a suspended approval must never hang the run forever; on timeout the
# gate fails closed (reject) and forgets the pending id.
DEFAULT_TIMEOUT_S = 300.0

# A Web research worker already executes inside one run's isolated workspace.
# Creating or replacing files there, and running non-destructive computation,
# are routine reversible work. Keeping them behind a five-minute human gate
# makes data analysis unable to finish. Unknown tools and destructive actions
# retain the shared apodex decision; hard denials are never downgraded.
_WEB_AUTO_APPROVED_MUTATIONS = frozenset(
    {
        "create_file",
        "download_file",
        "write_file",
        "file_editor_create",
        "file_editor_str_replace",
        # Appends an audit manifest under this run's own artifact directory.
        # It cannot mutate the corpus publication store.
        "corpus_submit_manifest",
    }
)


def assess_web_tool_risk(name: str, args: dict, cwd: str) -> ToolRisk:
    """Apply the Web run's sandbox-aware approval policy.

    The shared classifier remains authoritative for hard denials and danger
    detection. Web only removes confirmation from scoped, reversible writes
    and non-destructive shell computation. Deletion and every other dangerous
    shell classification continue to require an explicit decision.
    """
    risk = assess_with_rules(name, args, cwd, rules=None)
    if risk.level != RISK_CONFIRM:
        return risk
    if name in _WEB_AUTO_APPROVED_MUTATIONS:
        return ToolRisk(RISK_SAFE, "run-scoped reversible write", risk.target)
    if name == "bash" and not risk.danger:
        return ToolRisk(RISK_SAFE, "sandboxed non-destructive command", risk.target)
    return risk


@dataclass
class ApprovalDecision:
    """The user's verdict for one ``approval_id`` (§6.1 decision enum).

    ``replacement_command`` is the redirect instruction: when set together with
    ``reject`` it becomes the declined call's result so the model adapts on the
    next turn instead of retrying blindly (CLI ``[e] redirect`` semantics).

    ``source`` records **who produced the verdict** (F21): the fail-closed paths
    below all return ``decision="reject"``, and without this an operator could
    not tell "the user declined" from "the gate timed out" or "the run was
    stopped while this was pending" — the durable record would misattribute a
    decision the user never made. Values: ``user`` | ``timeout`` | ``stopped`` |
    ``unknown``.
    """

    decision: str  # once | reject | session_bash | session_all | persist
    replacement_command: str | None = None
    source: str = "user"


class ApprovalGate:
    """Maps ``approval_id → Future[ApprovalDecision]`` across threads.

    ``open``/``wait`` run on the loop; ``resolve`` may be called from the stdin
    reader thread, in which case the wakeup goes through
    ``loop.call_soon_threadsafe``.
    """

    def __init__(self) -> None:
        self._pending: dict[str, asyncio.Future[ApprovalDecision]] = {}
        self._closed = threading.Event()
        # The Web UI exposes one approval dialog. Multiple team members may
        # reach confirm-level tools concurrently, so serialize prompts at the
        # shared run gate instead of letting a later request overwrite the one
        # the user is currently deciding.
        self.confirmation_lock = asyncio.Lock()
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
        if self.closed:
            self._pending[aid].set_result(ApprovalDecision(decision="reject", source="stopped"))
        return aid

    @property
    def closed(self) -> bool:
        """A stopped Run can never open its approval gate again."""
        return self._closed.is_set()

    async def wait(
        self,
        approval_id: str,
        timeout: float = DEFAULT_TIMEOUT_S,
    ) -> ApprovalDecision:
        """Await the decision; on timeout fail closed to ``reject``."""
        fut = self._pending.get(approval_id)
        if fut is None:
            # No future to await: this id was never opened here, or it was
            # already spent. Never the user's verdict (F21).
            return ApprovalDecision(decision="reject", source="unknown")
        try:
            decision = await asyncio.wait_for(fut, timeout=timeout)
            if self.closed and decision.decision != "reject":
                return ApprovalDecision(decision="reject", source="stopped")
            return decision
        except TimeoutError:
            # Fail-closed is not the user rejecting: the durable record must
            # keep the two apart (F21).
            return ApprovalDecision(decision="reject", source="timeout")
        finally:
            self._pending.pop(approval_id, None)

    def resolve(self, approval_id: str, decision: ApprovalDecision) -> bool:
        """Deliver a decision from any thread; ``False`` for unknown/spent ids."""
        fut = self._pending.get(approval_id)
        if self.closed and decision.source != "stopped":
            return False
        if fut is None or fut.done():
            return False
        loop = fut.get_loop()

        def _set() -> None:
            if not fut.done():
                fut.set_result(
                    ApprovalDecision(decision="reject", source="stopped")
                    if self.closed and decision.decision != "reject"
                    else decision
                )

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
        self._closed.set()
        for aid in list(self._pending):
            self.resolve(aid, ApprovalDecision(decision="reject", source="stopped"))


class ApprovalObserver:
    """In-loop approval gate mirroring apodex's TerminalObserver semantics.

    Classification starts with apodex's own ``assess_with_rules`` and only
    promotes scoped reversible work after that shared policy has ruled out a
    hard denial or destructive danger. A hard ``deny`` is blocked *before* any event is
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
        source_meta: dict[str, Any] | None = None,
    ) -> None:
        self.gate = gate
        self._emit = emit
        self.cwd = cwd
        self.timeout = timeout
        self._source_meta = dict(source_meta or {})

    def for_subagent(self, agent_id: str) -> ApprovalObserver:
        """Share the run gate while stamping one member's approval events."""

        return ApprovalObserver(
            self.gate,
            self._emit,
            self.cwd,
            timeout=self.timeout,
            source_meta={"agent_id": agent_id, "agent_kind": "subagent"},
        )

    async def wait_for_tool_interrupt(self, ctx: Any, tool_call: dict) -> bool:
        """Wake parked collect_reports when the Web stdin reader closes the Run."""
        del ctx, tool_call
        while not self.gate.closed:
            await asyncio.sleep(0.1)
        return True

    async def on_tool_call(
        self,
        ctx: Any,
        tool_call: dict,
    ) -> ToolCallIntervention | None:
        del ctx  # unused; signature fixed by notify_tool_call
        if self.gate.closed:
            return ToolCallIntervention(
                skip_with_result="[user rejected this tool call: run stopped]"
            )
        name = str(tool_call.get("name", ""))
        args = tool_call.get("args", {}) or {}
        risk = assess_web_tool_risk(name, args, self.cwd)

        # Hard deny: never reaches the user prompt — no decision can bypass it.
        if risk.level == RISK_DENY:
            return ToolCallIntervention(
                skip_with_result=f"[blocked by safety policy: {risk.reason}]",
            )
        # Read-only, or already allowed for the rest of this run → no gate.
        if risk.level == RISK_SAFE or self.gate.is_allowed(name, args):
            return None

        async with self.gate.confirmation_lock:
            if self.gate.closed:
                return ToolCallIntervention(
                    skip_with_result="[user rejected this tool call: run stopped]",
                )
            # A preceding approval may have granted this exact call/tool for
            # the rest of the Run while this member waited for the dialog slot.
            if self.gate.is_allowed(name, args):
                return None
            return await self._request_confirmation(name=name, args=args, risk=risk)

    async def _request_confirmation(
        self,
        *,
        name: str,
        args: dict[str, Any],
        risk: ToolRisk,
    ) -> ToolCallIntervention | None:
        """Publish and resolve one confirmation while holding the run slot."""

        # confirm: show the human exactly what will run, then suspend.
        preview = ""
        if name == "bash":
            preview = str(args.get("command", "")).strip()
        approval_id = self.gate.open()
        if self.gate.closed:
            await self.gate.wait(approval_id, timeout=self.timeout)
            return ToolCallIntervention(
                skip_with_result="[user rejected this tool call: run stopped]"
            )
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
        # F21: ``source`` and the redirect text ride on the event so the parent
        # can persist what actually happened (user decline vs timeout vs stop,
        # and the instruction the user asked for instead).
        self._publish(
            "approval_resolved",
            approval_id=approval_id,
            decision=decision.decision,
            source=decision.source,
            replacement_command=decision.replacement_command,
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
        self._emit(redact_deep(make_event(type_, **data, **self._source_meta)))
