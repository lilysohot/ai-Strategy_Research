"""Small, durable member handoffs instead of one late all-checks response."""

from __future__ import annotations

import json
import time
from typing import Any

from frontier_agent.core.loop_types import (
    BaseObserver,
    Intervention,
    ToolCallIntervention,
    TurnContext,
)


class MemberProgressObserver(BaseObserver):
    """Bound verification output; encourage an early, explicitly scoped research report."""

    critical = True

    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = metadata
        self.started = time.monotonic()
        self.handoff_offered = False

    def _pending(self) -> list[dict[str, Any]]:
        # Events are committed by submit_report only after binding validation.
        completed = {(e["check_id"], e["binding_id"])
                     for e in self.metadata.get("verification_events", [])}
        return [c for c in self.metadata.get("verification_checks", [])
                if (c["check_id"], c["binding_id"]) not in completed]

    async def on_before_llm(self, ctx: TurnContext) -> Intervention | None:
        if self.metadata.get("verification_checks"):
            pending = self._pending()
            if not pending:
                return None
            check = pending[0]
            return Intervention(inject_messages=[
                "[next verification check] Evaluate ONLY this check in this generation. "
                "Submit exactly one verification_result now, with a short content summary. "
                "Use the attached original excerpts directly when sufficient; fetch only missing "
                "conditions/context. Do not recopy source bodies or the full report. Keep each "
                "scope_assessment detail to one comparison sentence. State fail/unchecked when "
                "evidence is insufficient; never spend the response reconstructing missing evidence. "
                "evidence_keys must contain only the job/ref keys listed below; put corpus locators "
                "in method/detail, not evidence_keys. unresolved_issues belongs beside "
                "scope_assessment, not inside it. Completed results are checkpointed before "
                "the next check.\n" + json.dumps({
                    "check_id": check["check_id"], "binding_id": check["binding_id"],
                    "subject_sha256": check["subject"]["sha256"],
                    "criterion": check["criterion"],
                    "evidence_keys": [s["key"] for s in check["evidence"]],
                    "finish": len(pending) == 1,
                }, ensure_ascii=False)
            ])
        if (
            not self.handoff_offered and not self.metadata.get("can_publish")
            and time.monotonic() - self.started >= 90
            and len(ctx.metadata.get("corpus_evidence") or []) >= 2
        ):
            self.handoff_offered = True
            return Intervention(inject_messages=[
                "[early research handoff] You have source evidence. If it supports the core "
                "assigned findings, submit_report now so verification can overlap other research. "
                "Give a concise report with exact refs, material qualifications and explicit "
                "unresolved items. Do not wait for the research deadline, repeatedly search "
                "uncovered historical topics, or create an optional report file. If a load-bearing "
                "fact still lacks evidence, do one targeted lookup and then report what is known. "
                "An incomplete finding must remain an explicit gap, not a claim of completion."
            ])
        return None

    async def on_tool_call(
        self, ctx: TurnContext, tool_call: dict[str, Any],
    ) -> ToolCallIntervention | None:
        del ctx
        if not self.metadata.get("verification_checks") or tool_call.get("name") != "submit_report":
            return None
        args = tool_call.get("args") or {}
        results = args.get("verification_results") if isinstance(args, dict) else None
        pending = self._pending()
        if pending and (
            not isinstance(results, list) or len(results) != 1
            or not isinstance(results[0], dict)
            or results[0].get("check_id") != pending[0]["check_id"]
        ):
            return ToolCallIntervention(
                skip_with_result="Submit only the next pending check: " + pending[0]["check_id"],
                skip_is_error=True,
            )
        if pending:
            # Finalization observes these same args AFTER successful validation;
            # a rejected verdict cannot finish the job or advance this queue.
            return ToolCallIntervention(rewrite_args={**args, "finish": len(pending) == 1})
        return None
