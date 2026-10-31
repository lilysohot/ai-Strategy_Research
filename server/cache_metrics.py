"""Read-only attempt cache diagnostics; unknown usage is never a cache miss."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from server.trajectory_sources import discover_trajectory_sources, iter_merged_records


def _counter(usage: dict[str, Any], *names: str) -> int | None:
    for name in names:
        value = usage.get(name)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


def _bucket(attempts: list[dict[str, Any]]) -> dict[str, Any]:
    prompt = cached = known = duration = unknown_duration = 0
    outcomes: dict[str, int] = {}
    for attempt in attempts:
        usage = attempt.get("usage") or {}
        if not isinstance(usage, dict):
            usage = {}
        p = _counter(usage, "prompt_tokens", "input_tokens")
        c = _counter(usage, "cache_read_tokens", "cached_tokens")
        if p is not None and c is not None and c <= p:
            known += 1
            prompt += p
            cached += c
        elapsed = _counter(attempt, "duration_ms")
        if elapsed is None:
            unknown_duration += 1
        else:
            duration += elapsed
        outcome = str(attempt.get("outcome") or "unfinished")
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    unknown = len(attempts) - known
    rate = cached / prompt if prompt else None
    return {
        "attempts": len(attempts),
        "known_usage_attempts": known,
        "unknown_usage_attempts": unknown,
        "duration_ms": duration,
        "unknown_duration_attempts": unknown_duration,
        "known_prompt_tokens": prompt,
        "known_cache_read_tokens": cached,
        "known_hit_rate": rate,
        "hit_rate": None if unknown else rate,
        "outcomes": outcomes,
    }


def cache_attempt_stats(records: list[dict[str, Any]]) -> dict[str, Any]:
    """Separate first attempts, retries and coordinator entry requests.

    Accepted ``llm`` rows duplicate attempt usage and are deliberately excluded.
    First attempts are per logical call; coordinator_entry is the first request
    of the main loop, the relevant comparison across human conversation rounds.
    Legacy traces without attempt identities cannot establish either split.
    """
    attempts: dict[tuple[str, str], dict[str, Any]] = {}
    for index, record in enumerate(records):
        if record.get("t") != "attempt":
            continue
        if record.get("phase") not in {"started", "finished"}:
            continue
        source = str(record.get("trajectory_source") or "unknown")
        key = (source, str(record.get("attempt_id") or f"record-{index}"))
        # The finished event wins if records are supplied out of timestamp order.
        if key not in attempts or record.get("phase") == "finished":
            attempts[key] = record
    values = list(attempts.values())
    first = [r for r in values if r.get("attempt_index") == 1]
    retries = [
        r for r in values if isinstance(r.get("attempt_index"), int) and r["attempt_index"] > 1
    ]
    entry = [
        r
        for r in first
        if r.get("turn") == 1 and r.get("trajectory_source") in {"main_agent", "react_agent"}
    ]
    all_attempts = _bucket(values)
    return {
        "version": 1,
        "status": (
            "unavailable"
            if not values
            else "partial"
            if all_attempts["unknown_usage_attempts"]
            else "complete"
        ),
        "first_attempts": _bucket(first),
        "retries": _bucket(retries),
        "coordinator_entry": _bucket(entry),
        "all_attempts": all_attempts,
    }


def cache_stats_for_directory(run_dir: Path) -> dict[str, Any]:
    """Read the same team/single trajectory inventory used by Web replay."""
    records = [record for record, _, _ in iter_merged_records(discover_trajectory_sources(run_dir))]
    return cache_attempt_stats(records)
