"""Audit the logical recovery call after the regular agent loop has ended."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from frontier_agent.components.observers.trajectory import TrajectoryFileObserver
from frontier_agent.core.loop_types import AgentLoopResult, LoopConfig, TurnContext
from frontier_agent.core.messages import Message, assistant_msg, text_of
from frontier_agent.core.runtime.loop._response import extract_usage
from frontier_agent.infra.usage_meter import record_llm_usage

logger = logging.getLogger(__name__)


async def traced_recovery_call(
    call: Callable[[], Awaitable[Any]],
    *,
    messages: list[Message],
    path: Path | None,
    record: dict[str, Any],
) -> Any:
    """Record one logical call; do not pretend to observe its provider retries."""
    observer = None
    started = time.monotonic()
    response = None
    outcome = "cancelled"
    record.update(usage_status="unavailable", scope="logical_recovery_call")
    try:
        if path is not None:
            observer = TrajectoryFileObserver(path.parent, filename=path.stem)
            await observer.on_loop_start(
                LoopConfig(
                    task_id=path.stem,
                    role_id="agent_team_main",
                    max_turns=1,
                )
            )
    except Exception:
        logger.warning("Cannot initialize recovery trace", exc_info=True)
        observer = None
    try:
        response = await call()
        outcome = "recovery_complete"
        return response
    except Exception as exc:
        outcome = "recovery_failed"
        record["error_type"] = type(exc).__name__
        raise
    finally:
        try:
            usage = extract_usage(response) if response is not None else None
        except Exception:
            logger.warning("Cannot extract recovery usage", exc_info=True)
            usage = None
        record.update(outcome=outcome, duration_ms=int((time.monotonic() - started) * 1000))
        if usage:
            record.update(usage_status="reported", usage=usage)
            record_llm_usage(
                **{
                    key: usage.get(key, "" if key in {"model", "provider"} else 0)
                    for key in (
                        "model",
                        "provider",
                        "prompt_tokens",
                        "completion_tokens",
                        "cache_read_tokens",
                        "cache_write_tokens",
                    )
                }
            )
        if observer is not None:
            try:
                content = text_of(getattr(response, "content", "")) if response else ""
                history = [*messages, assistant_msg(content)]
                await observer.on_llm_response(
                    TurnContext(
                        turn=1,
                        max_turns=1,
                        task_id=path.stem if path else "recovery",
                        role_id="agent_team_main",
                        ai_text=content,
                        thinking="",
                        tool_calls=[],
                        messages=history,
                        usage=usage,
                        metadata=dict(record),
                    )
                )
                await observer.on_loop_end(
                    AgentLoopResult(
                        messages=history,
                        final_content=content,
                        turns_used=1,
                        stopped_by=outcome,
                    )
                )
            except Exception:
                logger.warning("Cannot finish recovery trace", exc_info=True)
