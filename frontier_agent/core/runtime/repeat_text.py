"""Abbreviate a repeated notice only while its full form is still live.

The rule this module exists to enforce: *a short reference may replace a long
block only when the long block is still in the current effective context and its
content has not changed.* "We sent it earlier in this run" is not enough — compaction
rewrites the history in place, a sub-agent gets a fresh transcript, and the
finalization pass starts from zero. Abbreviating on the weaker condition is how a
model ends up reading "rules unchanged" with no rules anywhere above it.

Two callers, two ways of proving visibility:

* code that holds the message list (observers, via ``TurnContext.messages``) can ask
  :func:`full_still_visible` directly — an exact substring test;
* tools cannot see the list, so the loop mirrors its rewrite generation into their
  execution scope (:func:`publish_generation`) and they use :func:`may_abbreviate`,
  which treats every rewrite as "the full text may be gone; send it again".
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from typing import Any

from frontier_agent.core.runtime.loop.compact import COMPACTION_SEQ_KEY

__all__ = [
    "GENERATION_KEY",
    "REWRITE_SEQ_KEY",
    "context_generation",
    "full_still_visible",
    "mark_full_sent",
    "may_abbreviate",
    "note_context_rewrite",
    "publish_generation",
]

#: Per-scope record of ``key -> (digest, generation)`` for the last full send.
_SEEN_KEY = "_repeat_text_versions"

#: Loop-owned count of in-place history rewrites that are *not* compaction passes
#: — today, a reading checkpoint retiring consumed bodies. Compaction keeps its
#: own counter (``COMPACTION_SEQ_KEY``) because observers already coordinate on
#: it; :func:`context_generation` sums the two.
REWRITE_SEQ_KEY = "_context_rewrite_seq"

#: Where the loop mirrors the summed generation into the execution scope, so a
#: tool can reason about a context it cannot read.
GENERATION_KEY = "_context_generation"


def _digest(full: str) -> str:
    return hashlib.sha256(full.encode("utf-8")).hexdigest()[:12]


def _parse_int(value: Any) -> int | None:
    """An exact integer, or ``None`` when the value cannot be trusted.

    ``"invalid"``, ``""`` and ``True`` are *not* zero. Coercing a corrupt counter
    to the initial generation makes it compare equal to a real pre-rewrite one,
    which licenses exactly the abbreviation this module exists to refuse.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value) if value.is_integer() else None
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


def _generation(metadata: Mapping[str, Any] | None) -> int | None:
    """The verified generation, or ``None`` when it cannot be established.

    ``None`` is not a generation: a scope whose counter is unreadable has no
    evidence about rewrites, so nothing may be abbreviated in it.
    """
    if not isinstance(metadata, Mapping):
        return None
    if GENERATION_KEY in metadata:
        return _parse_int(metadata.get(GENERATION_KEY))
    total = 0
    for key in (COMPACTION_SEQ_KEY, REWRITE_SEQ_KEY):
        if key not in metadata:
            continue
        parsed = _parse_int(metadata.get(key))
        if parsed is None:
            return None
        total += parsed
    return total


def context_generation(metadata: Mapping[str, Any] | None) -> int:
    """How many in-place rewrites this context has had, for display and audit.

    An absent counter reads as ``0`` — the pre-rewrite value, so a scope the loop
    never mirrored may keep what it already marked. A counter that is present but
    unreadable also reports ``0`` *here*: this value is a number to print, never a
    licence. :func:`may_abbreviate` and :func:`mark_full_sent` refuse that scope.
    """
    generation = _generation(metadata)
    return 0 if generation is None else generation


def note_context_rewrite(metadata: dict[str, Any] | None) -> None:
    """Record one non-compaction rewrite of the live history.

    Call this wherever the loop replaces text the model already read in place —
    a reading checkpoint retiring bodies is the current case. It is deliberately
    separate from ``COMPACTION_SEQ_KEY``: that counter also drives observer
    re-arming, and re-shaping it here would change compaction behaviour.
    """
    if not isinstance(metadata, dict):
        return
    if REWRITE_SEQ_KEY not in metadata:
        metadata[REWRITE_SEQ_KEY] = 1
        return
    current = _parse_int(metadata.get(REWRITE_SEQ_KEY))
    # A counter that was already unreadable stays unreadable: inventing ``1``
    # here could collide with a generation this scope recorded earlier.
    metadata[REWRITE_SEQ_KEY] = None if current is None else current + 1


def publish_generation(
    metadata: Mapping[str, Any] | None,
    target: dict[str, Any] | None,
) -> None:
    """Mirror the loop's generation where tool callers can read it.

    ``target`` is the execution scope's metadata, not the loop's: the two are
    distinct dicts, and only the scope is reachable from a tool. An unreadable
    source is mirrored as ``None`` — "cannot confirm" travels as itself rather
    than as a generation that happens to equal the initial one.
    """
    if not isinstance(target, dict):
        return
    target[GENERATION_KEY] = _generation(metadata)


def full_still_visible(messages: Sequence[Any] | None, full: str) -> bool:
    """Whether *full* still appears verbatim in the live message list.

    Exact, not heuristic: a message that was compacted away, summarised, or replaced
    by a placeholder no longer contains the text, so the caller must resend it.
    """
    if not full:
        return False
    for message in messages or ():
        content = message.get("content") if isinstance(message, Mapping) else None
        if isinstance(content, str) and full in content:
            return True
    return False


def may_abbreviate(metadata: Mapping[str, Any] | None, *, key: str, full: str) -> bool:
    """Whether a short reference for *full* is safe in this context.

    True only when the identical text was marked sent under the same generation.
    Any bump, any change to *full*, or a scope that never marked it yields
    ``False`` — the conservative direction, because the failure mode of a wrong
    ``True`` is a model following rules it cannot read.
    """
    if not isinstance(metadata, Mapping):
        return False
    generation = _generation(metadata)
    if generation is None:
        return False
    seen = metadata.get(_SEEN_KEY)
    if not isinstance(seen, Mapping):
        return False
    entry = seen.get(key)
    if not isinstance(entry, tuple) or len(entry) != 2:
        return False
    digest, recorded = entry
    return digest == _digest(full) and recorded == generation


def mark_full_sent(metadata: dict[str, Any] | None, *, key: str, full: str) -> None:
    """Record that *full* went out under the current generation.

    Only call this for text the model actually receives in full: a result the
    loop truncates is not a full send, and marking it would license an
    abbreviation for a block nobody could read. A scope whose generation cannot
    be established is left unmarked, so it cannot abbreviate either.
    """
    if not isinstance(metadata, dict):
        return
    generation = _generation(metadata)
    if generation is None:
        return
    seen = metadata.get(_SEEN_KEY)
    if not isinstance(seen, dict):
        seen = {}
        metadata[_SEEN_KEY] = seen
    seen[key] = (_digest(full), generation)
