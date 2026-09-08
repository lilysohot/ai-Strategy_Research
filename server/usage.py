"""Token-usage aggregation from the runtime trajectory (T2.11).

The platform does **not** write its own UsageObserver. The runtime already
records one ``{"t": "llm", ...}`` line per LLM turn into
``<run_dir>/run/agent/trajectories/react_agent.jsonl``, each carrying the
normalised ``usage`` dict produced by
``frontier_agent.core.runtime.loop._response.extract_usage``::

    {"provider": ..., "model": ..., "prompt_tokens": N, "completion_tokens": N,
     "total_tokens": N, "cache_read_tokens": N, "cache_write_tokens": N,
     "cached_tokens": N, "cache_creation_tokens": N, "reasoning_tokens": N}

So metering is a pure sum over those lines, done once when the run reaches its
terminal state. Reading the trajectory rather than observing the loop keeps the
platform off the kernel's hot path and makes a re-scan (after a crash, or on a
historical run) produce the same numbers as the live run — the file is the
source of truth, and this module never mutates it.

Why the cache split matters: ``cache_read_tokens`` (cache hit) bills at ~0.1x
base input on Anthropic and is free on OpenAI, while ``cache_write_tokens``
(cache creation) bills at 1.25x-2x. Summing them into one "cached" bucket is
what makes a cost board under-attribute write spend, so we keep them apart.
"""

from __future__ import annotations

from typing import Any

from server.relay import trajectory_records

#: Summed integer fields, in the shape they are persisted on the Run row.
_TOKEN_FIELDS = (
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "reasoning_tokens",
)


def _first_int(usage: dict[str, Any], *keys: str) -> int:
    """First non-null int among ``keys`` (new cache names before legacy aliases)."""
    for key in keys:
        value = usage.get(key)
        if value is None:
            continue
        try:
            return int(value)
        except (TypeError, ValueError):
            continue
    return 0


def aggregate_usage(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Sum per-turn usage across trajectory records.

    Only ``t == "llm"`` records carry usage; every other record type (start /
    result / compaction) is ignored. A turn with no usage (a provider that omits
    it, or a streamed response whose usage arrived empty) contributes nothing but
    is still counted as a call only when it did report usage — we must not
    inflate ``llm_calls`` with unmetered turns.

    ``total_tokens`` is summed when present; when a provider omits it we fall
    back to ``prompt + completion`` for that turn so the total never reads lower
    than its parts.
    """
    totals: dict[str, int] = {name: 0 for name in _TOKEN_FIELDS}
    models: list[str] = []
    providers: list[str] = []
    llm_calls = 0

    for rec in records or []:
        if not isinstance(rec, dict) or rec.get("t") != "llm":
            continue
        usage = rec.get("usage")
        if not isinstance(usage, dict) or not usage:
            continue
        llm_calls += 1

        prompt = _first_int(usage, "prompt_tokens", "input_tokens")
        completion = _first_int(usage, "completion_tokens", "output_tokens")
        reported_total = usage.get("total_tokens")
        try:
            total = int(reported_total) if reported_total is not None else 0
        except (TypeError, ValueError):
            total = 0
        if total <= 0:
            # Some gateways omit total or report 0 mid-stream; derive it so the
            # run's total is never below prompt + completion.
            total = prompt + completion

        cache_read = _first_int(usage, "cache_read_tokens", "cached_tokens")
        cache_write = _first_int(
            usage,
            "cache_write_tokens",
            "cache_creation_tokens",
        )
        reasoning = _first_int(usage, "reasoning_tokens")

        totals["prompt_tokens"] += prompt
        totals["completion_tokens"] += completion
        totals["total_tokens"] += total
        totals["cache_read_tokens"] += cache_read
        totals["cache_write_tokens"] += cache_write
        totals["reasoning_tokens"] += reasoning

        model = str(usage.get("model") or "").strip()
        if model and model not in models:
            models.append(model)
        provider = str(usage.get("provider") or "").strip()
        if provider and provider not in providers:
            providers.append(provider)

    return {**totals, "llm_calls": llm_calls, "models": models, "providers": providers}


def usage_for_run(run_id: str) -> dict[str, Any]:
    """Aggregate a run's token usage from its trajectory file.

    Best-effort by design: a missing or corrupt trajectory yields a zeroed
    aggregate rather than raising — metering must never break the run lifecycle.
    """
    try:
        records = trajectory_records(run_id)
    except OSError:
        return aggregate_usage([])
    return aggregate_usage(records)
