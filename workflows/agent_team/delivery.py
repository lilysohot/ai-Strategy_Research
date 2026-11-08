"""One coordinator submission for final prose and validated task dispositions."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictStr, model_validator

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
from plugins.tools._verification import (
    minimum_verification_budget,
    missing_publication_excerpts,
    project_bus_checks,
    project_checks,
    unresolved_publication_claims,
    verification_label_findings,
    work_item_verification_progress,
)
from plugins.tools.finalize_answer import finalize_gate, planning_requirement_error
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

_DELIVERY_ACCEPTED = "Final answer and task dispositions accepted."


class FinalDisposition(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: StrictStr = Field(min_length=1)
    resolution: Literal["resolved", "blocked"]
    notes: StrictStr = Field(min_length=1, max_length=2000)
    gap: StrictStr = Field(default="", max_length=2000)
    limitations: StrictStr = Field(
        default="", max_length=2000,
        description="Nonblocking boundaries outside the requested outcome. "
        "Never use this to waive necessary evidence or a required check.",
    )

    @model_validator(mode="after")
    def consistent_completion(self) -> FinalDisposition:
        if self.resolution == "resolved" and self.gap:
            raise ValueError(
                "resolved cannot retain a blocking gap: use blocked for an unmet requirement, "
                "or limitations for a boundary that does not affect the requested outcome. "
                "Required evidence and verification remain mandatory."
            )
        return self


@tool
async def deliver_answer(
    content: str,
    updates: list[FinalDisposition],
    corpus_conclusions: list[dict[str, Any]] | None = None,
) -> str:
    """Submit the complete final answer AND task dispositions in one call.

    Do not spend a separate generation updating the board first. Research with
    unmet done_when or unpassed required checks must be blocked, with notes and
    gap; never claim success from execution alone. Disclose gaps in the answer.
    Delivery tasks complete with acceptance. Call this tool alone.

    Args:
        content: Complete user-facing answer, with sources and explicit limitations.
        updates: Final dispositions against the user's outcome and necessary evidence. Use []
            if none remain. gap means an unmet requirement and requires blocked; limitations
            records nonblocking boundaries. Self-added optional work cannot become an obligation.
        corpus_conclusions: Complete corpus evidence manifest for THIS content. Each entry
            needs id, report_quote copied verbatim from content, and evidence:[{evidence_ref}].
            Use original complete corpus tool refs (eref: or ce:). Required for corpus-backed
            final prose; omit for web-only answers. URLs, job IDs and web hashes are not corpus
            receipts. Never copy old report anchors. This binds citations, not a semantic PASS.
    """
    scope = get_current_execution_scope()
    if scope is None or SWARM_SCOPE_KEY not in scope.metadata or in_planning(scope.task_id):
        raise ValueError("Final delivery requires an executing team coordinator")
    if not is_user_report(content):
        raise ValueError("Provide the final answer body, not an empty/internal tool payload")
    from plugins.corpus.ledger import get_run_ledger
    from plugins.tools.corpus_manifest import commit_final_manifest, prepare_final_manifest

    if corpus_conclusions is None and get_run_ledger().has_activity():
        raise ValueError(
            "Corpus-backed delivery requires corpus_conclusions bound to this content. "
            "Supply id, exact report_quote, evidence:[{evidence_ref}]. "
            "Use [] only when no supported corpus claim is delivered; disclose the gap."
        )
    items = [FinalDisposition.model_validate(u).model_dump() for u in updates]
    if len({u["id"] for u in items}) != len(items):
        raise ValueError("Each task may have only one final disposition")
    # Return independent defects together, before board or manifest mutation.
    # Otherwise each cheap validation failure costs another full report generation.
    from plugins.tools._corpus_scope import corpus_scope_findings

    bus = registry.get_optional(AgentBus)
    bus_id = resolve_bus_task_id(scope)
    observations = [
        observation
        for job in (bus.list_task_jobs(bus_id) if bus else [])
        if job.result is not None
        for observation in job.result.metadata.get("content_acquisition", [])
    ]
    issues: list[dict[str, Any]] = corpus_scope_findings(content, observations)
    projected = project_bus_checks(bus, bus_id)["checks"] if bus else []
    issues.extend(verification_label_findings(projected, content))
    current_tasks = snapshot_tasks(scope.task_id)
    excluded = {
        task["id"] for task in current_tasks if task["resolution"] in {"blocked", "cancelled"}
    }
    excluded.update(item["id"] for item in items if item["resolution"] == "blocked")
    for check_id in missing_publication_excerpts(
        projected,
        content,
        excluded_work_items=excluded,
    ):
        issues.append(
            {
                "rule": "checked_publication_excerpt_missing",
                "check_id": check_id,
                "detail": "checked publication excerpt is missing from final content",
            }
        )
    for finding in unresolved_publication_claims(
        projected,
        content,
        excluded_work_items=excluded,
    ):
        issues.append({"rule": "failed_publication_claim_retained", **finding})
    payload = None
    if corpus_conclusions is not None:
        try:
            payload = prepare_final_manifest(corpus_conclusions, content.strip())
        except ValueError as exc:
            issues.append({"rule": "corpus_manifest_invalid", "detail": str(exc)})
    if issues:
        raise ValueError(
            "Delivery preflight failed: "
            + json.dumps(issues, ensure_ascii=False)
            + ". Correct all listed fields/sentences together. Preserve valid passages and "
            "citations; changed checked passages require recheck or a blocked disposition. "
            "No task disposition or final manifest has been committed."
        )
    if bus and any(
        s.current_job_id or s.pending_tasks or s.pending_results
        for s in bus.list_sessions_for_task(bus_id)
    ):
        raise ValueError("Collect or stop outstanding members before final delivery")
    job_outcomes = snapshot_job_outcomes(bus, bus_id) if bus else []
    project_checks(job_outcomes)
    outcomes = {j["job_id"]: j for j in job_outcomes}
    tasks = {t["id"]: t for t in snapshot_tasks(scope.task_id)}
    for item in items:
        if item["resolution"] == "resolved":
            for job_id in tasks.get(item["id"], {}).get("execution_job_ids", []):
                outcome = outcomes.get(job_id, {})
                replacements = outcome.get("coverage_resolved_by", [])
                recovered = (
                    outcome.get("coverage_status") == "complete"
                    and any(r["job_id"] != job_id for r in replacements)
                    and all(
                        r["job_id"] == job_id
                        or outcomes.get(r["job_id"], {}).get("status") == "complete"
                        for r in replacements
                    )
                )
                if outcome.get("status") != "complete" and not recovered:
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
        if payload is not None:
            commit_final_manifest(payload)
        complete_delivery_tasks(scope.task_id)
    return _DELIVERY_ACCEPTED


deliver_answer.metadata["execution_barrier"] = True


class TeamDeliveryObserver(BaseObserver):
    """Move from gathered evidence to one final generation before time runs out."""

    critical = True

    def __init__(
        self, budget: TeamPhaseBudget, *, coordination_tools: tuple[str, ...] | None = None,
    ) -> None:
        self.budget = budget
        self.coordination_tools = coordination_tools
        self.active = False
        self.wind_down: TeamWindDown | None = None
        self._repair_offers: dict[tuple[str, str], int] = {}
        self._verification_nudges: set[tuple[str, tuple[str, ...]]] = set()

    def _pending_verification_prompt(
        self,
        bus: AgentBus,
        bus_id: str,
        tasks: list[dict[str, Any]],
    ) -> Intervention | None:
        """Start focused checks as soon as source reports arrive, before waiting for all research."""
        jobs = bus.list_task_jobs(bus_id)
        sources = [
            j.job_id
            for j in jobs
            if j.status == "completed"
            and j.result is not None
            and not j.item.metadata.get("verification_checks")
        ]
        if not sources:
            return None
        evidence_version = tuple(sorted(sources))
        dispatched = {c["check_id"] for c in project_bus_checks(bus, bus_id)["checks"]}
        pending = [
            {"work_item_id": t["id"], **c}
            for t in tasks
            if t.get("verification_required")
            and t["resolution"] not in {"resolved", "blocked", "cancelled"}
            for c in t.get("verification_requirements", [])
            if c["check_id"] not in dispatched
            and (c["check_id"], evidence_version) not in self._verification_nudges
        ]
        if not pending:
            return None
        self._verification_nudges.update((c["check_id"], evidence_version) for c in pending)
        return Intervention(
            inject_messages=[
                "[required verification ready] Source reports are available. Before another long "
                "collect_reports wait, dispatch the required checks whose evidence is ready. "
                "Use real verification_checks with the planned ID/criterion, exact subject.text "
                "or source job, and evidence job/ref. Do not wait for every research branch or a "
                "complete answer. Each subject must be the passage relevant to that check; do not "
                "bind the same whole answer to unrelated criteria. Dispatch ready checks alone now "
                "and defer only checks that lack their own evidence. The board resolves work_item_id "
                "and criterion from check_id when omitted. Do not copy all source reports into prompt; "
                "binding evidence job/ref attaches them automatically. Do not wait for a "
                "polished final draft. Mark factual_scope=true for factual claims. Mark exact "
                "final passages publication_excerpt=true; separate conditional estimates and "
                "forecasts from observed outcomes. If evidence is still missing, name that dependency.\n"
                + json.dumps(
                    {"source_jobs": sources, "pending_checks": pending}, ensure_ascii=False
                )
            ]
        )

    def _offer_repair(
        self,
        ctx: TurnContext,
        bus: AgentBus,
        bus_id: str,
        tasks: list[dict[str, Any]],
        runtime: Any,
        now: float,
        reserve: float,
    ) -> Intervention | None:
        """Allow one bounded correction round per check before closing coordination."""
        phase = self.budget.sync_phase(now)
        if phase in {"publishing", "finalizing"}:
            return None
        deadline = self.budget.deadline_for_job(
            can_publish=phase in {"draining", "consolidating"},
            is_verification=True,
            is_recheck=True,
        )
        limits = [d for d in [deadline] if d is not None]
        if self.budget.publication_deadline_s is not None:
            limits.append(self.budget.publication_deadline_s - reserve)
        minimum = minimum_verification_budget(getattr(runtime, "first_chunk_timeout_s", 45))
        if limits and min(limits) - now < minimum:
            return None
        open_items = {
            t["id"] for t in tasks if t["resolution"] not in {"resolved", "blocked", "cancelled"}
        }
        pending = [
            c
            for c in project_bus_checks(bus, bus_id)["checks"]
            if c["required"] and c["verdict"] != "pass" and c["work_item_id"] in open_items
        ]
        offers = []
        for check in pending:
            key = check["check_id"]
            # Permit one effective correction plus one incomplete attempt.
            # Transport/protocol failures without a verdict must not consume
            # the opportunity to repair the first actual failed review.
            attempts = check["attempts"]
            failures = sum(bool(a["events"]) and a["verdict"] != "pass" for a in attempts)
            incomplete = sum(not a["events"] for a in attempts)
            if len(attempts) >= 3 or failures >= 2 or incomplete >= 2:
                continue
            started = self._repair_offers.setdefault((key, check["job_id"]), ctx.turn)
            if ctx.turn - started >= 3:
                continue  # Two follow-up generations to collect/prepare/dispatch, never spin.
            result = check.get("result") or {}
            offers.append(
                {
                    "check_id": key,
                    "work_item_id": check["work_item_id"],
                    "criterion": check["criterion"],
                    "replaces_job_id": check["job_id"],
                    "subject_sha256": check["subject"]["sha256"],
                    "verdict": check["verdict"],
                    **({"revision_kind": "retry"} if not result else {}),
                    "recovery_action": (
                        "No verdict was checkpointed. Retry this check alone with identical "
                        "subject and evidence; retain all other checkpointed results."
                        if not result
                        else "Correct the failed subject or acquire the specifically missing evidence."
                    ),
                    "detail": result.get("detail", ""),
                    "unresolved_issues": result.get("unresolved_issues", []),
                }
            )
        if not offers:
            return None
        ctx.metadata["team_verification_repair_offered"] = [c["check_id"] for c in offers]
        return Intervention(
            inject_messages=[
                "[team verification repair] Some checks are defective or incomplete. Coordination "
                "remains open for ONE bounded correction/recheck round, using existing evidence. "
                "Collect the verifier report if necessary, correct only the affected claims, and "
                "dispatch verification_checks with the complete corrected passage in subject.text, "
                "publication_excerpt=true, factual_scope=true for factual claims, "
                "replaces_job_id below, revision_kind='subject' and a revision_reason. Keep the "
                "criterion and evidence scope; use revision_kind='retry' only for unchanged bytes. "
                "When no verdict was checkpointed, retry only that check using its original "
                "subject/evidence; do not rewrite it or repeat passed sibling checks. "
                "A fix mentioned in assignment prose is not a new subject. Compare model/version, "
                "date, units, conditions and attribution, not just matching quotations. Preserve "
                "the checked wording in delivery; further material edits need their own check. "
                "Do not start broad research or repeat whole-report audits. Dispatch within this "
                "generation or the next two; if correction cannot be checked, mark the affected "
                "work blocked and disclose its limits. A failed recheck ends this repair round.\n"
                + json.dumps(offers, ensure_ascii=False)
            ]
        )

    def _ready(self, bus: AgentBus, task_id: str, tasks: list[dict[str, Any]]) -> bool:
        if any(
            s.current_job_id or s.pending_tasks for s in bus.list_sessions_for_task(task_id)
        ):
            return False
        jobs = bus.list_task_jobs(task_id)
        if not jobs or any(j.status in {"queued", "submitted", "running"} for j in jobs):
            return False
        known = {j.job_id for j in jobs}
        for task in tasks:
            if task["resolution"] in {"resolved", "cancelled", "blocked"}:
                continue
            # A completed member job is not a declaration that the user goal is met.
            # Without declared checks, let coordination assess the result and record
            # its disposition before closing tools. An idle roster is irrelevant.
            if task.get("kind") != "delivery" and not task.get("verification_required"):
                return False
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
        intervention = await self._before_llm(ctx)
        if not self.active and self.coordination_tools and snapshot_tasks(ctx.task_id):
            # Do not ask the model to compose a final body while delivery would reject it.
            # Keep collection/repair/dispatch available, including before verifier fan-in.
            names = tuple(name for name in self.coordination_tools if name != "deliver_answer")
            if intervention and intervention.allowed_tool_names is not None:
                names = tuple(n for n in names if n in intervention.allowed_tool_names)
            return replace(intervention, allowed_tool_names=names) if intervention else Intervention(
                allowed_tool_names=names,
            )
        return intervention

    async def _before_llm(self, ctx: TurnContext) -> Intervention | None:
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
        reserve = self.budget.delivery_reserve_s
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
        collected = bool(bus and self._ready(bus, bus_id, tasks))
        if collected and not time_to_deliver and not turns_to_deliver:
            requirement_error = planning_requirement_error(ctx.task_id, bus_id)
            if requirement_error:
                return Intervention(
                    inject_messages=[
                        "[runtime prerequisite pending] " + requirement_error
                        + " Do not retry final submission yet. Existing collected evidence may "
                        "be reused; do not expand the user's acceptance criteria."
                    ],
                )
        if collected and bus and not time_to_deliver and not turns_to_deliver:
            repair = self._offer_repair(ctx, bus, bus_id, tasks, runtime, now, reserve)
            if repair is not None:
                return repair
        ready = collected and not files_pending
        if not time_to_deliver and not turns_to_deliver and not ready:
            if bus and self.budget.sync_phase(now) not in {"publishing", "finalizing"}:
                remaining_verification = self.budget.remaining_for_job(
                    can_publish=False,
                    is_verification=True,
                )
                if (
                    remaining_verification is None
                    or remaining_verification
                    >= minimum_verification_budget(getattr(runtime, "first_chunk_timeout_s", 45))
                ):
                    return self._pending_verification_prompt(bus, bus_id, tasks)
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
            "board-update turn is needed. Judge completion against the ORIGINAL user request; "
            "your done_when cannot replace a missing requested result with an explanation of "
            "why it is missing. Resolved only if the requested outcome is satisfied and "
            "required checks passed; otherwise blocked with notes and "
            "gap. Nonblocking boundaries belong in limitations, not gap. Do not promote "
            "self-added optional work into required outcomes. Preserve material limits beside "
            "the affected conclusions. Do not equate a "
            "completed member job with verified findings. Missing files remain blocked. "
            "Keep the answer concise enough to finish within the remaining budget. "
            f"Publication time remaining: {max(0, deadline - time.monotonic()):.0f}s.\n"
            if deadline is not None
            else "[team delivery] Submit the answer and task dispositions together with deliver_answer. "
            "Judge completion against the original user request, not a weaker self-written done_when. "
            "Use blocked with notes and gap for unmet requirements; limitations for "
            "nonblocking boundaries.\n"
        )
        from plugins.corpus.ledger import get_run_ledger

        prompt += (
            "Deliver the requested result first. Optional enrichment that was not obtained is "
            "not a failed requirement. Do not reopen research to improve an already sufficient "
            "result. If a concrete broader investigation would help, ask briefly whether the user "
            "wants it AFTER the result; wait for the user's reply before executing that expansion. "
            "Do not routinely append an expansion question. Necessary unresolved gaps remain gaps.\n"
            "Verification covers only the exact passed subject and its declared criterion. "
            "A verification statement must identify only the subject and criterion actually checked. "
            "Place unchecked/failed limits beside the affected facts. Distinguish sourced "
            "observations from your forecasts, probabilities and causal interpretation; "
            "a stronger conclusion or a conclusion depending on unchecked data is not certified "
            "by neighbouring passed checks. Keep each claim within the scope and conditions of "
            "its actual evidence. Omit unsupported optional claims; disclose missing necessary "
            "support as a gap.\n"
        )

        corpus_active = get_run_ledger().has_activity() or bool(
            bus
            and any(
                job.result and job.result.metadata.get("corpus_evidence")
                for job in bus.list_task_jobs(bus_id)
            )
        )
        prompt += (
            "For corpus-backed prose, include corpus_conclusions in this SAME deliver_answer call: "
            "the complete final claim list, each with id, report_quote copied exactly from content, "
            "and evidence:[{evidence_ref: full original tool reference}]. Bind the revised wording, "
            "not research drafts. Do not recopy source text. Omit claims you cannot support or "
            "state the gap explicitly; a citation manifest never upgrades failed semantic checks. "
            "Only corpus-tool eref:/ce: receipts belong here. Cite web-only claims by URL in "
            "content; never put a URL, web hash or job ID into corpus_conclusions.\n"
            if corpus_active
            else "Omit corpus_conclusions: no corpus evidence was acquired in this run. "
            "Cite web sources by URL in content. A web URL, hash or job ID is not a corpus receipt.\n"
        )
        prompt += json.dumps(tasks, ensure_ascii=False)
        if bus:
            excluded = {t["id"] for t in tasks if t["resolution"] in {"blocked", "cancelled"}}
            passages = list(dict.fromkeys(
                c["subject"]["text"] for c in project_bus_checks(bus, bus_id)["checks"]
                if c.get("publication_excerpt") and c["verdict"] == "pass"
                and c["work_item_id"] not in excluded and c["subject"].get("text")
            ))
            if passages:
                prompt += (
                    "\n[checked publication text] Copy these passages exactly into content, "
                    "without rephrasing or inserting Markdown inside them. They are checked "
                    "answer text, not an audit appendix. Do not repeat their facts in a second "
                    "summary. A material revision needs a new check or a blocked disposition.\n"
                    + json.dumps(passages, ensure_ascii=False)
                )
            from plugins.tools._corpus_handoff import render_corpus_citation_index

            sources = {
                job.job_id: job.result.metadata.get("corpus_evidence") or []
                for job in bus.list_task_jobs(bus_id)
                if job.result is not None
            }
            focus = "\n".join(
                c["subject"].get("text", "") for c in project_bus_checks(bus, bus_id)["checks"]
            )
            prompt += render_corpus_citation_index(sources, focus_text=focus)
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
        if (
            result.name == "deliver_answer"
            and not result.is_error
            and result.execution_status == "succeeded"
            and result.result == _DELIVERY_ACCEPTED
        ):
            ctx.metadata["final_answer"] = result.args["content"].strip()
            ctx.metadata["team_delivery_accepted"] = True

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        if ctx.metadata.get("team_delivery_accepted"):
            return Intervention(stop_reason="final_answer")
        return None
