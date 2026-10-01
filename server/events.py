"""SSE event vocabulary for the web platform's realtime push layer.

This module is the *push* half only. It defines the JSON envelope the server
emits over SSE and a small serialiser. It does **not** own persistence: replay
reads the runtime's ``react_agent.jsonl`` trajectory (tech-stack.md §5.2/§6.2),
and the bridge never writes to disk itself.

Event types (subset of requirements-user-layer.md §5):
    run_started         lifecycle, not persisted
    assistant_delta     streamed token delta (only realtime; safe to drop on backpressure)
    tool_started        tool invocation began
    tool_finished       tool returned (ok / error + detail)
    run_completed       run finished with a final answer
    run_failed          run raised
    run_stopped         cooperative stop fired
    artifact_created    a deliverable was written to ws/outputs
    steer_queued        user direction accepted and handed to the worker (F21)
    steer_applied       that direction was injected at a turn boundary (F21)
    approval_requested  a confirm-level tool call is waiting on the user (F21)
    approval_resolved   the user's verdict for one approval id (F21)
    warning             non-fatal notice (e.g. partial injection)

The four control events were emitted as bare strings before F21; they are listed
here so the vocabulary has one home. They are *control* frames: the web client's
SSE cursor deliberately does not advance on them (``web/src/sse.ts``), and their
durable record is ``control_records`` — not a second event log.
"""

from __future__ import annotations

import json
import time
from enum import StrEnum
from typing import Any

EVENT_TYPES = (
    "run_started",
    "assistant_delta",
    "tool_started",
    "tool_finished",
    "run_completed",
    "run_failed",
    "run_stopped",
    "artifact_created",
    "steer_queued",
    "steer_applied",
    "approval_requested",
    "approval_resolved",
    "warning",
)


class EventType(StrEnum):
    RUN_STARTED = "run_started"
    ASSISTANT_DELTA = "assistant_delta"
    TOOL_STARTED = "tool_started"
    TOOL_FINISHED = "tool_finished"
    RUN_COMPLETED = "run_completed"
    RUN_FAILED = "run_failed"
    RUN_STOPPED = "run_stopped"
    ARTIFACT_CREATED = "artifact_created"
    STEER_QUEUED = "steer_queued"
    STEER_APPLIED = "steer_applied"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    WARNING = "warning"


def make_event(type_: str, **data: Any) -> dict[str, Any]:
    """Build an SSE event dict with a monotonic-ish timestamp."""
    return {"type": type_, "ts": time.time(), **data}


def to_sse(payload: dict[str, Any]) -> str:
    """Serialise an event dict to an SSE ``data:`` frame."""
    return "data: " + json.dumps(payload, ensure_ascii=False) + "\n\n"


# Lifecycle events must never be dropped under backpressure; only deltas may be.
_DROPPABLE = {EventType.ASSISTANT_DELTA.value}


def is_droppable(event: dict[str, Any]) -> bool:
    """True if this event may be discarded under backpressure.

    Deltas are droppable because the trajectory file holds the full per-turn
    content for replay; lifecycle events are not (tech-stack.md §5.2 backpressure).
    """
    return event.get("type") in _DROPPABLE
