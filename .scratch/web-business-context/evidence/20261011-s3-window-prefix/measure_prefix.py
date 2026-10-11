#!/usr/bin/env python
"""Offline prefix-stability measurement for the cross-turn replay window.

Zero model calls. Drives the **real** write-time trim
(``build_dump`` -> ``trim_to_turns``, i.e. the code path a run actually uses) turn
by turn, with a deterministic stand-in for the summarizer LLM call, and measures
how much of turn N-1's request reappears as a **prefix** of turn N's request.

Why a *prefix* and not a *set*: a provider KV cache matches the longest byte
prefix shared with a previous request. If turn N replays the same nine turns as
turn N-1 but shifted one position, none of those messages are cache hits — they
sit at a different offset. That is the entire question this script answers, and
why "we kept the same turns" is not the same claim as "the prefix survived".

Run:  uv run python .../measure_prefix.py --seed <a real conversation.json>
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from frontier_agent.components.observers.conversation_snapshot import (
    build_dump,
    canonical_json,
    summary_from,
    trim_to_turns,
)
from frontier_agent.core.messages import system_msg
from frontier_agent.core.runtime.loop.context_budget import estimate_tokens

#: A small unit, repeated to build messages of a target size. Deterministic, so
#: two runs of this script are comparable.
UNIT = "背景资料占位，仅用于制造体积；请忽略内容。"

#: Cache reads are billed at a fraction of full price. Aliyun/DeepSeek-style
#: endpoints price them around 10%; the exact number does not change the verdict,
#: so it is a parameter rather than a baked-in claim.
DISCOUNT = 0.1


def pad_to_tokens(seed: str, target_tokens: int) -> str:
    """A string of roughly *target_tokens* tokens (unit-quantised, deterministic)."""
    unit_tokens = max(1, estimate_tokens(seed))
    repeats = max(1, round(target_tokens / unit_tokens))
    return seed * repeats


def user_turn(index: int, tokens: int) -> dict[str, Any]:
    # The turn number is inside the text so no two turns are byte-identical: an
    # accidental repeat would be counted as a cache hit and flatter the result.
    return {"role": "user", "content": f"第 {index} 轮提问：" + pad_to_tokens(UNIT, tokens)}


def assistant_turn(index: int, tokens: int) -> dict[str, Any]:
    return {"role": "assistant", "content": f"第 {index} 轮回答：" + pad_to_tokens(UNIT, tokens)}


def fake_summary(old: str | None, dropped: list[dict[str, Any]], tokens: int) -> str:
    """Stand-in for the summarizer LLM call — deterministic, *and changed each cut*.

    Being deterministic is what makes this script free; changing on every cut is
    what makes it faithful: a real summary absorbs the newly dropped turn, so the
    block cannot stay byte-identical across cuts.

    Bounded, *not* accumulating: the compactor re-compresses (old summary +
    dropped turns) into a summary of roughly constant size. Concatenating the old
    block instead would grow the memory without bound and quietly make the window
    smaller and smaller — a bug this script is meant to *detect*, not commit.
    """
    head = "摘要（含前版记忆）：" if old else "摘要："
    return pad_to_tokens(f"{head}第 {len(dropped)} 条消息已被吸收。", tokens)


def shared_prefix_text(left: str, right: str) -> str:
    """The shared leading text of two serialised requests.

    Cross-check for the message-level metric above: it credits the *partial*
    overlap inside the first differing message too, which message-level counting
    ignores. In token terms the two numbers should be close — if they are not,
    the wire format is reshaping messages and the message-level lower bound
    deserves a second look.
    """
    return os.path.commonprefix([left, right])


def prefix_messages(a: list[dict[str, Any]], b: list[dict[str, Any]]) -> int:
    """How many leading messages are byte-identical (the cacheable prefix, lower bound)."""
    count = 0
    for left, right in zip(a, b, strict=False):
        if canonical_json(left) == canonical_json(right):
            count += 1
        else:
            break
    return count


@dataclass
class Turn:
    index: int
    request_msgs: int
    request_tokens: int
    prefix_msgs: int
    hit_tokens: int
    partial_ratio: float
    ratio: float
    #: Where the new request stops matching the previous one: ``index:role``. This
    #: is the diagnosis, not the score — "index 1 is the summary" says the whole
    #: window slid, "index 9 is a tool result" says one message changed.
    diff_at: str
    cut: dict[str, Any] | None
    summary_changed: bool


@dataclass
class Regime:
    name: str
    max_turns: int
    max_tokens: int
    hysteresis: int


def simulate(
    *,
    seed: dict[str, Any],
    turns: int,
    per_turn_user: int,
    per_turn_assistant: int,
    regime: Regime,
    summary_tokens: int,
) -> list[Turn]:
    """Run the real write-time trim for *turns* turns and record the prefix each turn."""
    system_prompt = str(seed["system_prompt"])
    tool_names = list(seed.get("tool_names") or [])
    tools_hash = str(seed.get("tool_schema_sha256") or "")
    thinking_format = str(seed.get("thinking_format") or "")

    window: list[dict[str, Any]] | None = None
    summary: str | None = None
    previous_request: list[dict[str, Any]] = []
    previous_bytes = ""
    rows: list[Turn] = []

    for index in range(1, turns + 1):
        ask = user_turn(index, per_turn_user)
        # The dump *is* the next request's head, system message included: the
        # kernel does not re-add a system message when ``initial_messages`` is
        # supplied (see ``select_replay``), so re-adding it here would model a
        # request nobody ever sends.
        request = [*(window if window else [system_msg(system_prompt)]), ask]
        ran = [*request, assistant_turn(index, per_turn_assistant)]

        prefix = prefix_messages(previous_request, request) if previous_request else 0
        request_tokens = estimate_tokens(canonical_json(request))
        body = canonical_json(request)
        shared = shared_prefix_text(previous_bytes, body) if previous_bytes else ""
        divergence = ""
        if previous_request and prefix < len(request):
            divergence = f"{prefix}:{request[prefix].get('role', '?')}"
        rows.append(
            Turn(
                index=index,
                request_msgs=len(request),
                request_tokens=request_tokens,
                prefix_msgs=prefix,
                hit_tokens=estimate_tokens(canonical_json(request[:prefix])),
                partial_ratio=(
                    estimate_tokens(shared) / request_tokens if request_tokens else 0.0
                ),
                ratio=0.0,  # filled below
                diff_at=divergence,
                cut=None,
                summary_changed=False,
            )
        )

        # ---- the write-time trim: the same call the observer makes ----
        effective_max_turns = regime.max_turns
        if regime.hysteresis:
            # Emulation of the proposed fix: keep the turn bound *off* until the
            # window overflows by ``hysteresis`` turns, then cut back to the bound
            # in one go. Between cuts every turn is a pure append.
            user_turns = sum(1 for m in ran if m.get("role") == "user")
            effective_max_turns = (
                regime.max_turns if user_turns > regime.max_turns + regime.hysteresis else 0
            )
        head, old_summary = summary_from(ran)
        _, probe = trim_to_turns(
            ran, effective_max_turns, max_tokens=regime.max_tokens, head=head
        )
        new_summary = summary
        if probe is not None:
            dropped = ran[head : int(probe["cut_at"])]
            new_summary = fake_summary(old_summary, dropped, summary_tokens)
        dump = build_dump(
            messages=ran,
            system_prompt=system_prompt,
            tool_names=tool_names,
            tools_hash=tools_hash,
            thinking_format=thinking_format,
            session_id="sim",
            run_id=f"sim-{index}",
            turns_used=index,
            max_replay_turns=effective_max_turns,
            max_replay_tokens=regime.max_tokens,
            summary_block=new_summary,
        )

        row = rows[-1]
        row.ratio = row.hit_tokens / request_tokens if request_tokens else 0.0
        row.cut = dump["trim"]
        row.summary_changed = new_summary != summary
        summary = new_summary
        previous_request = request
        previous_bytes = body
        window = [dict(message) for message in dump["messages"]]

    return rows


def aggregate(rows: list[Turn]) -> dict[str, Any]:
    steady = [row for row in rows if row.index > 1]
    first_cut = next((row.index for row in rows if row.cut), None)
    # "After the window first filled" — the regime the acceptance is about.
    after_fill = [row for row in rows if first_cut and row.index >= first_cut]
    # Effective spend, in "full-price-equivalent tokens": misses at 1.0, hits at
    # the cache discount. A cheap hit ratio only matters if it is cheaper.
    effective = sum(
        row.hit_tokens * DISCOUNT + (row.request_tokens - row.hit_tokens) for row in steady
    )
    return {
        "mean_ratio": sum(row.ratio for row in steady) / len(steady) if steady else 0.0,
        "mean_prompt_tokens": (
            sum(row.request_tokens for row in steady) / len(steady) if steady else 0.0
        ),
        "first_cut": first_cut,
        "mean_ratio_after_fill": (
            sum(row.ratio for row in after_fill) / len(after_fill) if after_fill else None
        ),
        "cuts": sum(1 for row in rows if row.cut),
        "summary_updates": sum(1 for row in rows if row.summary_changed),
        "miss_tokens": sum(row.request_tokens - row.hit_tokens for row in steady),
        "effective_per_turn": effective / len(steady) if steady else 0.0,
        "mean_partial_ratio": (
            sum(row.partial_ratio for row in steady) / len(steady) if steady else 0.0
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--seed", required=True, help="a real conversation.json")
    parser.add_argument("--turns", type=int, default=45)
    parser.add_argument("--per-turn-user", type=int, default=250)
    parser.add_argument("--per-turn-assistant", type=int, default=300)
    parser.add_argument("--summary-tokens", type=int, default=300)
    parser.add_argument("--max-turns", type=int, default=10, help="the shipped default")
    parser.add_argument("--max-tokens", type=int, default=114_688, help="229376 // 2")
    args = parser.parse_args()

    seed = json.loads(Path(args.seed).read_text(encoding="utf-8"))
    system_tokens = estimate_tokens(canonical_json(system_msg(str(seed["system_prompt"]))))
    print(f"seed            : {args.seed}")
    print(f"system prompt   : {len(seed['system_prompt'])} chars / {system_tokens} est tokens")
    print(
        f"turn size       : user {args.per_turn_user} + assistant {args.per_turn_assistant} "
        f"est tokens (turn 2 onward)"
    )
    print(
        f"bounds          : max_replay_turns={args.max_turns} (shipped default), "
        f"max_replay_tokens={args.max_tokens} (= 229376 // 2)"
    )
    print(f"summary block   : about {args.summary_tokens} est tokens, rewritten on every cut")
    print()

    regimes = [
        Regime("A 现状", args.max_turns, args.max_tokens, 0),
        Regime("B 迟滞 +5", args.max_turns, args.max_tokens, 5),
        Regime("C 只留 token 预算", 0, args.max_tokens, 0),
    ]

    for regime in regimes:
        rows = simulate(
            seed=seed,
            turns=args.turns,
            per_turn_user=args.per_turn_user,
            per_turn_assistant=args.per_turn_assistant,
            regime=regime,
            summary_tokens=args.summary_tokens,
        )
        print(
            f"=== {regime.name} (max_replay_turns={regime.max_turns}, "
            f"hysteresis={regime.hysteresis}) ==="
        )
        print(" turn  req_msgs  req_tok  kept_msgs  hit_tok  hit%  part%  cut  summ  diverges_at")
        for row in rows:
            mark = "CUT" if row.cut else "-"
            flag = "new" if row.summary_changed else ""
            print(
                f" {row.index:>4}  {row.request_msgs:>8}  {row.request_tokens:>7}  "
                f"{row.prefix_msgs:>9}  {row.hit_tokens:>7}  "
                f"{row.ratio * 100:>5.1f}  {row.partial_ratio * 100:>5.1f}  "
                f"{mark:>3}  {flag:>4}  {row.diff_at:>12}"
            )
        stats = aggregate(rows)
        after = stats["mean_ratio_after_fill"]
        print(
            f"  -> mean hit {stats['mean_ratio'] * 100:.1f}%  "
            f"(counting the partial message too: {stats['mean_partial_ratio'] * 100:.1f}%)  "
            f"mean prompt {stats['mean_prompt_tokens']:,.0f} tok  "
            f"first cut: turn {stats['first_cut']}  "
            f"hit after fill: " + (f"{after * 100:.1f}%" if after is not None else "n/a")
        )
        print(
            f"  -> cuts {stats['cuts']}  summary rewrites {stats['summary_updates']}  "
            f"miss tokens {stats['miss_tokens']:,.0f}  "
            f"effective {stats['effective_per_turn']:,.0f} tok/turn (hits at {DISCOUNT:g}x)"
        )
        print()

    print("=== turn-size sweep (regime A): does the collapse depend on size? ===")
    print("  user tok/turn   first cut   hit% after fill")
    for size in (100, 250, 1_000, 3_000):
        rows = simulate(
            seed=seed,
            turns=args.turns,
            per_turn_user=size,
            per_turn_assistant=args.per_turn_assistant,
            regime=Regime("A", args.max_turns, args.max_tokens, 0),
            summary_tokens=args.summary_tokens,
        )
        stats = aggregate(rows)
        after = stats["mean_ratio_after_fill"]
        print(
            f" {size:>13}   {stats['first_cut']!s:>9}   "
            + (f"{after * 100:>5.1f}%" if after is not None else "n/a")
        )
    print()
    print("note: 'kept_msgs' counts byte-identical *leading messages* — a lower bound on")
    print("      the provider's byte-prefix cache. Equal messages at a shifted offset")
    print("      contribute nothing: a set match is not a prefix match.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
