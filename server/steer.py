"""Live steering for web runs (plan cli-web-parity.md §6.2).

The orchestrator writes ``{"action":"steer","message":"..."}`` lines to the
worker's stdin; ``server.worker._stdin_watch`` feeds them into a
:class:`SteerInbox`, and the :class:`SteerObserver` drains that inbox at a
safe turn boundary — only after a turn that made tool calls, so the loop is
guaranteed to continue — returning a real ``Intervention(inject_messages=...)``
for the agent loop to append as the next user message.

Mirrors ``apodex/observers.py`` TerminalObserver semantics, but the inbox is
thread-safe via ``queue.SimpleQueue`` (the producer is the stdin reader
thread, the consumer is the asyncio loop) instead of the TTY-only
``asyncio.add_reader`` version in ``apodex/steer.py``.
"""

from __future__ import annotations

import queue

from frontier_agent.core.loop_types import Intervention, TurnContext


class SteerInbox:
    """Thread-safe FIFO of user steering lines (producer: stdin thread)."""

    def __init__(self) -> None:
        self._q: queue.SimpleQueue[str] = queue.SimpleQueue()

    def enqueue(self, message: str) -> None:
        """Queue one steering line; blank lines are ignored."""
        text = message.strip()
        if text:
            self._q.put(text)

    def drain(self) -> list[str]:
        """Atomically take every queued line (oldest first)."""
        out: list[str] = []
        while True:
            try:
                out.append(self._q.get_nowait())
            except queue.Empty:
                return out


class SteerObserver:
    """Injects queued steering lines as the next user message.

    ``critical`` must be True: ``notify_observers`` discards return values of
    passive observers, so a passive steer observer would silently drop every
    message.
    """

    critical: bool = True

    def __init__(self, inbox: SteerInbox) -> None:
        self.inbox = inbox

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        # A turn without tool calls is the model finishing; injecting then
        # would leave a dangling user message on a run about to stop.
        if not getattr(ctx, "tool_calls", None):
            return None
        steers = self.inbox.drain()
        if not steers:
            return None
        return Intervention(inject_messages=steers)
