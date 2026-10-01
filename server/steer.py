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

F21: each line carries the server-generated ``control_id`` of its
``control_records`` row, and the observer reports adoption back to the worker's
frame channel. A steer parked in the inbox when the run ends is *never* injected
— "queued" and "took effect" have to stay distinguishable, and only the observer
knows which of the two happened.
"""

from __future__ import annotations

import logging
import queue
from collections.abc import Callable
from dataclasses import dataclass

from frontier_agent.core.loop_types import Intervention, TurnContext

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SteerLine:
    """One queued direction: its text plus the control record it belongs to."""

    text: str
    control_id: str | None = None


class SteerInbox:
    """Thread-safe FIFO of user steering lines (producer: stdin thread)."""

    def __init__(self) -> None:
        self._q: queue.SimpleQueue[SteerLine] = queue.SimpleQueue()

    def enqueue(self, message: str, control_id: str | None = None) -> None:
        """Queue one steering line; blank lines are ignored."""
        text = message.strip()
        if text:
            self._q.put(SteerLine(text=text, control_id=control_id))

    def drain(self) -> list[str]:
        """Atomically take every queued line (oldest first), texts only."""
        return [line.text for line in self.drain_lines()]

    def drain_lines(self) -> list[SteerLine]:
        """Same as :meth:`drain`, keeping the control ids for adoption reporting."""
        out: list[SteerLine] = []
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

    ``on_adopted`` receives the ``control_id`` list of the lines that are about
    to be injected. It fires exactly at the boundary the return value is built
    for, which is the only moment "this steer took effect" is true; a failure in
    it must never break the run, so it is guarded.
    """

    critical: bool = True

    def __init__(
        self,
        inbox: SteerInbox,
        on_adopted: Callable[[list[str]], None] | None = None,
    ) -> None:
        self.inbox = inbox
        self._on_adopted = on_adopted

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        # A turn without tool calls is the model finishing; injecting then
        # would leave a dangling user message on a run about to stop.
        if not getattr(ctx, "tool_calls", None):
            return None
        lines = self.inbox.drain_lines()
        if not lines:
            return None
        if self._on_adopted is not None:
            adopted = [line.control_id for line in lines if line.control_id]
            if adopted:
                try:
                    self._on_adopted(adopted)
                except Exception:
                    # Reporting is bookkeeping: the injection below is the
                    # behaviour the user asked for, and it must still happen.
                    logger.exception("steer adoption report failed")
        return Intervention(inject_messages=[line.text for line in lines])
