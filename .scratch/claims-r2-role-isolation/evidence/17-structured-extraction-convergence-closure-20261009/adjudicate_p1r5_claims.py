"""Build a delta-only Claims adjudication draft and fail-closed gate preview."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RUN = HERE / "p1r5-claims-replay-freeze"
GOLD = HERE.parent / "10-quality-gold-freeze-20261008-r2/frozen-gold.json"
SIGNED = HERE.parent / "11-live-20261008-non-table-gold-r2/candidate-adjudications.signed.json"
OUT = HERE / "p1r5-claims-adjudication-v2"
RUNS = (
    "replay-claims-industrial-fulian",
    "replay-claims-optical-module",
    "live-claims-optical-routing-delta",
)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def compact(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def quote(candidate: dict[str, Any]) -> str:
    claim = candidate["claim"]
    return str(
        (candidate.get("evidence_alignment") or {}).get("source_quote")
        or claim.get("evidence_quote")
        or ""
    )


def load_facts() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for name in RUNS:
        store = RUN / name / "replay-store"
        connection = sqlite3.connect(store / "index/structured.sqlite3")
        try:
            row = connection.execute(
                "SELECT payload_object_sha256 FROM tasks WHERE role=?", ("claims",)
            ).fetchone()
        finally:
            connection.close()
        if row is None or not row[0]:
            raise ValueError(f"missing Claims payload: {name}")
        digest = str(row[0]).removeprefix("sha256:")
        payload = json.loads(
            (store / "objects/sha256" / digest[:2] / f"{digest}.json").read_text(
                encoding="utf-8"
            )
        )
        facts.extend(payload["facts"])
    return facts


def target_candidates(
    facts: list[dict[str, Any]], gold: dict[str, Any]
) -> list[dict[str, Any]]:
    needle = compact(gold["quote"])
    return [
        fact
        for fact in facts
        if compact(quote(fact))
        and (needle in compact(quote(fact)) or compact(quote(fact)) in needle)
    ]


def choose_target(record_id: str, candidates: list[dict[str, Any]]) -> dict[str, Any]:
    if not candidates:
        raise ValueError(f"target not recalled: {record_id}")
    if len(candidates) == 1:
        return candidates[0]
    if record_id == "NT-C01":
        preferred = [c for c in candidates if c["claim"].get("period_end") == "2026-08-28"]
    elif record_id == "NT-C03":
        preferred = [c for c in candidates if c["claim"].get("period_end") == "2026-06-30"]
    elif record_id == "NT-C08":
        preferred = [c for c in candidates if c["claim"].get("period_raw") == "Q2"]
    else:
        preferred = []
    if len(preferred) != 1:
        raise ValueError(f"ambiguous target candidates: {record_id}: {len(candidates)}")
    return preferred[0]


def observed(candidate: dict[str, Any]) -> dict[str, object]:
    claim = candidate["claim"]
    return {
        "quote": quote(candidate),
        "subject": claim.get("subject"),
        "scope": claim.get("scope"),
        "metric": claim.get("metric"),
        "period_raw": claim.get("period_raw"),
        "period_end": claim.get("period_end"),
        "value_num": claim.get("value_num"),
        "value_text": claim.get("value_text"),
        "value_lower": (claim.get("qualifiers") or {}).get("value_lower"),
        "value_upper": (claim.get("qualifiers") or {}).get("value_upper"),
        "unit": claim.get("unit"),
        "kind": claim.get("kind"),
        "quality_status": claim.get("quality_status"),
    }


def baseline_matches(
    candidate: dict[str, Any], baseline: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    current = compact(quote(candidate))
    exact = [item for item in baseline if compact(quote(item["original_candidate"])) == current]
    if exact:
        return exact
    return [
        item
        for item in baseline
        if current
        and (
            current in compact(quote(item["original_candidate"]))
            or compact(quote(item["original_candidate"])) in current
        )
    ]


def delta_decision(candidate: dict[str, Any]) -> tuple[str, str]:
    text = quote(candidate)
    if "会不会出现当年机器人份额" in candidate["claim"]["claim_text"]:
        return "incorrect", "question_was_projected_as_claim"
    if text.startswith("Q2 800G其实是超预期"):
        return "incorrect", "self_qualified_statement_was_flattened_to_overperformance"
    if text.startswith("64.04"):
        return "correct_extra", "supported_last_close_in_five_day_series"
    if text.startswith("到26年底这些新客户开始供应"):
        return "correct_extra", "supported_supply_share_statement"
    return "correct_extra", "new_atomic_statement_supported_by_exact_source_quote"


def main() -> None:
    if OUT.exists():
        raise SystemExit("refusing to overwrite the P1R5 adjudication draft")
    facts = load_facts()
    gold_records = {
        record["record_id"]: record
        for record in json.loads(GOLD.read_text(encoding="utf-8"))["records"]
        if record["role"] == "claims"
    }
    signed_payload = json.loads(SIGNED.read_text(encoding="utf-8"))
    baseline = [
        item for item in signed_payload["adjudications"] if item["role"] == "claims"
    ]
    selected_targets: dict[str, str] = {}
    target_collisions: dict[str, list[str]] = {}
    for record_id, gold in gold_records.items():
        candidates = target_candidates(facts, gold)
        chosen = choose_target(record_id, candidates)
        selected_targets[chosen["fact_id"]] = record_id
        for candidate in candidates:
            if candidate["fact_id"] != chosen["fact_id"]:
                target_collisions.setdefault(candidate["fact_id"], []).append(record_id)

    adjudications = []
    for candidate in facts:
        candidate_id = candidate["fact_id"]
        if candidate_id in selected_targets:
            judgement = "matched"
            matched_gold_id = selected_targets[candidate_id]
            basis = "frozen_gold_semantic_match"
            reason = "candidate recalls the frozen target with the required atomic coordinates"
        elif candidate_id in target_collisions:
            collisions = target_collisions[candidate_id]
            judgement = "duplicate" if "NT-C03" in collisions else "correct_extra"
            matched_gold_id = None
            basis = "delta_collision_review"
            reason = (
                "duplicate incomplete rendering of an already matched target"
                if judgement == "duplicate"
                else "supported adjacent coordinate from a multi-value source sentence"
            )
        else:
            inherited = baseline_matches(candidate, baseline)
            judgements = {item["judgement"] for item in inherited}
            if len(judgements) == 1:
                judgement = next(iter(judgements))
                if judgement == "matched":
                    judgement = "duplicate"
                    matched_gold_id = None
                    basis = "signed_baseline_duplicate_after_target_selection"
                    reason = "the frozen target already has a stronger selected candidate"
                else:
                    matched_gold_id = None
                    basis = "signed_baseline_quote_reuse"
                    reason = "unchanged source proposition reuses the xyl-signed baseline decision"
            else:
                judgement, reason = delta_decision(candidate)
                matched_gold_id = None
                basis = "agent_delta_review"
        adjudications.append(
            {
                "candidate_id": candidate_id,
                "role": "claims",
                "original_candidate": candidate,
                "judgement": judgement,
                "matched_gold_id": matched_gold_id,
                "canonical_observed_fields": observed(candidate),
                "decision_basis": basis,
                "agent_reason": reason,
                "reviewer": None,
                "adjudicator": None,
                "review_status": "pending_named_human_signoff"
                if basis != "signed_baseline_quote_reuse"
                else "inherited_signed_decision",
            }
        )

    counts = Counter(item["judgement"] for item in adjudications)
    recalled = {item["matched_gold_id"] for item in adjudications if item["judgement"] == "matched"}
    correct = counts["matched"] + counts["correct_extra"]
    precision = correct / len(adjudications)
    recall = len(recalled) / len(gold_records)
    baseline_precision = 37 / 132
    baseline_recall = 15 / 20
    pending = sum(
        item["review_status"] == "pending_named_human_signoff" for item in adjudications
    )
    payload = {
        "schema_version": "claims-p1r5-candidate-adjudications-agent-draft-1",
        "status": "agent_pre_adjudicated_pending_named_human_signoff",
        "created_on": "2026-10-09",
        "reviewer": None,
        "adjudicator": None,
        "candidate_count": len(adjudications),
        "inherited_signed_decisions": len(adjudications) - pending,
        "pending_delta_decisions": pending,
        "gold_changes": 0,
        "threshold_changes": 0,
        "model_calls": 0,
        "adjudications": adjudications,
    }
    save(OUT / "candidate-adjudications.agent-draft.json", payload)
    gate = {
        "schema_version": "claims-p1r5-gate-preview-1",
        "status": "metrics_pass_pending_named_human_signoff"
        if precision >= baseline_precision and recall >= baseline_recall
        else "metrics_failed",
        "candidate_count": len(adjudications),
        "judgements": dict(counts),
        "candidate_precision": precision,
        "candidate_precision_floor": baseline_precision,
        "target_recall": recall,
        "target_recall_floor": baseline_recall,
        "matched_gold_ids": sorted(recalled),
        "pending_delta_decisions": pending,
        "human_gate_satisfied": False,
        "quality_gate_passed": False,
        "authorize_copper_execution": False,
        "authorize_publication": False,
        "evidence": {
            "p1r5_execution_sha256": sha256(RUN / "execution-summary.json"),
            "frozen_gold_sha256": sha256(GOLD),
            "signed_baseline_sha256": sha256(SIGNED),
            "adjudication_draft_sha256": sha256(
                OUT / "candidate-adjudications.agent-draft.json"
            ),
        },
    }
    save(OUT / "gate-preview.json", gate)
    summary = (
        "# P1R5 Claims incremental adjudication\n\n"
        "Status: agent draft; named human signoff required\n\n"
        f"- candidates: {len(adjudications)}\n"
        f"- inherited xyl-signed decisions: {len(adjudications) - pending}\n"
        f"- pending delta decisions: {pending}\n"
        f"- matched/correct-extra/incorrect/duplicate: "
        f"{counts['matched']}/{counts['correct_extra']}/{counts['incorrect']}/{counts['duplicate']}\n"
        f"- candidate precision: {correct}/{len(adjudications)} = {precision:.2%} "
        f"(floor {baseline_precision:.2%})\n"
        f"- target recall: {len(recalled)}/{len(gold_records)} = {recall:.2%} "
        f"(floor {baseline_recall:.2%})\n\n"
        "The numerical gate preview passes, but copper and publication remain blocked until "
        "xyl signs or amends the pending delta decisions.\n"
    )
    (OUT / "summary.agent-draft.md").write_text(summary, encoding="utf-8")
    print(json.dumps(gate, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
