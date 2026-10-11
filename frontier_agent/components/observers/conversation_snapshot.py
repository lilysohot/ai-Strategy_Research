"""Cross-turn conversation snapshot: one run's replayable message list.

Why a dump and not the trajectory
---------------------------------
Multi-turn continuity only earns a KV-cache hit when the *previous* request's
prefix reappears byte-identically in the next request. ``AgentLoopResult.messages``
is that prefix in exactly the shape the kernel handed the wire — reasoning already
inlined or preserved per ``thinking_format``, tool results already post-processed —
so this observer persists it verbatim. It deliberately does **not** re-derive the
list from the trajectory event stream: the JSON envelope clips tool bodies to
``_BODY_MAX_CHARS`` and its records are written *before* the tool-result
post-processor runs, so any reconstruction matches only up to the first clipped
body.

Ownership
---------
The dump is a run-scoped artifact. The server layer only *transports* it (a byte
copy into the next run's directory) and never parses it; the next run's workflow
validates the header (``select_replay``) and either replays it as
``initial_messages`` or ignores it. See
``.scratch/web-business-context/issues/01-context-inheritance.md`` §9.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import os
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from frontier_agent.components.observers.trajectory import serialize_tool_schemas
from frontier_agent.core.loop_types import AgentLoopResult, BaseObserver
from frontier_agent.core.messages import (
    WIRE_MESSAGE_KEYS,
    Message,
    for_wire,
    system_msg,
)
from frontier_agent.core.runtime.loop.context_budget import estimate_tokens

logger = logging.getLogger(__name__)

#: Payload contract version. Bump when the header or the message encoding changes
#: so an older dump is rejected instead of misread.
SCHEMA = "conversation-dump/1"

_ROLES = frozenset({"system", "user", "assistant", "tool"})


def canonical_json(value: Any) -> str:
    """Byte-comparable JSON: insertion order kept, no incidental whitespace."""
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def tool_schema_sha256(tools: Any) -> str:
    """Fingerprint a tool set (names, order, descriptions, schemas).

    Tools are part of the request prefix, so any change to them invalidates the
    cache just as a system-prompt edit does. Both the dump and its reader hash the
    same serialised list with this one function.
    """
    payload = canonical_json(serialize_tool_schemas(tools)).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _wire_copy(messages: Iterable[Message]) -> list[Message]:
    """Shallow-copy each message so a dump never aliases the live loop list."""
    return cast("list[Message]", [dict(message) for message in messages])


def validate_messages(messages: Any) -> str | None:
    """Return a rejection reason, or ``None`` when the list is replay-safe.

    Replay-safe means: every entry is a role-bearing wire message, the first one
    is the system prompt, and assistant ``tool_calls`` pair one-to-one with later
    ``tool`` results. An unanswered call would make the *next* request invalid
    (providers reject an orphaned ``tool_call_id``), and a stray non-wire key
    would change the request bytes — both are reasons to refuse the dump rather
    than replay it.
    """
    if not isinstance(messages, list) or not messages:
        return "empty"
    for idx, message in enumerate(messages):
        if not isinstance(message, dict) or not message.get("role"):
            return f"message[{idx}] is not a role-bearing dict"
        role = message["role"]
        if role not in _ROLES:
            return f"message[{idx}] has unknown role {role!r}"
        extra = sorted(set(message) - WIRE_MESSAGE_KEYS)
        if extra:
            return f"message[{idx}] carries non-wire keys {extra}"
    if messages[0]["role"] != "system":
        return "first message is not the system prompt"

    pending: dict[str, int] = {}
    for idx, message in enumerate(messages):
        if message["role"] == "assistant":
            for call in message.get("tool_calls") or []:
                call_id = (call or {}).get("id")
                if not call_id:
                    return f"assistant tool_call in message[{idx}] has no id"
                if call_id in pending:
                    return f"duplicate tool_call id {call_id!r}"
                pending[call_id] = idx
        elif message["role"] == "tool":
            call_id = message.get("tool_call_id") or ""
            if not call_id:
                return f"tool message[{idx}] has no tool_call_id"
            if call_id not in pending:
                return f"tool message[{idx}] answers unknown or repeated call {call_id!r}"
            del pending[call_id]
    if pending:
        return f"assistant tool_call {next(iter(pending))!r} has no tool result"
    return None


def _keep_from(messages: list[Message], cut: int) -> list[Message]:
    """The kept head: the system prompt plus everything from *cut* on."""
    return [messages[0], *messages[cut:]] if messages else []


def trim_to_turns(
    messages: list[Message], max_turns: int, *, max_tokens: int = 0
) -> tuple[list[Message], dict[str, Any] | None]:
    """Drop the oldest whole turns until both bounds are satisfied.

    Cutting on a ``user`` boundary (never mid-turn) keeps tool pairing intact, and
    index 0 — the system prompt — is never dropped. ``<= 0`` disables a bound,
    mirroring the repo's "0 disables the bound" convention.

    Two bounds, because a turn count is not a size. A run may legally end just
    under the provider's input-token ceiling — the web profile's tiered compaction
    triggers at 80% of the context window — and *replaying* that dump plus a new
    turn is what would push the next run's first request over the ceiling, where
    no in-run compaction can help. The token bound is therefore the guard that
    keeps a replay from becoming an un-runnable request.

    Trimming happens when the dump is *written*, not when it is read: the dump is
    the next run's baseline, so the prefix stays byte-stable until the next cut. A
    read-time sliding window would shift every turn and lose the whole cache.
    """
    if max_turns <= 0 and max_tokens <= 0:
        return messages, None
    starts = [idx for idx, message in enumerate(messages) if message.get("role") == "user"]
    cut = 1
    cut_for_turns = False
    if max_turns > 0 and len(starts) > max_turns:
        cut = starts[len(starts) - max_turns]
        cut_for_turns = True
    dropped_for_tokens = 0
    if max_tokens > 0:
        while True:
            if estimate_tokens(canonical_json(_keep_from(messages, cut))) <= max_tokens:
                break
            following = next((idx for idx in starts if idx > cut), None)
            if following is None:
                break
            cut = following
            dropped_for_tokens += 1
    if cut == 1 and dropped_for_tokens == 0:
        return messages, None

    kept = _keep_from(messages, cut)
    kept_turns = sum(1 for message in kept if message.get("role") == "user")
    reasons = []
    if cut_for_turns:
        reasons.append(f"max_replay_turns={max_turns}")
    if dropped_for_tokens:
        reasons.append(f"replay_max_tokens={max_tokens}")
    trim: dict[str, Any] = {
        "dropped_turns": len(starts) - kept_turns,
        "kept_turns": kept_turns,
        "cut_at": cut,
        "reason": "over " + " and ".join(reasons),
    }
    if max_tokens > 0:
        trim["token_budget"] = max_tokens
        trim["est_tokens"] = estimate_tokens(canonical_json(kept))
        trim["dropped_for_tokens"] = dropped_for_tokens
    return kept, trim


def build_dump(
    *,
    messages: list[Message],
    system_prompt: str,
    tool_names: list[str],
    tools_hash: str,
    thinking_format: str,
    pipeline_id: str = "",
    node_id: str = "",
    role_id: str = "",
    run_id: str = "",
    session_id: str = "",
    model_name: str = "",
    turns_used: int = 0,
    stopped_by: str = "",
    max_replay_turns: int = 0,
    max_replay_tokens: int = 0,
) -> dict[str, Any]:
    """Render the dump document (header + trimmed message list).

    ``messages_est_tokens`` is informational only — the writer measures the kept
    window once, and the reader copies it into the replay decision so the run's
    ``usage_json`` can report how big the replayed context was without
    re-tokenising it. It is additive to ``SCHEMA``: readers ignore keys they do
    not know, and no replay decision depends on it.
    """
    wire = for_wire(_wire_copy(messages))
    trimmed, trim = trim_to_turns(wire, max_replay_turns, max_tokens=max_replay_tokens)
    return {
        "schema": SCHEMA,
        "run_id": run_id,
        "session_id": session_id,
        "pipeline_id": pipeline_id,
        "node_id": node_id,
        "role_id": role_id,
        "model_name": model_name,
        "thinking_format": thinking_format,
        "system_prompt": system_prompt,
        "tool_names": list(tool_names),
        "tool_schema_sha256": tools_hash,
        "messages": trimmed,
        "messages_est_tokens": estimate_tokens(canonical_json(trimmed)),
        "turns_used": turns_used,
        "stopped_by": stopped_by,
        "trim": trim,
    }


def select_replay(
    payload: str,
    *,
    system_prompt: str,
    tool_names: list[str],
    tools_hash: str,
    thinking_format: str,
    pipeline_id: str = "",
    node_id: str = "",
    session_id: str = "",
) -> tuple[list[Message] | None, dict[str, Any]]:
    """Validate a transported dump; return ``(messages, decision)``.

    Fail-open by construction: anything the reader cannot vouch for — unknown
    schema, a different pipeline, a changed system prompt or tool set, malformed
    message pairing — yields ``(None, decision)`` so the caller starts a fresh
    conversation instead of replaying a prefix it cannot prove. Each rejection
    carries a machine-readable reason for the run summary.

    ``system_prompt`` is compared as text, and the replayed system message is
    compared *serialised*: the kernel does not re-add a system message when
    ``initial_messages`` is supplied, so those bytes are the request's first bytes
    and must match exactly.
    """
    decision: dict[str, Any] = {"decision": "skipped", "reason": ""}
    if not payload or not payload.strip():
        decision["reason"] = "no_payload"
        return None, decision
    try:
        doc = json.loads(payload)
    except (TypeError, ValueError) as exc:
        decision["reason"] = f"unparsable payload: {type(exc).__name__}"
        return None, decision
    if not isinstance(doc, dict):
        decision["reason"] = "payload is not an object"
        return None, decision
    if doc.get("schema") != SCHEMA:
        decision["reason"] = f"schema mismatch: {doc.get('schema')!r}"
        return None, decision
    for field, expected in (("pipeline_id", pipeline_id), ("node_id", node_id)):
        if expected and str(doc.get(field) or "") != expected:
            decision["reason"] = f"{field} mismatch"
            return None, decision
    if session_id and str(doc.get("session_id") or "") != session_id:
        # Defence in depth: the server already scopes its lookup to this session,
        # but the dump carries its own id — check it rather than trust the caller.
        decision["reason"] = "session_id mismatch"
        return None, decision
    if str(doc.get("thinking_format") or "") != thinking_format:
        decision["reason"] = "thinking_format mismatch"
        return None, decision
    if str(doc.get("tool_schema_sha256") or "") != tools_hash:
        decision["reason"] = "tool schema mismatch"
        return None, decision
    if list(doc.get("tool_names") or []) != list(tool_names):
        decision["reason"] = "tool list mismatch"
        return None, decision
    if str(doc.get("system_prompt") or "") != system_prompt:
        decision["reason"] = "system prompt mismatch"
        return None, decision

    messages = doc.get("messages")
    if not isinstance(messages, list):
        decision["reason"] = "messages is not a list"
        return None, decision
    invalid = validate_messages(messages)
    if invalid:
        decision["reason"] = f"invalid messages: {invalid}"
        return None, decision
    if len(messages) < 2:
        decision["reason"] = "no prior turn to replay"
        return None, decision
    if canonical_json(messages[0]) != canonical_json(system_msg(system_prompt)):
        decision["reason"] = "system message bytes differ"
        return None, decision

    decision.update(
        {
            "decision": "used",
            "messages": len(messages),
            "prior_turns": sum(1 for m in messages if m.get("role") == "user"),
            # Window size, reported next to the field's own counters so a reader
            # can tell "replayed a 9k-token window" from "started fresh" (S1-a).
            # ``est_tokens`` is 0 for dumps written before the writer recorded it.
            "est_tokens": int(doc.get("messages_est_tokens") or 0),
            "payload_bytes": len(payload.encode("utf-8")),
            "trim": doc.get("trim"),
            "stopped_by": str(doc.get("stopped_by") or ""),
        }
    )
    return cast("list[Message]", [dict(message) for message in messages]), decision


class ConversationSnapshotObserver(BaseObserver):
    """Persist the loop's final message list so the next turn can replay it.

    Non-critical: a failed write (disk full, permissions) must never disturb the
    run — the worst case is that the next turn starts fresh, which is the same
    behaviour as having no continuity at all.
    """

    critical: bool = False

    def __init__(
        self,
        output_path: Path | str,
        *,
        system_prompt: str = "",
        tools: Any = None,
        tool_names: list[str] | None = None,
        thinking_format: str = "",
        pipeline_id: str = "",
        node_id: str = "",
        role_id: str = "",
        run_id: str = "",
        session_id: str = "",
        model_name: str = "",
        max_replay_turns: int = 0,
        max_replay_tokens: int = 0,
    ) -> None:
        """Args:
        output_path: Where the dump is written (atomic replace).
        system_prompt: The exact system prompt this loop was given — the
            reader compares it text-for-text before replaying.
        tools: The tool list bound to this loop, fingerprinted into
            ``tool_schema_sha256``.
        tool_names: Names in bound order. Passed in rather than derived, so
            the dump records exactly the list the workflow computed.
        thinking_format: Format the history normaliser used (``tag`` /
            ``reasoning_content`` / ``none``); a profile change between runs
            makes the replayed assistant shape wrong even if it is stable.
        max_replay_turns: Keep at most this many user turns (``0`` = no cap).
        max_replay_tokens: Keep the message list under this estimated token
            budget by dropping older turns (``0`` = no cap). Guards the next
            run's *first* request: a dump written just under the provider's
            ceiling would otherwise replay past it, where nothing in the run
            can compact it back.
        """
        self._path = Path(output_path)
        self._system_prompt = system_prompt
        self._tool_names = list(tool_names or [])
        self._tools_hash = tool_schema_sha256(tools or [])
        self._thinking_format = thinking_format
        self._pipeline_id = pipeline_id
        self._node_id = node_id
        self._role_id = role_id
        self._run_id = run_id
        self._session_id = session_id
        self._model_name = model_name
        self._max_replay_turns = max_replay_turns
        self._max_replay_tokens = max_replay_tokens

    async def on_loop_end(self, result: AgentLoopResult) -> None:
        try:
            self._write(result)
        except Exception:
            logger.warning(
                "conversation snapshot write failed: %s",
                self._path,
                exc_info=True,
            )

    def _write(self, result: AgentLoopResult) -> None:
        messages = list(getattr(result, "messages", None) or [])
        if not messages:
            logger.warning("conversation snapshot skipped: loop returned no messages")
            return
        wire = for_wire(_wire_copy(messages))
        invalid = validate_messages(wire)
        if invalid:
            # Fail closed: no dump means the next turn starts fresh, which is
            # always correct — replaying a half-answered turn would 400 upstream.
            logger.warning("conversation snapshot skipped: %s", invalid)
            return
        document = build_dump(
            messages=wire,
            system_prompt=self._system_prompt,
            tool_names=self._tool_names,
            tools_hash=self._tools_hash,
            thinking_format=self._thinking_format,
            pipeline_id=self._pipeline_id,
            node_id=self._node_id,
            role_id=self._role_id,
            run_id=self._run_id,
            session_id=self._session_id,
            model_name=self._model_name,
            turns_used=int(getattr(result, "turns_used", 0) or 0),
            stopped_by=str(getattr(result, "stopped_by", "") or ""),
            max_replay_turns=self._max_replay_turns,
            max_replay_tokens=self._max_replay_tokens,
        )
        self._atomic_write(document)

    def _atomic_write(self, document: dict[str, Any]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(self._path.suffix + ".tmp")
        payload = json.dumps(document, ensure_ascii=False, separators=(",", ":"))
        with open(tmp, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            # Best effort: a platform without fsync still writes the file.
            with contextlib.suppress(OSError):
                os.fsync(handle.fileno())
        os.replace(tmp, self._path)


__all__ = [
    "SCHEMA",
    "ConversationSnapshotObserver",
    "build_dump",
    "canonical_json",
    "select_replay",
    "tool_schema_sha256",
    "trim_to_turns",
    "validate_messages",
]
