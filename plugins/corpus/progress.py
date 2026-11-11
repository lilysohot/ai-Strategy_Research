"""Job-local acquisition progress, independent of queries and semantic completion.

Observe final tool messages, after output budgeting. Exhausting a no-progress
budget is an incomplete execution, never a verdict that the answer is supported.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from frontier_agent.core.loop_types import (
    BaseObserver,
    Intervention,
    ToolCallIntervention,
    ToolResult,
    TurnContext,
)
from plugins.corpus.search_evidence import search_evidence_items

if TYPE_CHECKING:
    from frontier_agent.core.loop_types import AgentLoopResult

ACQUISITION_TOOLS = frozenset({"corpus_search", "corpus_fetch", "corpus_inventory"})
STOP_REASON = "repeated_corpus_results"


def _digest(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def _observations(name: str, payload: dict[str, Any]) -> set[str]:
    """Content identities exclude query text, ranking and receipt/cursor aliases."""
    found: set[str] = set()

    def record(kind: str, doc_id: str, value: Any) -> None:
        found.add(_digest([kind, doc_id, value]))

    def evidence(doc_id: str, item: dict[str, Any]) -> None:
        if isinstance(item.get("text"), str) and item.get("locator"):
            fragment = item.get("fragment") or {"start": 0, "end": len(item["text"])}
            record("text", doc_id, [item["locator"], fragment, item["text"]])

    if name == "corpus_search":
        hits = payload.get("hits", [])
        if not isinstance(hits, list):
            return set()
        for hit in hits:
            if not isinstance(hit, dict) or not isinstance(hit.get("doc_id"), str):
                continue
            doc_id = hit["doc_id"]
            record(
                "candidate",
                doc_id,
                [
                    hit.get("title"),
                    hit.get("published"),
                    hit.get("available_blocks"),
                    hit.get("preview"),
                ],
            )
            for item in search_evidence_items(hit):
                evidence(doc_id, item)
    elif name == "corpus_fetch":
        doc_id = payload.get("doc_id", "")
        items = payload.get("items", [payload])
        if not isinstance(items, list):
            return set()
        for item in items:
            if isinstance(item, dict) and not item.get("error"):
                evidence(item.get("doc_id") or doc_id, item)
        # Blank units and the first true end-of-document receipt are progress too.
        # Neither declares task completion or coverage of the original PDF.
        if payload.get("scope") == "document":
            record(
                "document_position",
                doc_id,
                [
                    payload.get("document_sha256"),
                    payload.get("position"),
                    payload.get("fetch_complete"),
                ],
            )
    elif name == "corpus_inventory":
        items = payload.get("items", [])
        if not isinstance(items, list):
            return set()
        for item in items:
            if isinstance(item, dict) and item.get("locator"):
                record("inventory", payload.get("doc_id", ""), item)
    return found


class CorpusCoverageObserver(BaseObserver):
    """Absolute source-unit positions a job actually received, from page receipts.

    Positions derive mechanically from document-page receipts (filtered end
    index minus delivered item count, shifted by the dispatched range) — never
    from a model's own coverage claim. Locator and fragment reads carry no
    position and stay unrecorded; absence of telemetry is fail-open for
    completion accounting, contradicting telemetry is fail-closed.
    """

    def __init__(self) -> None:
        self.pending: dict[str, str] = {}
        self.positions: set[int] = set()

    async def on_tool_result(self, ctx: TurnContext, result: ToolResult) -> None:
        del ctx
        if result.name == "corpus_fetch":
            self.pending[result.tool_call_id] = result.name

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        for message in ctx.messages or []:
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            if self.pending.pop(str(message.get("tool_call_id", "")), None) is None:
                continue
            try:
                payload = json.loads(message.get("content") or "")
            except (ValueError, TypeError):
                continue
            if not isinstance(payload, dict) or payload.get("ok") is not True:
                continue
            if payload.get("scope") != "document":
                continue
            items = payload.get("items")
            position = payload.get("position") or {}
            end = position.get("unit_index")
            if not isinstance(items, list) or type(end) is not int or end < len(items):
                continue
            span = payload.get("unit_range")
            base = (
                int(span[0])
                if (isinstance(span, list) and len(span) == 2 and type(span[0]) is int)
                else 0
            )
            # Filtered index i is absolute 1-based position base+i; this page
            # delivered filtered indices [end-len(items), end).
            self.positions.update(range(base + end - len(items), base + end))
        return None

    async def on_loop_end(self, result: AgentLoopResult) -> None:
        metadata = getattr(result, "metadata", None)
        if isinstance(metadata, dict):
            metadata["observed_unit_coverage"] = sorted(self.positions)


@dataclass
class CorpusReadState:
    """Revocations shared by one run; never a process-wide admission cache."""

    withdrawn: dict[str, dict[str, Any]] = field(default_factory=dict)

    def observe(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            return
        doc_id = payload.get("doc_id")
        if (
            payload.get("ok") is False
            and payload.get("code") == "withdrawn"
            and payload.get("retryable") is False
            and payload.get("failure_scope") == "document"
            and isinstance(doc_id, str)
            and doc_id
        ):
            self.withdrawn[doc_id] = {
                "ok": False,
                "code": "withdrawn",
                "retryable": False,
                "failure_scope": "document",
                "doc_id": doc_id,
                "fetch_complete": False,
                "error": "source_withdrawn",
            }


class CorpusProgressObserver(BaseObserver):
    """Bound repeated returned content, while keeping new ranges/versions usable.

    Stop-loss is opt-in for recoverable member loops. Coordinators only expose
    progress and suppress known revoked reads; their delivery gate stays in charge.
    Delivered-content progress is job-local. Only typed revocations are shared
    when the caller supplies a run-owned read state.
    """

    critical = True

    def __init__(self, *, stop_after: int = 0, read_state: CorpusReadState | None = None) -> None:
        self.stop_after = max(4, stop_after) if stop_after else 0
        self.seen: set[str] = set()
        self.read_state = read_state if read_state is not None else CorpusReadState()
        self.withdrawn = self.read_state.withdrawn
        self.pending: dict[str, str] = {}
        self.streak = 0
        self.repeated_calls = 0
        self.new_observations = 0
        self.notice: dict[str, Any] | None = None

    async def on_tool_call(
        self,
        ctx: TurnContext,
        tool_call: dict[str, Any],
    ) -> ToolCallIntervention | None:
        del ctx
        args = tool_call.get("args") or {}
        if tool_call.get("name") not in {"corpus_fetch", "corpus_inventory"}:
            return None
        doc_id = args.get("doc_id") if isinstance(args, dict) else None
        if isinstance(doc_id, str) and doc_id in self.withdrawn:
            return ToolCallIntervention(
                skip_with_result=json.dumps(
                    {
                        **self.withdrawn[doc_id],
                        "execution_suppressed": True,
                    },
                    ensure_ascii=False,
                ),
                skip_is_error=True,
            )
        return None

    async def on_tool_result(self, ctx: TurnContext, result: ToolResult) -> None:
        del ctx
        if result.name in ACQUISITION_TOOLS:
            self.pending[result.tool_call_id] = result.name
            # Admission failures are runtime state even if the model's output
            # budget omits the body. This does not count omitted evidence as read.
            with suppress(ValueError, TypeError):
                self.read_state.observe(json.loads(result.result))

    async def on_before_llm(self, ctx: TurnContext) -> Intervention | None:
        del ctx
        if self.notice is None:
            return None
        notice, self.notice = self.notice, None
        # A runtime state receipt, not a topic-specific instruction or an answer.
        return Intervention(inject_messages=[json.dumps({"corpus_progress": notice})])

    async def on_turn_end(self, ctx: TurnContext) -> Intervention | None:
        observed = False
        new = 0
        unknown = False
        for message in ctx.messages or []:
            if not isinstance(message, dict) or message.get("role") != "tool":
                continue
            name = self.pending.pop(str(message.get("tool_call_id", "")), None)
            if name is None:
                continue
            try:
                payload = json.loads(message.get("content") or "")
            except (ValueError, TypeError):
                unknown = True
                continue
            if not isinstance(payload, dict):
                unknown = True
                continue
            doc_id = payload.get("doc_id")
            if (
                payload.get("ok") is False
                and payload.get("code") == "withdrawn"
                and payload.get("retryable") is False
                and payload.get("failure_scope") == "document"
                and isinstance(doc_id, str)
            ):
                self.read_state.observe(payload)
                observed = True
                continue
            if payload.get("ok") is not True:
                unknown = True
                continue
            identities = _observations(name, payload)
            if not identities:
                # Empty searches, malformed/omitted bodies and transient errors
                # provide no basis for asserting repeated delivered evidence.
                unknown = True
                continue
            observed = True
            added = identities - self.seen
            new += len(added)
            if not added:
                self.repeated_calls += 1
            self.seen.update(identities)
        unknown = unknown or bool(self.pending)
        self.pending.clear()
        self.new_observations += new
        only_acquisition = bool(ctx.tool_calls) and all(
            c.get("name") in ACQUISITION_TOOLS for c in ctx.tool_calls
        )
        self.streak = (
            self.streak + 1 if (observed and not new and not unknown and only_acquisition) else 0
        )
        state = {
            "new_observations": new,
            "observations_total": self.new_observations,
            "repeated_calls": self.repeated_calls,
            "consecutive_no_progress_turns": self.streak,
            "withdrawn_documents": sorted(self.withdrawn),
            "task_sufficiency": "not_assessed",
        }
        ctx.metadata["corpus_progress"] = state
        if self.streak == 3:
            self.notice = dict(state)
        if self.stop_after and self.streak >= self.stop_after:
            return Intervention(stop_reason=STOP_REASON)
        return None
