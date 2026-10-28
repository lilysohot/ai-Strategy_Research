"""Translate engine exit reasons into Web interruption semantics."""

from __future__ import annotations

import json
from typing import Any

from server.config import run_dir_for


def report_task_board(contract: Any) -> list[dict[str, str]] | None:
    """Expose only board fields from the terminal contract, never worker metadata."""
    if not isinstance(contract, dict) or not isinstance(contract.get("task_board"), list):
        return None
    fields = {
        "id", "description", "resolution", "notes", "gap",
        "verification_status", "verification_execution_status",
    }
    return [
        {key: value for key, value in task.items() if key in fields and isinstance(value, str)}
        for task in contract["task_board"] if isinstance(task, dict)
    ]


def read_terminal_task_board(run_id: str) -> list[dict[str, str]] | None:
    """Read the same terminal projection after reconnect; caller authorizes the run."""
    try:
        summary = json.loads((run_dir_for(run_id) / "summary.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return report_task_board(summary.get("report_contract")) if isinstance(summary, dict) else None


def interruption_reason(reason: str | None) -> str:
    """Recognize natural single-agent and team completion markers.

    Keep unknown reasons conservative. Errors are checked separately by the
    caller, so this never promotes a failed worker to a successful run.
    """
    return "" if reason in {"no_tool", "final_answer"} else reason or ""


def is_legacy_normal_completion(status: str, reason: str | None, error: str | None) -> bool:
    """Recognize old rows misclassified before normal exits were distinguished."""
    return status in {"stopped", "completed"} and reason == "no_tool" and not error


def apply_input_request_outcome(frame: dict[str, Any], request: Any) -> None:
    """Project a committed request into every terminal presentation channel."""
    if not isinstance(request, dict) or request.get("status") != "pending" or not request.get("request_id"):
        return
    frame["input_request"] = request
    frame.setdefault("worker_stopped_by", frame.get("stopped_by"))
    frame["stopped_by"] = "input_required"
    frame["answer_status"] = "partial"
    notice = "服务端最终状态：已创建待补资料请求，请在会话中补充后继续分析。以下为补数前的研究结果。"
    answer = str(frame.get("final_answer") or "").strip()
    if not answer.startswith(notice):
        frame["final_answer"] = f"{notice}\n\n{answer}".strip()
