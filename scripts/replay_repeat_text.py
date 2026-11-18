"""Replay the repeated-notice gate against a frozen trajectory (no model calls).

Every decision is taken by the production function
(:func:`workflows.agent_team.observers.evidence_boundary.boundary_notice`), not by
a copy of its rule, and each one is checked afterwards: after a kept *or* omitted
notice, the most recent boundary state in the replayed history must equal the
state that was current at that point. An omission that leaves the model reading an
older state therefore shows up as a mismatch instead of a saving.

Two wordings are reported:

* ``current`` — today's constants, replayed over the recorded state sequence. This
  is the estimate for a future run.
* ``historical`` — the wording the recorded run actually used (its own rules
  block), so the same mechanism can be compared against a byte-faithful baseline.

The check-block section is **potential**, not verified: the trajectory records
neither compaction generations nor the run's result cap, so the production
admission (generation + delivered cap) cannot be replayed honestly from it.

Usage:

    uv run python scripts/replay_repeat_text.py \
        --trajectory results/team-workflow-v1-semantic/F01-r1/agent/trajectories/main_agent.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Sequence
from typing import Any

from plugins.tools.collect_reports import _VERIFICATION_STATUS_REF
from workflows.agent_team.observers.evidence_boundary import (
    _RULES,
    _RULES_REF,
    _boundary_state_of,
    boundary_notice,
)

CHECKS = "[version-bound checks]"


def _decide(
    messages: Sequence[dict[str, Any]],
    notices: Sequence[tuple[int, str]],
    *,
    rules: str,
    rules_ref: str,
) -> dict[str, Any]:
    """Replay every recorded notice through the production decision."""
    history: list[dict[str, Any]] = []
    decisions: list[dict[str, Any]] = []
    mismatches: list[dict[str, Any]] = []
    baseline = sent = 0
    by_decision = {"full_rules": 0, "reference": 0, "omitted": 0}
    recorded = dict(notices)
    for index, message in enumerate(messages):
        state = recorded.get(index)
        if state is None:
            history.append(message)
            continue

        baseline += len(rules) + 1 + len(state)
        notice = boundary_notice(history, state, rules=rules, rules_ref=rules_ref)
        if notice is None:
            by_decision["omitted"] += 1
            label = "omitted"
            chars = 0
        else:
            history.append({"role": "user", "content": notice})
            chars = len(notice)
            sent += chars
            label = "reference" if notice.startswith(rules_ref) else "full_rules"
            by_decision[label] += 1

        latest = ""
        for earlier in history:
            found = _boundary_state_of(earlier.get("content"))
            if found is not None:
                latest = found
        if latest != state:
            mismatches.append(
                {
                    "notice_index": index,
                    "decision": label,
                    "recorded_state_sha": hashlib.sha256(state.encode()).hexdigest()[:12],
                    "latest_state_sha": hashlib.sha256(latest.encode()).hexdigest()[:12],
                }
            )
        decisions.append(
            {
                "notice_index": index,
                "decision": label,
                "chars": chars,
                "state_sha": hashlib.sha256(state.encode()).hexdigest()[:12],
            }
        )
    return {
        **by_decision,
        "notices": len(notices),
        "baseline_chars": baseline,
        "sent_chars": sent,
        "saved": baseline - sent,
        "states_current_after_every_decision": not mismatches,
        "mismatches": mismatches,
        "decisions": decisions,
    }


def _checks(messages: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Textual repeat volume only — the production gate is not replayed here."""
    blocks = [
        str(message["content"])[str(message["content"]).index(CHECKS) :]
        for message in messages
        if isinstance(message.get("content"), str) and CHECKS in str(message["content"])
    ]
    repeats = [block for block in blocks[1:] if block == blocks[0]] if blocks else []
    return {
        "blocks_seen": len(blocks),
        "textual_repeats": len(repeats),
        "potential_chars_saved": sum(
            max(0, len(block) - len(_VERIFICATION_STATUS_REF)) for block in repeats
        ),
        # No compaction generations and no result cap are recorded in a trajectory,
        # so neither the generation gate nor the delivered-cap gate can be replayed.
        "admission_replayed": False,
    }


def replay(path: str) -> dict[str, Any]:
    with open(path, encoding="utf-8") as handle:
        payload = json.load(handle)
    messages = payload["messages"]
    frozen = json.dumps(messages, ensure_ascii=False, sort_keys=True)

    notices = [
        (index, state)
        for index, message in enumerate(messages)
        if (state := _boundary_state_of(message.get("content"))) is not None
    ]
    legacy_headers = {
        str(messages[index]["content"]).split("\n", 1)[0] for index, _ in notices
    }
    legacy_rules = next(iter(legacy_headers), "")

    current = _decide(messages, notices, rules=_RULES, rules_ref=_RULES_REF)
    historical = _decide(messages, notices, rules=legacy_rules, rules_ref=_RULES_REF)

    return {
        "trajectory": path,
        "messages": len(messages),
        "boundary_notices": len(notices),
        "current_wording": current,
        "historical_wording": {
            **historical,
            "rules_chars": len(legacy_rules),
            "legacy_rules_constant": len(legacy_headers) <= 1,
        },
        "current_rules_chars": len(_RULES),
        "checks": _checks(messages),
        # Proves only that this script did not mutate its input. It says nothing
        # about compaction, reading checkpoints, or result truncation at runtime.
        "input_mutated_by_replay": (
            json.dumps(messages, ensure_ascii=False, sort_keys=True) != frozen
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trajectory", required=True)
    parser.add_argument(
        "--decisions",
        action="store_true",
        help="also print the per-notice decision list",
    )
    args = parser.parse_args()
    report = replay(args.trajectory)
    if not args.decisions:
        report["current_wording"].pop("decisions")
        report["historical_wording"].pop("decisions")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
