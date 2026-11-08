"""User-facing report boundary; internal member evidence stays in the trajectory.

This contract describes observable coverage, not independent proof that every
user requirement or artifact is correct. It does not supervise worker liveness.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

from frontier_agent.components.finalization.recovery import minimal_best_effort_answer
from workflows.agent_team.output_cleaning import strip_team_control
from workflows.agent_team.verification_claims import (
    omit_verification_assurances,
    verification_claim_findings,
)

_INTERNAL_SOURCES = {"collected_reports", "tool_observations", "deterministic_fallback"}
_PROTOCOL = re.compile(
    r"<\s*/?\s*(?:report|tool_call|tool_response|function|parameter|think|attach)\b"
    r"|<ANSWER_NOT_FOUND>|Traceback \(most recent call last\):",
    re.IGNORECASE,
)
_COUNTERS = ("collected_count", "incomplete_count", "queued_aborted", "unresolved_count")


def _contradicts_incomplete_work(text: str) -> bool:
    """Compatibility predicate; matches are scope concerns, not verified contradictions."""
    return bool(verification_claim_findings(text))


_STOP_LABELS = {
    "llm_error": ("模型调用失败", "A model call failed"),
    "wall_deadline": ("已到研究阶段截止时间", "The research deadline was reached"),
    "deadline": ("已到执行时间上限", "The execution deadline was reached"),
    "max_turns": ("已到对话轮次上限", "The turn limit was reached"),
    "budget_exhausted": ("执行预算已耗尽", "The execution budget was exhausted"),
    "user_stop": ("用户已停止执行", "The user stopped execution"),
}


def is_user_report(text: str) -> bool:
    """Reject empty/internal payloads, without pretending to verify prose facts."""
    if not text.strip() or _PROTOCOL.search(text):
        return False
    payload = text.strip()
    if payload.startswith("```") and payload.endswith("```"):
        payload = "\n".join(payload.splitlines()[1:-1])
    try:
        value = json.loads(payload)
    except (ValueError, TypeError):
        return True
    objects = value if isinstance(value, list) else [value]
    return not any(
        isinstance(item, dict)
        and (
            "tool_calls" in item
            or isinstance(item.get("function"), dict)
            or ("name" in item and ("arguments" in item or "parameters" in item))
        )
        for item in objects
    )


def _chinese(question: str, language: str) -> bool:
    label = language.strip().lower()
    if label and label != "auto":
        return "chinese" in label or label in {"zh", "zh-cn", "zh-hans", "中文"}
    return bool(re.search(r"[\u4e00-\u9fff]", question))


def _label(value: object) -> str:
    """Render a bounded board label as text, never as HTML or Markdown links."""
    text = " ".join(str(value or "").split())[:240]
    return re.sub(r"([\\`*_\[\]()#!|])", r"\\\1", html.escape(text))


def finalize_team_report(
    text: str,
    *,
    source: str,
    answer_status: str,
    stopped_by: str,
    question: str = "",
    language: str = "",
    wind_down: dict[str, Any] | None = None,
    tasks: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return publishable answer fields plus a JSON-safe versioned contract.

    Board resolutions are coordinator declarations. Wind-down counts cover only
    work outstanding at that boundary, not all jobs performed in the Run.
    """
    candidate = text
    text = strip_team_control(text)
    examined = text
    wind = wind_down or {}
    counts = {
        key: value
        for key in _COUNTERS
        if isinstance((value := wind.get(key)), int) and not isinstance(value, bool) and value >= 0
    }
    board = [
        {
            "id": str(task.get("id") or ""),
            "description": str(task.get("description") or ""),
            "resolution": str(task.get("resolution") or "open"),
            "notes": str(task.get("notes") or ""),
            "gap": str(task.get("gap") or ""),
            "limitations": str(task.get("limitations") or ""),
            "owners": list(task.get("owners") or []),
            "execution_job_ids": list(task.get("execution_job_ids") or []),
            "verification_status": str(task.get("verification_status") or "not_assessed"),
            "verification_execution_status": str(
                task.get("verification_execution_status") or "not_started"
            ),
            "verification_required": task.get("verification_required") is True,
            "verification_requirements": [
                {
                    "check_id": str(item.get("check_id") or ""),
                    "criterion": str(item.get("criterion") or ""),
                }
                for item in task.get("verification_requirements") or []
                if isinstance(item, dict) and item.get("check_id")
            ],
        }
        for task in (tasks or [])
    ]
    unresolved = [task for task in board if task["resolution"] not in {"resolved", "cancelled"}]
    gaps: list[dict[str, Any]] = []
    jobs = [dict(job) for job in wind.get("job_outcomes", []) if isinstance(job, dict)]
    from plugins.tools._verification import (
        missing_publication_excerpts,
        project_checks,
        verification_progress,
    )

    verification = project_checks(jobs)
    for task in board:
        bound_ids = task["execution_job_ids"]
        assigned = [
            job
            for job in jobs
            if (job.get("job_id") in bound_ids if bound_ids else job.get("agent") in task["owners"])
        ]
        task["execution_job_ids"] = bound_ids or [str(job.get("job_id") or "") for job in assigned]
        task["execution_status"] = (
            "not_assessed"
            if not assigned
            else "complete"
            if all(job.get("status") == "complete" for job in assigned)
            and (not bound_ids or len(assigned) == len(bound_ids))
            else "incomplete"
        )
        if task["gap"].strip() and task["resolution"] != "cancelled":
            gaps.append(
                {
                    "code": "task_evidence_gap",
                    "task_id": task["id"],
                    "detail": task["gap"],
                }
            )
        if task["verification_required"]:
            task.update(
                verification_progress(
                    verification["checks"],
                    task["id"],
                    [item["check_id"] for item in task["verification_requirements"]],
                )
            )
    required_gaps = [
        job
        for job in jobs
        if job.get("required") is not False
        and job.get("coverage_status", job.get("status")) != "complete"
    ]
    acquisition_limits = [
        {"job_id": job.get("job_id"), **observation}
        for job in jobs
        for observation in job.get("content_acquisition", [])
        if isinstance(observation, dict) and not observation.get("obtained")
    ]
    for job in required_gaps:
        check_gap = job.get("status") == "complete" and job.get("verification_checks")
        gaps.append(
            {
                "code": "verification_not_passed" if check_gap else "member_job_incomplete",
                "job_id": str(job.get("job_id") or ""),
                "agent": str(job.get("agent") or ""),
                "reason": "verification_not_passed"
                if check_gap
                else str(
                    job.get("reason")
                    or ("verification_not_passed" if job.get("verification_checks") else "unknown")
                ),
            }
        )
    for task in unresolved:
        gaps.append(
            {"code": "task_unresolved", "task_id": task["id"], "description": task["description"]}
        )
    required_checks_by_work_item: dict[str, list[dict[str, Any]]] = {}
    for check in verification["checks"]:
        if check["required"]:
            required_checks_by_work_item.setdefault(check["work_item_id"], []).append(check)
    for task in board:
        if not task["verification_required"]:
            continue
        checks = required_checks_by_work_item.get(task["id"], [])
        planned_ids = [requirement["check_id"] for requirement in task["verification_requirements"]]
        by_id = {check["check_id"]: check for check in checks}
        selected = [by_id[check_id] for check_id in planned_ids if check_id in by_id]
        missing_ids = [check_id for check_id in planned_ids if check_id not in by_id]
        relevant = selected if planned_ids else checks
        if relevant and not missing_ids and all(check["verdict"] == "pass" for check in relevant):
            continue
        status = (
            "not_registered"
            if not relevant
            else "failed"
            if any(check["verdict"] == "fail" for check in relevant)
            else "partial"
            if missing_ids or any(check["verdict"] == "pass" for check in relevant)
            else "unchecked"
        )
        gap = {
            "code": "task_verification_incomplete",
            "task_id": task["id"],
            "status": status,
        }
        if missing_ids:
            gap["missing_check_ids"] = missing_ids
        gaps.append(gap)
    for key in ("incomplete_count", "queued_aborted", "unresolved_count"):
        if counts.get(key, 0) and wind.get("run_status") != "complete":
            gaps.append({"code": key, "count": counts[key]})
    if (
        wind.get("status") == "partial"
        and wind.get("run_status") != "complete"
        and not any(counts.get(k, 0) for k in _COUNTERS[1:])
    ):
        gaps.append({"code": "team_coverage_incomplete"})

    # Blanket assurance is unsupported even when every *declared* check passed:
    # declared checks only prove their bounded criteria and versions.  Scoped
    # statements such as "all declared checks passed" remain publishable.
    retained_reports = source == "collected_report_fallback" and is_user_report(text)
    findings = verification_claim_findings(text) if not retained_reports else []
    contradictory = bool(findings)
    if contradictory:
        gaps.append({"code": "unsupported_verification_claim"})
    from plugins.tools._corpus_scope import corpus_scope_findings

    corpus_observations = [
        o for job in jobs for o in job.get("content_acquisition", []) if isinstance(o, dict)
    ]
    scope_findings = corpus_scope_findings(text, corpus_observations)
    if scope_findings:
        gaps.append({"code": "corpus_scope_overstatement"})
        findings += scope_findings
    if findings:
        text = omit_verification_assurances(text, findings)
    missing_excerpts = missing_publication_excerpts(
        verification["checks"], text,
        excluded_work_items={t["id"] for t in board if t["resolution"] in {"blocked", "cancelled"}},
    )
    if missing_excerpts:
        gaps.append({"code": "checked_publication_excerpt_changed", "check_ids": missing_excerpts})
    # A local assurance error must not erase unrelated evidence or analysis.
    # Formatting debris alone is not a useful answer after sentence removal.
    residual = re.sub(r"(?m)^[ \t]*(?:#{1,6}\s+.*|\d+[.)]\s*|[-*+_>` ]+)$", "", text)
    useful_text = (
        bool(re.search(r"[\w\u4e00-\u9fff]", residual)) if findings else bool(text.strip())
    )
    system = source in _INTERNAL_SOURCES or not is_user_report(text) or not useful_text
    publication = {
        "status": "withheld"
        if findings and system
        else "unavailable"
        if system
        else "revised"
        if findings
        else "published",
        "candidate_sha256": hashlib.sha256(candidate.encode()).hexdigest(),
        "candidate_verification": "not_assessed",
        "findings": findings,
        "unmatched_checked_excerpts": missing_excerpts,
    }
    if findings:
        publication["candidate_text"] = candidate
        publication["examined_text"] = examined
    if system:
        gaps.append({"code": "publication_withheld" if findings else "synthesis_unavailable"})
        if not is_user_report(examined) and source not in _INTERNAL_SOURCES:
            gaps.append({"code": "invalid_user_report"})
    if stopped_by and stopped_by not in {"final_answer", "submit_report"}:
        gaps.append({"code": "execution_stopped", "reason": stopped_by})
        if publication["status"] in {"published", "revised"}:
            publication["status"] = "interrupted"
    status = answer_status or "best_effort"
    if gaps and status == "complete":
        status = "partial"
    if system:
        status = "not_found"
    if retained_reports:
        status = "best_effort"
        gaps.append({"code": "synthesis_unavailable"})
    kind = "system_status" if system else "complete" if status == "complete" else "partial"
    contract = {
        "version": 4,
        "publication": publication,
        "source": "system" if system or retained_reports else "model",
        "kind": kind,
        "answer_status": status,
        "stopped_by": stopped_by,
        "input_source": source,
        "gaps": gaps,
        "task_board": board,
        "task_board_basis": "coordinator_declared",
        "wind_down": {
            "status": str(wind.get("status") or "unknown"),
            **counts,
            "run_status": str(wind.get("run_status") or "unknown"),
        },
        "artifact_verification": "not_assessed",
        "job_outcomes": jobs,
        "required_work_basis": "dispatch_declared",
        "verification": verification["status"],
        "verification_basis": verification["basis"]
        if verification["checks"]
        else "execution_limits_only",
        "verification_checks": verification["checks"],
        "acquisition_limits": acquisition_limits,
    }
    zh = _chinese(question, language)

    def gap_label(value: str) -> str:
        # Board prose is model-authored too. Do not reintroduce an unsupported
        # absence claim through the automatically appended limitation section.
        note_findings = corpus_scope_findings(value, corpus_observations)
        if not note_findings:
            return _label(value)
        publication.setdefault("note_scope_findings", []).append({
            "candidate_text": value, "findings": note_findings,
        })
        remainder = omit_verification_assurances(value, note_findings)
        notice = (
            "检索范围不足以确认该全库断言，原文见运行记录。"
            if zh else "Search coverage cannot establish the corpus-wide claim; see the run record. "
        )
        return _label(notice + remainder)

    notes: list[str] = []
    verification_notes: list[str] = []
    if scope_findings:
        notes.append(
            "已移除超出检索覆盖范围的全库断言。本次检索覆盖或日期信息不完整；"
            "未检索到不等于全库不存在，也不能据此确认全库最新版本。"
            if zh else "Corpus-wide assertions exceeding the recorded search coverage were omitted. "
            "Bounded retrieval does not prove absence or latestness across the corpus."
        )
    if missing_excerpts:
        notes.append(
            "最终正文未保留部分已核验片段，原片段的通过结果不能用于确认改写后的内容。"
            if zh else "Some checked passages were changed or omitted in the final text; their "
            "passing verdicts do not verify the rewritten content."
        )
    declared_gaps = [
        task for task in board if task["gap"].strip() and task["resolution"] != "cancelled"
    ]
    undisclosed_gaps = [task for task in declared_gaps if system or task["gap"].strip() not in text]
    if undisclosed_gaps:
        notes.append("仍未确认的证据缺口：" if zh else "Unresolved evidence gaps:")
        notes.extend(
            f"- {_label(task['description'] or task['id'])}: {gap_label(task['gap'])}"
            for task in undisclosed_gaps[:20]
        )
    if verification["checks"]:
        verification_notes.append(
            "以下结论仅针对列明版本与检查项，不代表整份报告或其他版本已通过核验："
            if zh
            else "Verdicts cover only the declared checks and versions, not the entire report:"
        )
        labels = {"pass": "通过", "fail": "未通过", "unchecked": "未能确认"}
        for check in verification["checks"]:
            verdict = labels.get(check["verdict"], "未检查") if zh else check["verdict"]
            if check["required"] and check["verdict"] != "pass":
                notes.append(f"- {_label(check['criterion'])}: {verdict}")
                notes.extend(_label(issue) for issue in (check.get("result") or {}).get("unresolved_issues", []))
            verification_notes.append(
                f"- {_label(check['criterion'])}: {verdict} "
                f"({'版本' if zh else 'version'}={check['binding_id'][:12]}; "
                f"{'对象' if zh else 'subject'}={_label(check['subject']['key'])}; "
                f"sha256={_label(check['subject']['sha256'][:12])})"
            )
            for issue in (check.get("result") or {}).get("unresolved_issues", []):
                verification_notes.append(
                    f"  - {'未解决问题' if zh else 'Unresolved issue'}: {_label(issue)}"
                )
    if required_gaps:
        notes.append(
            "以下必要成员任务或检查仍有缺口；已返回的工具观测不等于核验通过："
            if zh
            else "Required member jobs or checks remain incomplete; observations are not verification:"
        )
        notes.extend(
            f"- {_label(job.get('agent') or job.get('job_id'))}: "
            f"{_label(job.get('reason') or 'verification_not_passed')} ({_label(job.get('job_id'))})"
            for job in required_gaps[:20]
        )
        if len(required_gaps) > 20:
            notes.append(
                f"另有 {len(required_gaps) - 20} 项，完整列表见运行记录。"
                if zh
                else f"{len(required_gaps) - 20} more jobs are listed in the run record."
            )
    if contradictory:
        notes.append(
            "已移除超出可确认核验范围的声明句；其他分析予以保留。原始候选正文与命中位置保存在运行记录中。"
            if zh and not system
            else "候选正文已生成，但移除超范围核验声明后没有可交付正文。原始候选与命中位置保存在运行记录中。"
            if zh
            else "Statements exceeding the recorded verification scope were omitted; other analysis "
            "is retained. The original candidate and matched spans are preserved in the run record."
            if not system
            else "A candidate was generated, but no deliverable prose remains after removing "
            "unsupported verification assurances. The original and matched spans are preserved."
        )
    if stopped_by and stopped_by not in {"final_answer", "submit_report"}:
        reason = _STOP_LABELS.get(
            stopped_by,
            (
                "执行提前结束，具体原因见运行记录",
                "Execution ended early; see the run record for details",
            ),
        )
        notes.append(reason[0 if zh else 1] + ("。" if zh else "."))
    if wind.get("status") == "partial" and wind.get("run_status") != "complete":
        notes.append(
            "团队收尾仍有缺口，不能据此确认全部任务已完成。"
            if zh
            else "Team wind-down has gaps; full task completion cannot be confirmed."
        )
    # A task gap already appears either in the answer or the gap disclosure above.
    unresolved = [t for t in unresolved if not t["gap"].strip()]
    if unresolved:
        notes.append("任务板尚未解决的事项：" if zh else "Unresolved task-board items:")
        notes.extend(
            f"- {_label(task['description'] or task['id'])}"
            + (f": {gap_label(task['gap'] or task['notes'])}" if task["gap"] or task["notes"] else "")
            for task in unresolved[:20]
        )
        if len(unresolved) > 20:
            notes.append(
                f"另有 {len(unresolved) - 20} 项，详见任务板。"
                if zh
                else f"{len(unresolved) - 20} more items remain on the task board."
            )
    if counts and system:
        labels = (
            ("收尾阶段回收报告", "其中未完整结束", "取消排队任务", "仍未回收任务")
            if zh
            else (
                "Reports collected during wind-down",
                "Incomplete among them",
                "Queued jobs cancelled",
                "Jobs still outstanding",
            )
        )
        notes.append(
            ("；" if zh else "; ").join(
                f"{label}: {counts[key]}"
                for key, label in zip(_COUNTERS, labels, strict=True)
                if key in counts
            )
            + ("。" if zh else ".")
        )
        notes.append(
            "以上仅为收尾阶段统计，不代表全部研究任务已完成或结论已核验。"
            if zh
            else "These are wind-down counts only, not proof of full coverage or verified findings."
        )
    if system:
        intro = (
            "以下为系统根据执行记录生成的状态说明，不是主 Agent 的综合结论。"
            if zh
            else "This is a system-generated execution status, not the main agent's synthesis."
        )
        # Reuse the existing fallback but render only a controlled stop marker.
        safe_stop = (
            stopped_by if re.fullmatch(r"[a-zA-Z0-9_:-]{1,80}", stopped_by) else "execution_limit"
        )
        if safe_stop in {"final_answer", "submit_report"}:
            safe_stop = "report_unavailable"
        if contradictory or safe_stop == "report_unavailable":
            text = ("## 当前可交付结果\n\n" if zh else "## Publication status\n\n") + (
                "候选正文已生成，但未通过发布范围检查。"
                if zh and contradictory
                else "本次未取得可交付的综合正文。"
                if zh
                else "A candidate was generated but withheld by the publication scope check."
                if contradictory
                else "No deliverable synthesis is available."
            )
        else:
            text = minimal_best_effort_answer(
                question,
                safe_stop,
                language="zh" if zh else "en",
            )
        text += "\n\n" + intro
        text += "\n\n" + (
            "本状态说明不代表已核验文件内容或下载可用性。"
            if zh
            else "This status does not verify file contents or downloads."
        )
    elif kind == "partial":
        # Put the actual delivery status before the conclusion; a footer alone
        # can leave the headline falsely looking like a fully verified answer.
        text = (
            "**部分完成：以下结论仅基于已取得的证据，尚有任务或证据缺口。**\n\n"
            if zh
            else "**Partial result: conclusions use available evidence; work or evidence gaps remain.**\n\n"
        ) + text
        notes.insert(
            0,
            "本次结果为部分完成或尽力结果，不能据此认定所有要求均已完成。"
            if zh
            else "This is a partial or best-effort result; full completion is not established.",
        )
    if notes and (system or kind == "partial"):
        text += (
            "\n\n" + ("### 执行状态\n\n" if zh else "### Execution status\n\n") + "\n\n".join(notes)
        )
    # Audit detail remains accessible independently of the user-facing answer.
    # Required failures above stay visible; a failed optional tool attempt alone
    # is not evidence that the requested result is incomplete.
    contract["audit_appendix"] = {"verification_notes": verification_notes}
    return {
        "final_answer": text,
        "final_content": text,
        "final_answer_source": "deterministic_fallback" if system else source,
        "answer_status": status,
        "answer_sentinel": "<ANSWER_NOT_FOUND>" if status == "not_found" else "",
        "report_contract": contract,
    }
