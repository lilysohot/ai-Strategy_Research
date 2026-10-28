"""Bounded source-preserving excerpts for team handoff and final synthesis.

Selection is deterministic, not a factual verifier. Every retained observation
gets space before any body gets extra space; older counterevidence must not be
evicted just because a later retrieval is long. Originals remain in job traces.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
from typing import Any

from frontier_agent.core.messages import Message, text_of

_BLOCK = "### Retained observation "
_REPORT = re.compile(r"<report\b[^>]*>[\s\S]*?</report>")


def _excerpt(text: str, budget: int) -> str:
    if len(text) <= budget:
        return text
    marker = "\n[excerpt truncated; original remains in the job trajectory]\n"
    available = max(0, budget - len(marker))
    head = available * 3 // 4
    tail = available - head
    return text[:head] + marker + (text[-tail:] if tail else "")


def _entries(messages: list[Message], clean: Callable[[str], str]) -> list[tuple[str, str]]:
    calls: dict[str, tuple[str, dict[str, Any]]] = {}
    entries: list[tuple[str, str]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        for call in message.get("tool_calls") or []:
            function = call.get("function") or {}
            args = function.get("arguments") or call.get("args") or {}
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except (ValueError, TypeError):
                    args = {}
            calls[str(call.get("id") or "")] = (
                str(function.get("name") or call.get("name") or "tool"),
                args if isinstance(args, dict) else {},
            )
        if message.get("role") != "tool":
            continue
        body = clean(text_of(message.get("content"))).strip()
        if not body:
            continue
        call_id = str(message.get("tool_call_id") or "unknown")
        name, args = calls.get(call_id, ("tool", {}))
        # Re-budget our own handoff blocks individually at the coordinator,
        # rather than head-clipping an entire member report a second time.
        if _BLOCK in body:
            prefix = body.split(_BLOCK, 1)[0]
            if "COVERAGE GAP:" in prefix:
                entries.append((f"upstream coverage {call_id}", prefix))
            for block in body.split(_BLOCK)[1:]:
                header, _, content = block.partition("\n")
                report = re.search(r"<report\b[^>]*>", prefix)
                origin = f"{report.group(0)} | " if report else ""
                entries.append((origin + header, content.removesuffix("</report>").strip()))
            continue
        reports = _REPORT.findall(body)
        if reports:
            entries.extend((f"report {call_id}.{i}", block) for i, block in enumerate(reports))
            continue
        source = args.get("url") or args.get("path") or args.get("file_path") or "unspecified"
        # Untrusted labels are data, never instructions or asserted provenance.
        label = json.dumps(source, ensure_ascii=False)
        digest = hashlib.sha256(body.encode()).hexdigest()
        header = (
            f"{call_id[:100]} | tool={name[:80]} | requested_source={label[:1000]} "
            f"| chars={len(body)} | sha256={digest}"
        )
        entries.append((header, body))
    return entries


def evidence_digest(
    messages: list[Message],
    *,
    max_chars: int,
    clean: Callable[[str], str],
) -> str:
    """Allocate bounded space to every observation, with explicit omissions."""
    entries = _entries(messages, clean)
    if not entries:
        return ""
    preamble = (
        "These are source excerpts, not verified findings. Requested URLs identify "
        "tool inputs, not successful acquisition. Keep conflicting values and their "
        "sources separate; do not promote a retelling to a primary-source measurement. "
        "Excerpts may omit facts: consult original job traces for full bodies.\n\n"
    )
    # Bound pathological inventories too, visibly, instead of silently erasing
    # sources. Reserve at least 160 body characters for each included entry.
    retained: list[tuple[str, str]] = []
    used = len(preamble) + 180
    for header, body in entries:
        cost = len(_BLOCK) + len(header) + 5 + min(160, len(body))
        if used + cost > max_chars:
            break
        retained.append((header, body))
        used += cost
    omitted = len(entries) - len(retained)
    if omitted:
        preamble += f"COVERAGE GAP: {omitted} observations omitted by the excerpt budget.\n\n"
    overhead = len(preamble) + sum(len(_BLOCK) + len(h) + 5 for h, _ in retained)
    available = max(0, max_chars - overhead)
    lengths = [len(b) for _, b in retained]
    allocations = [min(160, length) for length in lengths]
    available -= sum(allocations)
    # Once every observation has a minimum excerpt, full-page/file retrievals
    # receive more space than discovery snippets and control acknowledgements.
    # This is source-type allocation, not an assertion about factual authority.
    weights = [
        4 if re.search(r"tool=(?:web_fetch|read_file|doc_reader)\b", header) else 1
        for header, _ in retained
    ]
    pending = {i for i in range(len(retained)) if allocations[i] < lengths[i]}
    while pending and available:
        share = max(1, available // sum(weights[i] for i in pending))
        for i in sorted(pending):
            take = min(share * weights[i], lengths[i] - allocations[i], available)
            allocations[i] += take
            available -= take
            if allocations[i] == lengths[i]:
                pending.remove(i)
    return preamble + "\n\n".join(
        f"{_BLOCK}{header}\n{_excerpt(body, budget)}"
        for (header, body), budget in zip(retained, allocations, strict=True)
    )
