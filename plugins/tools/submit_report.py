"""submit_report — terminal tool for sub-agents (sibling of finalize_answer)."""

from __future__ import annotations

import asyncio
import json
import logging

from frontier_agent.core.tool import ToolOutcome, tool
from plugins.tools._handoff import validate_handoff_refs
from plugins.tools._verification import VerificationResult, commit_results, validate_results

logger = logging.getLogger(__name__)

REPORT_TEXT_MAX_CHARS = 24_000


@tool
async def submit_report(
    content: str,
    confidence: float = 0.7,
    attachments: list[str] | None = None,
    verification_results: list[VerificationResult] | None = None,
    finish: bool = True,
) -> str | ToolOutcome:
    """Submit your final research report and end this task.

    Normally call once to return to the main agent. For assigned checks,
    finish=false checkpoints structured verdicts and lets this task continue.

    Args:
        content: The complete report in the mandatory format:
            ``Scope: ...\\nFinding: ...\\nEvidence:\\n  - ...\\nConfidence: ...``.
            Include exact values, source URLs, and code results — not just
            conclusions.
        confidence: Self-assessed confidence in [0, 1] that your findings
            are correct and well-sourced. Default 0.7.
        attachments: Up to eight exact ``ref`` values returned by
            ``publish_handoff``. Ordinary workspace paths are rejected.
        verification_results: Verdicts for the exact check_id/binding_id assigned
            in the task. A pass must cite every bound evidence key.
        finish: End the task by default. False requires verification_results.

    Returns:
        Short acknowledgement. The report body is surfaced to the main
        agent via ``<report agent="NAME">...</report>``.
    """
    text = (content or "").strip()
    if not isinstance(finish, bool) or (not finish and not verification_results):
        return ToolOutcome("Error: finish must be boolean; false requires check results.", is_error=True)
    if not text:
        return ToolOutcome(
            "submit_report rejected: `content` was empty. "
            "Pass the complete Scope/Finding/Evidence report in `content`.",
            is_error=True,
        )
    if len(text) > REPORT_TEXT_MAX_CHARS:
        return ToolOutcome(
            "Error: submit_report content exceeds the 24,000-character report "
            "limit. Keep the decision-relevant findings in `content`, publish "
            "large tables or files with publish_handoff, and pass their refs "
            "through `attachments`.",
            is_error=True,
        )

    try:
        manifests = await asyncio.to_thread(validate_handoff_refs, attachments)
        accepted = await asyncio.to_thread(validate_results, verification_results)
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return ToolOutcome(
            f"Error: submit_report attachment or verification rejected: {exc}", is_error=True,
        )
    commit_results(accepted)

    try:
        conf = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        conf = 0.7

    logger.info(
        "submit_report called: len=%d chars, confidence=%.2f, attachments=%d",
        len(text), conf, len(manifests),
    )
    if accepted:
        return json.dumps({"submitted": True, "finish": finish, "verification_results": accepted})
    return (
        f"Report submitted ({len(text)} chars, confidence={conf:.2f}, "
        f"attachments={len(manifests)}). "
        "Task loop will exit after this turn."
    )
