"""Read-only preview adapter for Super-link run output (SSE-T05).

The ordinary run stream already receives Bridge/Worker frames through
``Orchestrator._publish``.  This module copies the display-only subset into a
process-local hub keyed by participant session, so a space SSE connection can
show live text, thinking and tool progress without changing the run stream,
the durable event ledger or the business state.

Deployment stays single-owner (technical design §11.1): only the API process
that spawned the worker can produce previews.  Another instance still serves
facts and archived traces; it simply has no local preview to forward.

Nothing here executes tools, persists output or advances the space cursor.
Preview frames are explicitly droppable; a gap is reported as ``sl.output_reset``
so the client rebuilds from the archived trace instead of splicing fragments.
"""

from __future__ import annotations

import asyncio
import enum
import uuid
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from server.bridge import redact_deep
from server.events import EventType

PREVIEW_EVENT = "sl.run.preview"
OUTPUT_RESET_EVENT = "sl.output_reset"

PREVIEW_TEXT_LIMIT = 4096
_MEMBER_LIMIT = 128
_DETAIL_LIMIT = 400


class PreviewKind(enum.StrEnum):
    CONTENT = "content"
    THINKING = "thinking"
    TOOL = "tool"
    NOTICE = "notice"
    TERMINAL = "terminal"


@dataclass(frozen=True)
class PreviewItem:
    """One preview frame payload; the connection adds space/epoch/seq."""

    run_id: str
    kind: PreviewKind
    data: dict[str, Any]


@dataclass(frozen=True)
class OutputReset:
    """Preview frames for these runs were dropped; rebuild from archive."""

    run_ids: tuple[str, ...]


def _text(value: Any, limit: int = PREVIEW_TEXT_LIMIT) -> str:
    if not isinstance(value, str):
        return ""
    return redact_deep(value)[:limit]


def _chunks(value: Any, limit: int = PREVIEW_TEXT_LIMIT) -> list[str]:
    if not isinstance(value, str) or not value:
        return []
    # Redact before splitting so a secret can never straddle a chunk boundary
    # and survive partially.
    redacted = redact_deep(value)
    return [redacted[i : i + limit] for i in range(0, len(redacted), limit)]


def _member(payload: dict[str, Any]) -> dict[str, str]:
    agent_id = payload.get("agent_id")
    agent_kind = payload.get("agent_kind")
    return {
        "agent_id": agent_id[:_MEMBER_LIMIT] if isinstance(agent_id, str) else "",
        "agent_kind": agent_kind[:_MEMBER_LIMIT] if isinstance(agent_kind, str) else "",
    }


def _agent_key(member: dict[str, str]) -> str:
    return f"{member['agent_kind']}|{member['agent_id']}"


def _turn(payload: dict[str, Any]) -> int | None:
    turn = payload.get("turn")
    if isinstance(turn, bool) or not isinstance(turn, int):
        return None
    return turn


def _block_key(member: dict[str, str], turn: int | None, kind: str) -> str:
    return f"{kind}|{_agent_key(member)}|{turn if turn is not None else '?'}"


def preview_items(payload: Any) -> list[PreviewItem]:
    """Map one live run frame to zero or more preview items.

    Pure by design: callers keep the original frame untouched, and no branch
    reads the worker, the database or the event ledger.  ``output`` (the full,
    possibly huge tool result) is deliberately never copied; the archived trace
    is the authoritative source for it.
    """

    if not isinstance(payload, dict):
        return []
    type_ = payload.get("type")
    if not isinstance(type_, str):
        return []
    member = _member(payload)
    turn = _turn(payload)
    items: list[PreviewItem] = []

    def add(kind: PreviewKind, key: str, data: dict[str, Any]) -> None:
        items.append(
            PreviewItem(
                run_id="",  # filled by RunOutputHub.publish
                kind=kind,
                data={"member": member, "turn": turn, "block_key": key, **data},
            )
        )

    if type_ == EventType.ASSISTANT_DELTA.value:
        text = payload.get("text")
        thinking = payload.get("thinking_text")
        # One frame must not carry two blocks: split so the client can key each
        # fragment by member, turn and kind without guessing.
        for chunk in _chunks(thinking):
            add(
                PreviewKind.THINKING,
                _block_key(member, turn, PreviewKind.THINKING),
                {"text": chunk},
            )
        for chunk in _chunks(text):
            add(
                PreviewKind.CONTENT,
                _block_key(member, turn, PreviewKind.CONTENT),
                {"text": chunk},
            )
        return items

    if type_ == EventType.TOOL_STARTED.value:
        call_id = payload.get("tool_call_id")
        call_id = call_id[:_MEMBER_LIMIT] if isinstance(call_id, str) else ""
        name = payload.get("tool_name") or payload.get("name") or ""
        key = (
            f"tool|{_agent_key(member)}|{call_id}"
            if call_id
            else _block_key(member, turn, "tool")
        )
        add(
            PreviewKind.TOOL,
            key,
            {
                "tool": {
                    "call_id": call_id,
                    "name": _text(name, _MEMBER_LIMIT),
                    "state": "started",
                }
            },
        )
        return items

    if type_ == EventType.TOOL_FINISHED.value:
        call_id = payload.get("tool_call_id")
        call_id = call_id[:_MEMBER_LIMIT] if isinstance(call_id, str) else ""
        name = payload.get("tool_name") or payload.get("name") or ""
        key = (
            f"tool|{_agent_key(member)}|{call_id}"
            if call_id
            else _block_key(member, turn, "tool")
        )
        ms = payload.get("ms")
        add(
            PreviewKind.TOOL,
            key,
            {
                "tool": {
                    "call_id": call_id,
                    "name": _text(name, _MEMBER_LIMIT),
                    "state": "finished",
                    "ok": bool(payload.get("ok")),
                    "skipped": bool(payload.get("skipped")),
                    "detail": _text(payload.get("detail"), _DETAIL_LIMIT),
                    "ms": ms if isinstance(ms, int) and not isinstance(ms, bool) else None,
                }
            },
        )
        return items

    if type_ == EventType.WARNING.value:
        detail = _text(payload.get("detail"), _DETAIL_LIMIT)
        if not detail:
            return []
        add(
            PreviewKind.NOTICE,
            _block_key(member, turn, "notice"),
            {"text": detail},
        )
        return items

    if type_ in {
        EventType.RUN_COMPLETED.value,
        EventType.RUN_FAILED.value,
        EventType.RUN_STOPPED.value,
    }:
        if type_ == EventType.RUN_COMPLETED.value:
            status = "completed"
        elif type_ == EventType.RUN_STOPPED.value:
            status = "stopped"
        else:
            status = "failed"
        stopped_by = payload.get("stopped_by")
        add(
            PreviewKind.TERMINAL,
            _block_key(member, turn, "terminal"),
            {
                "status": status,
                "stopped_by": (
                    stopped_by[:_MEMBER_LIMIT] if isinstance(stopped_by, str) else ""
                ),
                "error": _text(payload.get("error")),
            },
        )
        return items

    return []


