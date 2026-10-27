"""Observer that retries leaked-text tool calls with escalating temperature."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable

from frontier_agent.core.loop_types import BaseObserver, Intervention, TurnContext

logger = logging.getLogger(__name__)

_METADATA_COUNT_KEY = "_leak_retry_count"
_METADATA_TOTAL_KEY = "_leak_retry_total"
_METADATA_TEMP_KEY = "_llm_temp_override"

_DEFAULT_TEMPERATURES: tuple[float, ...] = (0.3, 0.6, 1.0)

# XML wrappers the parser already tries — detect-only for signalling.
_LEAK_XML_RE = re.compile(
    r"<\s*(?:tool_call\b"
    r"|function\s+name\s*="
    r"|seed:tool_call\b"
    r"|seedtool_call\b"
    r"|seed:tool[-_]name\b"
    r")",
    re.IGNORECASE,
)

LEAKED_TOOL_CALL_NUDGE = (
    "Your previous response looks like an unstructured tool invocation. "
    "If you intend a new tool call, use the structured tool_calls interface. "
    "If you are reporting a completed or failed call, provide the final answer "
    "and its limitations; do not repeat that call solely to restate its result."
)


class LeakedToolCallRetryObserver(BaseObserver):
    """Detect text-only tool-call leaks and trigger a next-turn retry.

    Args:
        tool_names: iterable of allowed tool identifiers. Used to guard the
            free-text mention check ("I will run_python_code(...)" only
            counts as a leak if ``run_python_code`` is in this set).
        temperatures: escalation sequence. Defaults to ``(0.3, 0.6, 1.0)``.
        enabled: master switch. Disables without removing from the stack.
        max_nudges_per_task: total cap on retries triggered per loop run
            (regardless of how many distinct turns leak). Prevents
            pathological tight loops when the model ignores the nudge.
    """

    critical = True

    def __init__(
        self,
        tool_names: Iterable[str],
        *,
        temperatures: tuple[float, ...] = _DEFAULT_TEMPERATURES,
        enabled: bool = True,
        max_nudges_per_task: int | None = None,
    ) -> None:
        self._tool_names: frozenset[str] = frozenset(tool_names)
        self._temperatures = temperatures
        self._enabled = enabled and bool(temperatures)
        # Default cap = len(temperatures) so each temperature is tried once.
        self._max_nudges = (
            max_nudges_per_task if max_nudges_per_task is not None else len(temperatures)
        )
        # Tool syntax must be local to the name. A report may mention a tool
        # alongside unrelated parentheses (e.g. PE(TTM)) or quote past calls.
        self._bare_call_re: re.Pattern[str] | None = None
        self._intent_re: re.Pattern[str] | None = None
        if self._tool_names:
            name = r"\b(?:" + "|".join(re.escape(n) for n in self._tool_names) + r")\b"
            self._bare_call_re = re.compile(
                r"\s*`?" + name + r"`?\s*(?:\([\s\S]*\)|\{[\s\S]*\})`?\s*[.;]?\s*",
                re.IGNORECASE,
            )
            # Require an affirmative invocation clause. Neither retrospective
            # prose nor a future verb elsewhere in the report is sufficient.
            intent = (
                r"(?:\bi(?: will|'ll| am going to|'m going to)\s+"
                r"(?:(?:call|run|invoke|use|execute)\s+)?"
                r"|\blet me\s+(?:call|run|invoke|use|execute)\s+"
                r"|\bnow\s+(?:call|run|invoke|use|execute)\s+"
                r"|\bcalling\s+"
                r"|(?:现在|接下来|下一步|我将|我要|让我|准备)(?:调用|执行|使用)\s*)"
            )
            self._intent_re = re.compile(
                r"(?:^|[.!?。！？\n])\s*(?:next,\s*)?" + intent + r"`?" + name,
                re.IGNORECASE,
            )

    # ------------------------------------------------------------------ API

    async def on_llm_response(self, ctx: TurnContext) -> Intervention | None:
        if not self._enabled:
            return None

        # A structured tool call was parsed — nothing to retry. Also reset
        # the escalation counter so a future leak starts at 0.3 again. Keep
        # the run-wide count: alternating leaks and calls must stay bounded.
        if ctx.tool_calls:
            ctx.metadata.pop(_METADATA_COUNT_KEY, None)
            return None

        if not self._looks_like_leak(ctx.ai_text):
            return None

        count = int(ctx.metadata.get(_METADATA_COUNT_KEY, 0))
        total = int(ctx.metadata.get(_METADATA_TOTAL_KEY, 0))
        if total >= self._max_nudges:
            logger.info(
                "[LeakedToolCallRetry] Exhausted retry budget (%d) — "
                "letting default no_tool handler take over.",
                self._max_nudges,
            )
            return None

        temp_index = min(count, len(self._temperatures) - 1)
        next_temp = float(self._temperatures[temp_index])

        ctx.metadata[_METADATA_COUNT_KEY] = count + 1
        ctx.metadata[_METADATA_TOTAL_KEY] = total + 1
        ctx.metadata[_METADATA_TEMP_KEY] = next_temp

        logger.warning(
            "[LeakedToolCallRetry] turn=%d | leaked content, scheduling retry "
            "with temperature=%.1f (retry %d/%d)",
            ctx.turn,
            next_temp,
            total + 1,
            self._max_nudges,
        )

        return Intervention(
            inject_messages=[LEAKED_TOOL_CALL_NUDGE],
            continue_to_next_turn=True,
        )

    # --------------------------------------------------------------- helpers

    def _looks_like_leak(self, text: str) -> bool:
        """Detect invocation intent, standalone call syntax, or XML residue."""
        if not text:
            return False
        sample = text[:4000]
        if _LEAK_XML_RE.search(sample):
            return True
        if self._bare_call_re is None or self._intent_re is None:
            return False
        if self._intent_re.search(sample):
            return True
        # Only strip a fence that wraps the entire response, not a quoted code
        # example embedded in a finished report. Do not fullmatch a truncation.
        body = text.strip()
        if body.startswith("```") and body.endswith("```") and "\n" in body:
            body = body.split("\n", 1)[1][:-3].strip()
        return bool(self._bare_call_re.fullmatch(body))


__all__ = ["LEAKED_TOOL_CALL_NUDGE", "LeakedToolCallRetryObserver"]
