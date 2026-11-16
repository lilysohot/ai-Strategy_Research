"""Measure what each outgoing request is made of, at the request boundary.

Why this exists
---------------
Compaction decisions were being argued from log sizes. A trajectory line's
``content`` length is not the size of the request the provider charged for:
the provider re-serialises, adds tool definitions, and the reasoning it replays
is billed as input tokens without appearing as a tool result. A per-turn split
of the *actual* message list is the smallest thing that makes those arguments
checkable, and it has to be taken where the list is final — after observer
injections and the per-call system addendum, immediately before the call.

What is recorded
----------------
Sizes, identities and hashes, never content. The composition is a description
of the request, not a copy of it: a hash lets two turns be compared for byte
equality without storing either, and the tool name attributes a result to the
tool that produced it. Full request capture, when it is needed, stays a
separate deliberate act on local storage.

The split is by *message role and origin*, not by tool name alone, because the
categories behave differently under compaction: tool results are what Tier 1
drops, assistant text is what a summary replaces, and injected user material is
neither. ``tool_call_args`` is separated out because a serialised call can be
larger than the result it produced, and it is not tool *output*.

Reasoning is its own category because it is the one thing nothing above touches:
it is billed as input on every replay, Tier 1 never sees it (it is not a tool
result), and the summary does not replace it (it is not visible text). Counting
it as assistant text — or not counting it at all — makes the largest growing
category invisible exactly when the total is being argued about.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from frontier_agent.core.messages import Message, text_of
from frontier_agent.core.runtime.loop.compact import _tool_names_by_call_id

__all__ = [
    "REQUEST_COMPOSITION_KEY",
    "request_composition",
]

#: Metadata key the loop publishes the composition under. Mirrors
#: ``INPUT_ESTIMATE_KEY``: an observer reading ``ctx.messages`` at turn end can
#: never reproduce the list that was sent, so the loop has to publish it.
REQUEST_COMPOSITION_KEY = "_request_composition"

#: Longest entries named individually. The aggregate is exact; this list only
#: exists to say WHICH messages dominate, so it is bounded rather than
#: proportional to history length.
_LARGEST_KEEP = 8

#: Digest length. Long enough to distinguish two blocks in one history, short
#: enough that a hundred of them stay readable in a trace line.
_HASH_CHARS = 12

#: ``tag`` thinking format inlines reasoning into ``content`` as
#: ``<think>…</think>``; :func:`assistant_msg_with_reasoning` escapes a nested
#: closing tag as ``</ think>`` so the first real closing tag is the boundary.
_THINK_OPEN = "<think>"
_THINK_CLOSE = "</think>"


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "replace")).hexdigest()[:_HASH_CHARS]


def _split_inline_reasoning(content: str) -> tuple[str, str]:
    """Separate an inlined ``<think>…</think>`` block from visible assistant text.

    Returns ``(reasoning, visible)``. Only content that *starts* with the opener
    is treated as inlined reasoning, which is the shape
    ``assistant_msg_with_reasoning`` emits for the ``tag`` format. A missing
    closing tag means the reply was truncated mid-reasoning; the remainder still
    counts as reasoning because that is what the provider was billed for.
    """
    if not content.startswith(_THINK_OPEN):
        return "", content
    close = content.find(_THINK_CLOSE, len(_THINK_OPEN))
    if close < 0:
        return content[len(_THINK_OPEN) :], ""
    reasoning = content[len(_THINK_OPEN) : close]
    visible = content[close + len(_THINK_CLOSE) :].lstrip("\n")
    return reasoning, visible


def _arguments_chars(call: Any) -> int:
    if not isinstance(call, dict):
        return len(str(call))
    function = call.get("function")
    if isinstance(function, dict):
        raw = function.get("arguments")
    else:
        raw = call.get("args", call.get("arguments"))
    if isinstance(raw, str):
        return len(raw)
    if raw is None:
        return 0
    return len(json.dumps(raw, ensure_ascii=False, separators=(",", ":")))


def request_composition(messages: list[Message]) -> dict[str, Any]:
    """Split one request into size categories, with identities and hashes.

    Returns a JSON-serialisable dict::

        {
          "messages": 19,
          "chars": {"system": 0, "user": 120, "assistant_text": 340,
                    "reasoning": 48_457, "tool_call_args": 210,
                    "tool_results": 63_512, "total": 112_639},
          "tool_results_by_name": {"corpus_fetch": 63_000},
          "largest": [{"role": "tool", "tool": "corpus_fetch",
                       "chars": 11_755, "reasoning": 0, "hash": "1f2c..."}],
          "sha256": "…"        # of the whole list, for byte-stability checks
        }

    ``chars`` counts the text the provider is asked to read. Serialisation
    overhead between messages is not included — it is provider-specific and
    would be an invented constant here.

    ``reasoning`` covers both shapes reasoning reaches a request in: the
    ``reasoning_content`` wire field, and the ``<think>…</think>`` block inlined
    into ``content`` by the ``tag`` format. The two are mutually exclusive per
    message in practice — :func:`assistant_msg_with_reasoning` picks one — and
    when a message somehow carries both, the inline block is left in
    ``assistant_text`` rather than counted twice, so the total can only be read
    too high, never too low.
    """
    names = _tool_names_by_call_id(messages)
    chars = {
        "system": 0,
        "user": 0,
        "assistant_text": 0,
        "reasoning": 0,
        "tool_call_args": 0,
        "tool_results": 0,
    }
    by_tool: dict[str, int] = {}
    blocks: list[dict[str, Any]] = []
    hasher = hashlib.sha256()

    for message in messages:
        role = str(message.get("role", "") or "")
        content = text_of(message.get("content"))
        reasoning_content = str(message.get("reasoning_content") or "")
        calls = message.get("tool_calls") or []
        call_chars = sum(_arguments_chars(call) for call in calls if isinstance(call, dict))
        tool_name = names.get(str(message.get("tool_call_id") or "")) if role == "tool" else None

        inline_reasoning = ""
        visible = content
        if role not in ("system", "user", "tool") and not reasoning_content:
            inline_reasoning, visible = _split_inline_reasoning(content)

        if role == "system":
            chars["system"] += len(content)
        elif role == "user":
            chars["user"] += len(content)
        elif role == "tool":
            chars["tool_results"] += len(content)
            if tool_name:
                by_tool[tool_name] = by_tool.get(tool_name, 0) + len(content)
        else:
            chars["assistant_text"] += len(visible)
        reasoning_chars = len(reasoning_content) + len(inline_reasoning)
        chars["reasoning"] += reasoning_chars
        chars["tool_call_args"] += call_chars

        # The digest covers everything that is billed, reasoning included: two
        # requests differing only in replayed reasoning are different requests,
        # and a cache check that called them equal would report phantom hits.
        calls_json = json.dumps(calls, ensure_ascii=False, sort_keys=True) if calls else ""
        hasher.update(role.encode("utf-8", "replace"))
        hasher.update(b"\x00")
        hasher.update(content.encode("utf-8", "replace"))
        hasher.update(b"\x00")
        hasher.update(reasoning_content.encode("utf-8", "replace"))
        hasher.update(b"\x00")
        if calls_json:
            hasher.update(calls_json.encode("utf-8", "replace"))

        blocks.append(
            {
                "role": role,
                "tool": tool_name,
                # Billed size of this message. Reasoning is included, or the
                # block that is largest in the request would sort as if it were
                # small — ``largest`` exists to name the dominant messages, and
                # a turn whose cost is all reasoning is exactly such a message.
                "chars": len(visible) + call_chars + reasoning_chars,
                "reasoning": reasoning_chars,
                "hash": _digest(f"{reasoning_content}\x00{content}\x00{calls_json}"),
            }
        )

    chars["total"] = sum(value for key, value in chars.items() if key != "total")
    blocks.sort(key=lambda block: block["chars"], reverse=True)
    return {
        "messages": len(messages),
        "chars": chars,
        "tool_results_by_name": dict(
            sorted(by_tool.items(), key=lambda item: item[1], reverse=True),
        ),
        "largest": blocks[:_LARGEST_KEEP],
        "sha256": hasher.hexdigest(),
    }
