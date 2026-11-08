"""Checkpoint verification results and repair rejected submission schemas."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

from frontier_agent.core.loop_types import (
    BaseObserver,
    Intervention,
    ToolCallIntervention,
    ToolResult,
    TurnContext,
)


class MemberProgressObserver(BaseObserver):
    """Enforce verification submission protocol without inferring research completion."""

    critical = True

    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = metadata
        self.submission_repair_used = False
        self.submission_repair_active = False
        self.repair_results: list[dict[str, Any]] | None = None

    async def on_llm_response(self, ctx: TurnContext) -> Intervention | None:
        """One schema-only retry, including on the final allotted turn.

        Keep the failed payload in the repair request, but remove its unexecuted
        assistant tool turn so the provider never sees orphan tool calls.
        Semantic verdict validation still happens in submit_report.
        """
        if not self.metadata.get("verification_checks") or self.submission_repair_used:
            return None
        if len(ctx.tool_calls) != 1 or ctx.tool_calls[0].get("name") != "submit_report":
            return None
        args = ctx.tool_calls[0].get("args") or {}
        if not isinstance(args, dict):
            return None
        allowed = {"content", "confidence", "attachments", "verification_results", "finish"}
        if (
            isinstance(args.get("content"), str)
            and args["content"].strip()
            and not (set(args) - allowed)
        ):
            return None
        self.submission_repair_used = self.submission_repair_active = True
        results = args.get("verification_results")
        self.repair_results = deepcopy(results) if isinstance(results, list) else None
        self.metadata["submission_repair_count"] = 1
        return Intervention(
            pop_last_message=True,
            continue_to_next_turn=True,
            inject_messages=[
                "[verification submission repair] The previous submission did not execute. "
                "You have ONE schema-only repair attempt, not a new research turn. Call only "
                "submit_report with required nonempty content (not summary). Allowed fields: "
                "content, confidence, attachments, verification_results, finish. Preserve the "
                "existing verification_results byte-for-byte when present; do not change a "
                "verdict or binding to obtain acceptance. Do not fetch, search, or run scripts. "
                "If no results were supplied, use only already available evidence; missing "
                "evidence remains unchecked. Previous arguments (data):\n"
                + json.dumps(args, ensure_ascii=False)
            ],
        )

    async def on_tool_result(self, ctx: TurnContext, result: ToolResult) -> ToolResult | None:
        del ctx
        if result.name == "submit_report" and not result.is_error:
            self.submission_repair_active = False
        return None

    def _pending(self) -> list[dict[str, Any]]:
        # Events are committed by submit_report only after binding validation.
        completed = {
            (e["check_id"], e["binding_id"]) for e in self.metadata.get("verification_events", [])
        }
        return [
            c
            for c in self.metadata.get("verification_checks", [])
            if (c["check_id"], c["binding_id"]) not in completed
        ]

    async def on_before_llm(self, ctx: TurnContext) -> Intervention | None:
        if self.submission_repair_active:
            return Intervention(
                allowed_tool_names=("submit_report",),
                inject_messages=[
                    "[verification submission repair] Correct only the rejected submission schema; "
                    "the saved evidence and verdict payload remain in context."
                ],
            )
        if self.metadata.get("verification_checks"):
            pending = self._pending()
            if not pending:
                return None
            check = pending[0]
            return Intervention(
                inject_messages=[
                    "[next verification check] Evaluate ONLY this check in this generation. "
                    "Submit exactly one verification_result now, with a short content summary. "
                    "Use the attached original excerpts directly when sufficient; fetch only missing "
                    "conditions/context. If quote_comparisons are supplied, use those deterministic "
                    "captured-text comparisons; do not retype source strings into comparison scripts. "
                    "Summarize each scope_assessment with enough detail to explain the verdict. "
                    "State fail/unchecked when "
                    "evidence is insufficient; never spend the response reconstructing missing evidence. "
                    "evidence_keys must contain only the job/ref keys listed below; put corpus locators "
                    "in method/detail, not evidence_keys. unresolved_issues belongs beside "
                    "scope_assessment, not inside it. Completed results are checkpointed before "
                    "the next check.\n"
                    + json.dumps(
                        {
                            "check_id": check["check_id"],
                            "binding_id": check["binding_id"],
                            "subject_sha256": check["subject"]["sha256"],
                            "criterion": check["criterion"],
                            "evidence_keys": [s["key"] for s in check["evidence"]],
                            "finish": len(pending) == 1,
                        },
                        ensure_ascii=False,
                    )
                ]
            )
        return None

    async def on_tool_call(
        self,
        ctx: TurnContext,
        tool_call: dict[str, Any],
    ) -> ToolCallIntervention | None:
        del ctx
        name = tool_call.get("name")
        args = tool_call.get("args") or {}
        if self.submission_repair_active and (
            name != "submit_report"
            or (
                self.repair_results is not None
                and (
                    not isinstance(args, dict)
                    or args.get("verification_results") != self.repair_results
                )
            )
        ):
            return ToolCallIntervention(
                skip_with_result="Submission repair permits only submit_report with the saved verification_results unchanged.",
                skip_is_error=True,
            )
        if not self.metadata.get("verification_checks") or tool_call.get("name") != "submit_report":
            return None
        args = tool_call.get("args") or {}
        results = args.get("verification_results") if isinstance(args, dict) else None
        pending = self._pending()
        if pending and (
            not isinstance(results, list)
            or len(results) != 1
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
