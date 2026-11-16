"""Terminate the main-agent loop on a plain-text, no-tool turn."""

from __future__ import annotations

import logging
from typing import Any

from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.loop_types import BaseObserver, Intervention, TurnContext
from plugins.corpus.final_delivery import corpus_citation_readability_issue
from plugins.tools._bus_scope import resolve_bus_task_id
from plugins.tools.finalize_answer import finalize_gate
from plugins.tools.task_board import complete_delivery_tasks

logger = logging.getLogger(__name__)

_TRUNCATED_FINISH_REASONS = frozenset({"length", "max_tokens"})


def _write_accepted_record(scope: Any, text: str) -> None:
    """Commit the same normalized delivery record as ``deliver_answer``.

    This runs *before* the loop is told to stop: a bare-text answer must pass
    through the delivery record, not get an "accepted" note appended after the
    fact. A member report's old corpus conclusions are deliberately not reused.
    """
    from workflows.agent_team.delivery import (
        _DELIVERED_KEY,
        _DELIVERY_RECORD_KEY,
        _accepted_delivery_record,
        _content_sha256,
        _record_audit,
    )

    record = _accepted_delivery_record(
        content=text,
        version=1,
        corpus_conclusions=None,
        items=[],
        checks=[],
        manifest_committed=False,
    )
    record["channel"] = "bare_text"
    record["evidence_rebound"] = False
    scope.metadata[_DELIVERY_RECORD_KEY] = record
    scope.metadata[_DELIVERED_KEY] = text
    _record_audit(
        scope,
        "accepted",
        version=record["version"],
        content_sha256=_content_sha256(text),
        disposition_ids=[],
        check_ids=[],
        channel="bare_text",
        evidence_rebound=False,
    )


class BareTextFinalizeObserver(BaseObserver):
    critical = True

    def __init__(self) -> None:
        self._readability_repair_offered = False

    async def on_llm_response(self, ctx: TurnContext) -> Intervention | None:
        if ctx.tool_calls:
            # Further work may change the evidence. Do not revive an older
            # rejected draft if a later tool/model turn runs out of time.
            if isinstance(ctx.metadata, dict):
                ctx.metadata.pop("final_answer_candidate", None)
            return None
        text = (ctx.ai_text or "").strip()
        if not text:
            # Nothing said and no tool — let the loop's no-tool recovery nudge.
            return None

        # A truncated body is an UNFINISHED CANDIDATE, never a publication.
        # This must precede the gate and the last-turn bypass: even with every
        # task resolved, finishing here would end the run on a cut-off answer.
        if str(ctx.metadata.get("finish_reason") or "") in _TRUNCATED_FINISH_REASONS:
            ctx.metadata["final_answer_candidate"] = text
            ctx.metadata["delivery_candidate_status"] = "unfinished"
            return None

        # Repair before accepting/binding the body. Never strip receipts from an
        # already checked passage or discard useful evidence at budget exhaustion.
        last_turn = ctx.turn >= ctx.max_turns - 1
        readability_issue = corpus_citation_readability_issue(text)
        if readability_issue:
            ctx.metadata["corpus_citation_readability"] = "unresolved"
            if not self._readability_repair_offered and not last_turn:
                self._readability_repair_offered = True
                ctx.metadata["final_answer_candidate"] = text
                return Intervention(
                    continue_to_next_turn=True,
                    inject_messages=[readability_issue],
                )
        else:
            ctx.metadata.pop("corpus_citation_readability", None)

        scope = get_current_execution_scope()
        err = finalize_gate(
            ctx.task_id,
            text,
            bus_task_id=resolve_bus_task_id(scope) if scope is not None else None,
        )
        # On the very last turn tools are stripped (LastTurnForcer), so the only
        # way to emit anything is plain text; accept it rather than lose the
        # answer to a max_turns stop even if the gate would otherwise block.
        if err and not last_turn:
            if isinstance(ctx.metadata, dict):
                ctx.metadata["final_answer_candidate"] = text
            return Intervention(continue_to_next_turn=True, inject_messages=[err])

        if scope is not None:
            _write_accepted_record(scope, text)
        if isinstance(ctx.metadata, dict):
            ctx.metadata["final_answer"] = text
            ctx.metadata["final_answer_confidence"] = 1.0
        complete_delivery_tasks(ctx.task_id)
        logger.info(
            "BareTextFinalizeObserver latched: turn=%d, len=%d, gate=%s",
            ctx.turn,
            len(text),
            "bypassed(last_turn)" if err else "passed",
        )
        return Intervention(stop_reason="final_answer")