def _with_run_id(run_id: Any, items: list[PreviewItem]) -> list[PreviewItem]:
    normalized = str(run_id)
    return [
        PreviewItem(run_id=normalized, kind=item.kind, data=item.data)
        for item in items
    ]


class OutputSubscription:
    """Bounded per-connection preview queue.

    An overflow must never block the worker or silently splice text.  Pending
    previews are discarded and collapsed into one reset item covering every
    affected run; the producer sends that reset before forwarding that run's
    next frame.
    """

    def __init__(self, *, max_frames: int) -> None:
        self.max_frames = max(1, max_frames)
        self._items: deque[PreviewItem | OutputReset] = deque()
        self._closed = False
        self._wake = asyncio.Event()

    @property
    def closed(self) -> bool:
        return self._closed

    def offer(self, item: PreviewItem) -> None:
        if self._closed:
            return
        if len(self._items) >= self.max_frames:
            dropped: set[str] = set()
            for queued in self._items:
                if isinstance(queued, OutputReset):
                    dropped.update(queued.run_ids)
                else:
                    dropped.add(queued.run_id)
            dropped.add(item.run_id)
            self._items.clear()
            self._items.append(OutputReset(tuple(sorted(dropped))))
        else:
            self._items.append(item)
        self._wake.set()

    def close(self) -> None:
        self._closed = True
        self._items.clear()
        self._wake.set()

    async def next(self) -> PreviewItem | OutputReset | None:
        while True:
            if self._items:
                return self._items.popleft()
            if self._closed:
                return None
            self._wake.clear()
            if self._items or self._closed:
                continue
            await self._wake.wait()


class RunOutputHub:
    """Process-local preview fan-out keyed by participant session."""

    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[OutputSubscription]] = {}

    def subscribe(
        self, session_ids: Iterable[uuid.UUID], *, max_frames: int
    ) -> OutputSubscription:
        subscription = OutputSubscription(max_frames=max_frames)
        for session_id in frozenset(session_ids):
            self._subs.setdefault(session_id, set()).add(subscription)
        return subscription

    def unsubscribe(self, subscription: OutputSubscription) -> None:
        subscription.close()
        for session_id in tuple(self._subs):
            subscribers = self._subs[session_id]
            subscribers.discard(subscription)
            if not subscribers:
                self._subs.pop(session_id, None)

    def observed(self, session_id: uuid.UUID) -> bool:
        return session_id in self._subs

    def publish(self, session_id: uuid.UUID, run_id: str, payload: Any) -> None:
        subscribers = self._subs.get(session_id)
        if not subscribers:
            return
        items = _with_run_id(run_id, preview_items(payload))
        if not items:
            return
        for subscription in tuple(subscribers):
            for item in items:
                subscription.offer(item)

    def subscription_count(self, session_id: uuid.UUID) -> int:
        return len(self._subs.get(session_id, ()))


HUB = RunOutputHub()


def publish(session_id: str | None, run_id: str, payload: Any) -> None:
    """Best-effort bridge used by the orchestrator; never raises to the caller."""

    if not session_id:
        return
    try:
        session_uuid = uuid.UUID(session_id)
    except (ValueError, AttributeError, TypeError):
        return
    if not HUB.observed(session_uuid):
        return
    HUB.publish(session_uuid, run_id, payload)
