"""Measurements from existing trajectory events; absent telemetry remains unknown."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


def percentile(values: list[float], quantile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * quantile
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return round(ordered[low] + (ordered[high] - ordered[low]) * (position - low), 3)


# Attempt outcomes whose llm row actually executed. A discarded or failed
# attempt never delivered its tool calls, so its phantom calls must not book
# redundancy; the retry after it is recovery resampling, not waste.
ACCEPTED_ATTEMPT_OUTCOMES = {"accepted", "accepted_degraded"}


def measure(root: Path) -> dict[str, Any]:
    """Accept either a Web run or an isolated evaluator trial directory."""
    candidates = [root / "run/agent/trajectories", root / "agent/trajectories"]
    trajectory = next((p for p in candidates if p.is_dir()), None)
    if trajectory is None:
        return {"available": False, "reason": "trajectory directory missing"}
    agents = []
    attempts = []
    tools: Counter[str] = Counter()
    tool_attempts: Counter[str] = Counter()
    tool_latencies: dict[str, list[float]] = defaultdict(list)
    tool_missing_duration: Counter[str] = Counter()
    tool_errors: Counter[str] = Counter()
    queries: Counter[str] = Counter()
    dispatches: dict[str, list[float]] = defaultdict(list)
    starts: dict[str, list[float]] = defaultdict(list)
    report_times = []
    research_jobs = 0
    malformed_events = 0
    for path in sorted(trajectory.rglob("*.jsonl")):
        rows = []
        for line in path.read_text().splitlines():
            if not line.strip():
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                malformed_events += 1
        if not rows:
            continue
        first, last = rows[0]["ts"], rows[-1]["ts"]
        # Attempt outcomes are logged before the llm row they govern; an llm
        # row before any finished attempt has no outcome evidence and stays
        # counted (conservative for redundancy detection).
        attempt_outcomes: list[str | None] = []
        current_outcome: str | None = None
        for row in rows:
            if row["t"] == "attempt" and row.get("phase") == "finished":
                current_outcome = row.get("outcome")
            attempt_outcomes.append(current_outcome)
        agent_attempts = [r for r in rows if r["t"] == "attempt" and r.get("phase") == "finished"]
        agent_prompts = [
            r["usage"]["prompt_tokens"]
            for r in agent_attempts
            if (r.get("usage") or {}).get("prompt_tokens") is not None
        ]
        agent_calls = Counter(
            c["name"] for r in rows if r["t"] == "llm" for c in r.get("tool_calls", [])
        )
        agents.append(
            {
                "trace": str(path.relative_to(root)),
                "start": first,
                "end": last,
                "attempts": len(agent_attempts),
                "known_prompt_tokens": sum(agent_prompts),
                "max_prompt_tokens": max(agent_prompts, default=None),
                "tool_attempts": dict(agent_calls),
            }
        )
        if path.stem != "main_agent":
            starts[path.stem.rsplit(".t", 1)[0]].append(first)
        for row_index, row in enumerate(rows):
            if row["t"] == "attempt" and row.get("phase") == "finished":
                attempts.append(row)
            if row["t"] == "result":
                tool_name = row.get("name", "")
                tools[tool_name] += 1
                duration = row.get("ms")
                if (
                    isinstance(duration, (int, float))
                    and not isinstance(duration, bool)
                    and duration >= 0
                ):
                    tool_latencies[tool_name].append(float(duration))
                else:
                    tool_missing_duration[tool_name] += 1
                # Only the explicit telemetry flag is authoritative here. A string
                # containing "Error" may be quoted source data, not an execution error.
                if row.get("error"):
                    tool_errors[tool_name] += 1
            if row["t"] != "llm":
                continue
            outcome = attempt_outcomes[row_index]
            executed = outcome is None or outcome in ACCEPTED_ATTEMPT_OUTCOMES
            for call in row.get("tool_calls", []):
                args = call.get("args") or {}
                name = call["name"]
                tool_attempts[name] += 1
                if name == "assign_task":
                    for task in args.get("tasks") or []:
                        dispatches[task.get("agent", "")].append(row["ts"])
                        if not task.get("verification_checks"):
                            research_jobs += 1
                if name == "submit_report" and not args.get("verification_results"):
                    report_times.append(row["ts"])
                if executed and name in {
                    "web_search",
                    "corpus_search",
                    "web_fetch",
                    "corpus_fetch",
                }:
                    queries[name + ":" + json.dumps(args, sort_keys=True, ensure_ascii=False)] += 1
    begin = min((a["start"] for a in agents), default=None)
    end = max((a["end"] for a in agents), default=None)
    delays = []
    # Failed admissions have no corresponding start. Match each start to the earliest
    # preceding unmatched request; this is an estimate, not authoritative bus telemetry.
    for name, times in starts.items():
        pending = sorted(dispatches[name])
        for started in sorted(times):
            eligible = [t for t in pending if t <= started]
            if eligible:
                assigned = eligible[0]
                pending.remove(assigned)
                delays.append(round(started - assigned, 3))
    known = [a for a in attempts if (a.get("usage") or {}).get("prompt_tokens") is not None]
    prompt = sum(a["usage"]["prompt_tokens"] for a in known)
    cache_known = [a for a in known if a["usage"].get("cache_read_tokens") is not None]
    cache_prompt = sum(a["usage"]["prompt_tokens"] for a in cache_known)
    cache_read = sum(a["usage"]["cache_read_tokens"] for a in cache_known)
    return {
        "available": True,
        "malformed_events": malformed_events,
        "trajectory_wall_s": round(end - begin, 3) if begin is not None else None,
        "first_research_report_s": round(min(report_times) - begin, 3) if report_times else None,
        "first_report_is_usefulness_score": False,
        "attempts": len(attempts),
        "known_usage_attempts": len(known),
        "unknown_usage_attempts": len(attempts) - len(known),
        "known_prompt_tokens": prompt,
        "max_prompt_tokens": max((a["usage"]["prompt_tokens"] for a in known), default=None),
        "cache_known_attempts": len(cache_known),
        "known_cache_read_tokens": cache_read,
        "cache_hit_rate_on_known_usage": cache_read / cache_prompt if cache_prompt else None,
        "llm_attempt_seconds_sum": round(
            sum((a.get("duration_ms") or 0) for a in attempts) / 1000, 3
        ),
        "llm_sum_is_wall_time": False,
        "outcomes": dict(Counter(a.get("outcome", "unknown") for a in attempts)),
        "failure_reasons": dict(Counter(a["reason"] for a in attempts if a.get("reason"))),
        "tools": dict(tools),
        "tool_attempts": dict(tool_attempts),
        "tool_latency_ms": {
            name: {
                "known": len(tool_latencies[name]),
                "unknown": tool_missing_duration[name],
                "p50": percentile(tool_latencies[name], 0.5),
                "p90": percentile(tool_latencies[name], 0.9),
                "max": max(tool_latencies[name], default=None),
                "sum": sum(tool_latencies[name]) if tool_latencies[name] else None,
                "explicit_errors": tool_errors[name],
            }
            for name in sorted(tools)
        },
        "tool_sum_is_wall_time": False,
        "retrieval_stage_timings": None,
        "research_dispatch_attempts": research_jobs,
        "exact_repeated_tool_requests": sum(n - 1 for n in queries.values()),
        "dispatch_start_delay_estimate_s": delays,
        "dispatch_delay_p50_s": percentile(delays, 0.5),
        "dispatch_delay_p90_s": percentile(delays, 0.9),
        "agents": agents,
        "limitations": [
            "Queue delay inferred from dispatch attempts; rejected requests can skew it.",
            "Parallel attempt durations are not additive wall time.",
            "First report may be incomplete; semantic usefulness requires review.",
            "Dollar cost unavailable without an explicit model tariff.",
            "Tool timings are recorded result durations, not isolated service/queue latency.",
            "Retrieval DB/embedding/rerank/queue timings are unavailable in standard traces.",
            "Tool attempts include denied or interrupted requests; shell use is not automatically waste.",
            "Repeated-request redundancy is booked only for accepted attempts; "
            "retries after discarded attempts or failed calls are recovery.",
        ],
    }
