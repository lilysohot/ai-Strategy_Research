"""User-facing report boundary; internal member evidence stays in the trajectory.

This contract describes observable coverage, not independent proof that every
user requirement or artifact is correct. It does not supervise worker liveness.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

from frontier_agent.components.finalization.recovery import minimal_best_effort_answer

_INTERNAL_SOURCES = {"collected_reports", "tool_observations", "deterministic_fallback"}
_PROTOCOL = re.compile(
    r"<\s*/?\s*(?:report|tool_call|tool_response|function|parameter|think|attach)\b"
    r"|<ANSWER_NOT_FOUND>|Traceback \(most recent call last\):",
    re.IGNORECASE,
)
_COUNTERS = ("collected_count", "incomplete_count", "queued_aborted", "unresolved_count")
# A narrow contradiction guard, not a semantic verifier. Recovery synthesis
# gets the structured gaps first; these explicit blanket claims must not survive
# when it nevertheless ignores them. Keep scoped/negative statements intact.
_BLANKET_VERIFICATION = re.compile(
    r"已获充分交叉验证|(?:全部|所有|全面|整体).{0,16}(?:核验|验证|核对|复核)(?:通过|完成)"
    r"|(?:全部|所有).{0,12}(?:已|均已|均|通过).{0,4}(?:核验|验证|核对|复核)"
    r"|(?:已完成|完成了)(?:全部|所有|全面).{0,6}(?:核验|验证|核对|复核)"
    r"|(?:全文|整份(?:报告|文档|研报)).{0,12}(?:已|已经|完成|通过).{0,6}(?:核验|验证|核对|复核)"
    r"|(?:全文|整份(?:报告|文档|研报)).{0,8}(?:核验|验证|核对|复核)"
    r"(?:已)?(?:完成|通过|完毕|无误)"
    r"|^\s*(?:fully|thoroughly|exhaustively)\s+(?:cross[- ]?)?verified"
    r"|(?:the\s+)?(?:entire|full|whole)\s+(?:document|report|paper)\s+"
    r"(?:has been|is|was)\s+(?:fully\s+)?verified"
    r"|(?:all|every)\s+(?:findings?|claims?|figures?|results?)\s+(?:have been |are )?verified",
    re.IGNORECASE,
)


def _contradicts_incomplete_work(text: str) -> bool:
    for sentence in re.split(r"[。！？\n.!?]", text):
        for match in _BLANKET_VERIFICATION.finditer(sentence):
            claim = sentence[max(0, match.start() - 24):match.end() + 24]
            if re.search(
                r"(?:已声明|列明|上述)(?:的)?(?:检查|核验项)"
                r"|\b(?:declared|listed) checks?\b",
                claim,
                re.IGNORECASE,
            ):
                continue
            # Negation must qualify this claim, not an earlier clause such as
            # "reviewer did not finish, but all findings are verified".
            prefix = sentence[max(0, match.start() - 24):match.start()]
            if re.search(
                r"(?:尚未|未|不能|无法|并非|不应|不要)[^，,；;但。]{0,6}$"
                r"|\b(?:not|cannot|can't)(?:\s+\w+){0,2}\s*$", prefix, re.I,
            ):
                continue
            return True
    return False
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
    if label:
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
    from plugins.tools._verification import project_checks

    verification = project_checks(jobs)
    required_gaps = [
        job for job in jobs if job.get("required") is not False
        and job.get("coverage_status", job.get("status")) != "complete"
    ]
    acquisition_limits = [
        {"job_id": job.get("job_id"), **observation}
        for job in jobs for observation in job.get("content_acquisition", [])
        if isinstance(observation, dict) and not observation.get("obtained")
    ]
    for job in required_gaps:
        gaps.append({
            "code": "member_job_incomplete", "job_id": str(job.get("job_id") or ""),
            "agent": str(job.get("agent") or ""),
            "reason": str(job.get("reason") or (
                "verification_not_passed" if job.get("verification_checks") else "unknown"
            )),
        })
    for task in unresolved:
        gaps.append(
            {"code": "task_unresolved", "task_id": task["id"], "description": task["description"]}
        )
    required_checks_by_work_item: dict[str, list[dict[str, Any]]] = {}
    for check in verification["checks"]:
        if check["required"]:
            required_checks_by_work_item.setdefault(check["work_item_id"], []).append(check)
    for task in board:
        if not task["verification_required"] or task["resolution"] not in {"resolved", "cancelled"}:
            continue
        checks = required_checks_by_work_item.get(task["id"], [])
        planned_ids = [
            requirement["check_id"] for requirement in task["verification_requirements"]
        ]
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
    if (wind.get("status") == "partial" and wind.get("run_status") != "complete"
            and not any(counts.get(k, 0) for k in _COUNTERS[1:])):
        gaps.append({"code": "team_coverage_incomplete"})

    # Blanket assurance is unsupported even when every *declared* check passed:
    # declared checks only prove their bounded criteria and versions.  Scoped
    # statements such as "all declared checks passed" remain publishable.
    contradictory = _contradicts_incomplete_work(text)
    if contradictory:
        gaps.append({"code": "unsupported_verification_claim"})
    system = source in _INTERNAL_SOURCES or not is_user_report(text) or contradictory
    if system:
        gaps.append({"code": "synthesis_unavailable"})
        if not is_user_report(text) and source not in _INTERNAL_SOURCES:
            gaps.append({"code": "invalid_user_report"})
    if stopped_by and stopped_by not in {"final_answer", "submit_report"}:
        gaps.append({"code": "execution_stopped", "reason": stopped_by})
    status = answer_status or "best_effort"
    if gaps and status == "complete":
        status = "partial"
    if system:
        status = "not_found"
    kind = "system_status" if system else "complete" if status == "complete" else "partial"
    contract = {
        "version": 3,
        "source": "system" if system else "model",
        "kind": kind,
        "answer_status": status,
        "stopped_by": stopped_by,
        "input_source": source,
        "gaps": gaps,
        "task_board": board,
        "task_board_basis": "coordinator_declared",
        "wind_down": {
            "status": str(wind.get("status") or "unknown"), **counts,
            "run_status": str(wind.get("run_status") or "unknown"),
        },
        "artifact_verification": "not_assessed",
        "job_outcomes": jobs,
        "required_work_basis": "dispatch_declared",
        "verification": verification["status"],
        "verification_basis": verification["basis"] if verification["checks"] else "execution_limits_only",
        "verification_checks": verification["checks"],
        "acquisition_limits": acquisition_limits,
    }
    zh = _chinese(question, language)
    notes: list[str] = []
    verification_notes: list[str] = []
    if verification["checks"]:
        verification_notes.append(
            "以下结论仅针对列明版本与检查项，不代表整份报告或其他版本已通过核验："
            if zh else "Verdicts cover only the declared checks and versions, not the entire report:"
        )
        labels = {"pass": "通过", "fail": "未通过", "unchecked": "未检查"}
        for check in verification["checks"]:
            verdict = labels.get(check["verdict"], "未检查") if zh else check["verdict"]
            verification_notes.append(
                f"- {_label(check['criterion'])}: {verdict} "
                f"({'版本' if zh else 'version'}={check['binding_id'][:12]})"
            )
    if required_gaps:
        notes.append(
            "以下必要成员任务或检查仍有缺口；已返回的工具观测不等于核验通过："
            if zh else "Required member jobs or checks remain incomplete; observations are not verification:"
        )
        notes.extend(
            f"- {_label(job.get('agent') or job.get('job_id'))}: "
            f"{_label(job.get('reason') or 'verification_not_passed')} ({_label(job.get('job_id'))})"
            for job in required_gaps[:20]
        )
        if len(required_gaps) > 20:
            notes.append(
                f"另有 {len(required_gaps) - 20} 项，完整列表见运行记录。"
                if zh else f"{len(required_gaps) - 20} more jobs are listed in the run record."
            )
    if contradictory:
        notes.append(
            "候选报告声称核验通过，但与执行记录矛盾，因此未发布该候选正文。"
            if zh else "The candidate claimed verification contrary to execution records and was withheld."
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
    if unresolved:
        notes.append("任务板尚未解决的事项：" if zh else "Unresolved task-board items:")
        notes.extend(f"- {_label(task['description'] or task['id'])}" for task in unresolved[:20])
        if len(unresolved) > 20:
            notes.append(
                f"另有 {len(unresolved) - 20} 项，详见任务板。"
                if zh
                else f"{len(unresolved) - 20} more items remain on the task board."
            )
    if counts:
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
        text = minimal_best_effort_answer(question, safe_stop, language=language)
        text += "\n\n" + intro
        text += "\n\n" + (
            "最终综合未形成可用报告；本状态说明未核验文件内容或下载可用性。"
            if zh
            else "Final synthesis is unavailable; this status does not verify file contents or downloads."
        )
    elif kind == "partial":
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
    if verification_notes:
        text += (
            "\n\n" + ("### 核验范围\n\n" if zh else "### Verification scope\n\n")
            + "\n\n".join(verification_notes)
        )
    if acquisition_limits:
        text += "\n\n" + (
            "### 内容读取边界\n\n以下工具尝试未取得完整内容；是否影响具体结论须按证据判断，"
            "不能将这些尝试当作已读或已核验：\n\n"
            if zh else "### Content access limits\n\nThese attempts did not obtain complete content. "
            "Their relevance depends on the claim; they are not evidence of reading or verification:\n\n"
        )
        text += "\n".join(
            f"- {_label(item.get('tool'))}: {_label(item.get('source'))} "
            f"({_label(item.get('status'))})"
            + (f" — {_label(item.get('detail'))}" if item.get("detail") else "")
            for item in acquisition_limits[:20]
        )
        if len(acquisition_limits) > 20:
            text += (
                f"\n另有 {len(acquisition_limits) - 20} 项读取限制，完整列表见运行记录。"
                if zh else f"\n{len(acquisition_limits) - 20} more access limits are in the run record."
            )
    return {
        "final_answer": text,
        "final_content": text,
        "final_answer_source": "deterministic_fallback" if system else source,
        "answer_status": status,
        "answer_sentinel": "<ANSWER_NOT_FOUND>" if status == "not_found" else "",
        "report_contract": contract,
    }
