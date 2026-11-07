"""Small, durable member handoffs instead of one late all-checks response."""

from __future__ import annotations

import json
import re
import time
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
    """Bound verification output; encourage an early, explicitly scoped research report."""

    critical = True

    def __init__(self, metadata: dict[str, Any]) -> None:
        self.metadata = metadata
        self.started = time.monotonic()
        self.handoff_offered = False
        self.submission_repair_used = False
        self.submission_repair_active = False
        self.repair_results: list[dict[str, Any]] | None = None
        self.date_match: dict[str, str] | None = None

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
        target = self.metadata.get("find_one_published_on")
        if not target or self.date_match or result.name != "corpus_search" or result.is_error:
            return None
        try:
            payload = json.loads(result.result)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return None
        for hit in payload.get("hits", []):
            if not isinstance(hit, dict) or hit.get("published") != target:
                continue
            doc_id = hit.get("doc_id")
            excerpts = hit.get("excerpts") or []
            if (
                isinstance(doc_id, str)
                and re.fullmatch(r"cv2:[0-9a-f]{64}", doc_id)
                and hit.get("evidence_contract") == "native-search-evidence-v2"
                and any(
                    isinstance(e, dict)
                    and isinstance(e.get("text"), str)
                    and e["text"].strip()
                    and isinstance(e.get("ref"), str)
                    and re.fullmatch(r"eref:[0-9a-f]{64}:\d+", e["ref"])
                    for e in excerpts
                )
            ):
                self.date_match = {"doc_id": doc_id, "published": target}
                self.metadata["first_date_match"] = self.date_match
                break
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
        if self.date_match:
            return Intervention(
                allowed_tool_names=("corpus_fetch", "corpus_inventory", "submit_report"),
                inject_messages=[
                    "[first supported date match] The assigned date-only lookup has a candidate "
                    "with published metadata and delivered original evidence: "
                    + json.dumps(self.date_match, ensure_ascii=False)
                    + ". Report this document now; read only missing context of this document "
                    "if needed. Do not enumerate other dates or undated sources. Partial corpus "
                    "coverage does not invalidate this existence result; do not claim uniqueness "
                    "or exhaustive coverage. A candidate is not automatic semantic verification."
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
                    "Do not recopy source bodies or the full report. Keep each "
                    "scope_assessment detail to one comparison sentence. State fail/unchecked when "
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
        if (
            not self.handoff_offered
            and not self.metadata.get("can_publish")
            and (
                (
                    time.monotonic() - self.started >= 90
                    and len(ctx.metadata.get("corpus_evidence") or []) >= 2
                )
                or bool(ctx.metadata.get("web_evidence"))
            )
        ):
            self.handoff_offered = True
            return Intervention(
                inject_messages=[
                    "[early research handoff] You have source evidence. If it supports the core "
                    "assigned findings, submit_report now so verification can overlap other research. "
                    "Give a concise report with exact refs, material qualifications and explicit "
                    "unresolved items. Delivered web text is retained for the verifier: repeated "
                    "fetches of the same page are not independent corroboration. Do not wait for "
                    "the research deadline, repeatedly search "
                    "uncovered historical topics, or create an optional report file. If a load-bearing "
                    "fact still lacks evidence, do one targeted lookup and then report what is known. "
                    "An incomplete finding must remain an explicit gap, not a claim of completion."
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
        if self.date_match and (
            name not in {"submit_report", "corpus_fetch", "corpus_inventory"}
            or (
                name != "submit_report"
                and (not isinstance(args, dict) or args.get("doc_id") != self.date_match["doc_id"])
            )
        ):
            return ToolCallIntervention(
                skip_with_result="Date-only lookup already matched. Report or read missing context of that same doc_id; do not expand research.",
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
