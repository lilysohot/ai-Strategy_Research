"""Request-boundary delivery acknowledgement for the stateful workflow's A4 ledger."""

from __future__ import annotations

import copy
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from typing import Any

from frontier_agent.components.middleware.llm.proxy import LLMProxy
from frontier_agent.core.llm import LLMResponse, StreamDelta
from frontier_agent.core.messages import Message
from frontier_agent.infra.llm.fallback import LLMFallbackChain
from frontier_agent.infra.llm_adapter import FallbackLLM
from plugins.corpus.ledger import ConsumptionLedger, get_run_ledger

logger = logging.getLogger(__name__)


class SemanticDeliveryLLM:
    """Confirm the exact successful request, after loop compaction and middleware.

    A failed/never-issued request cannot mark evidence delivered. In streaming,
    the first provider response delta acknowledges receipt of the request. This
    wrapper neither changes messages nor upgrades legacy fetched counters.
    """

    def __init__(self, inner: Any, ledger: ConsumptionLedger | None = None) -> None:
        self.inner = inner
        self.ledger = ledger

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def _confirm(self, messages: list[Message]) -> None:
        try:
            ledger = self.ledger if self.ledger is not None else get_run_ledger()
            ledger.semantic.confirm_request(messages)
        except Exception:
            logger.exception("semantic delivery acknowledgement failed; evidence stays unverified")

    async def chat(self, messages: list[Message], **kwargs: Any) -> LLMResponse:
        sent = copy.deepcopy(messages)
        response = await self.inner.chat(messages, **kwargs)
        self._confirm(sent)
        return response

    async def stream(self, messages: list[Message], **kwargs: Any) -> AsyncIterator[StreamDelta]:
        sent = copy.deepcopy(messages)
        confirmed = False
        async for delta in self.inner.stream(messages, **kwargs):
            if not confirmed:
                self._confirm(sent)
                confirmed = True
            yield delta


def with_semantic_delivery(llm: Any, ledger: ConsumptionLedger | None = None) -> Any:
    """Preserve shared middleware clients; install acknowledgement beneath their rewrites."""
    if isinstance(llm, LLMProxy):
        scoped = copy.copy(llm)
        scoped.inner = with_semantic_delivery(llm.inner, ledger)
        return scoped
    if isinstance(llm, LLMFallbackChain):
        scoped_chain = copy.copy(llm)
        scoped_chain.entries = [
            replace(entry, model=with_semantic_delivery(entry.model, ledger))
            for entry in llm.entries
        ]
        return scoped_chain
    if isinstance(llm, FallbackLLM):
        scoped_fallback = copy.copy(llm)
        scoped_fallback.primary = with_semantic_delivery(llm.primary, ledger)
        scoped_fallback.fallback = with_semantic_delivery(llm.fallback, ledger)
        return scoped_fallback
    return SemanticDeliveryLLM(llm, ledger)
